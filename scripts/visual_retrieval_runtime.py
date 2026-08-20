#!/usr/bin/env python3
"""Visual retrieval quality patch applied after API-budget/runtime hardening."""
from __future__ import annotations

import subprocess

MARKER = "VISUAL_RETRIEVAL_QUALITY_V2"
ROUTER_MARKER = "VISUAL_SOURCE_ROUTER_V2"
LOCAL_RERANK_MARKER = "LOCAL_CLIP_RERANK_V2"
TEMPLATE_FALLBACK_MARKER = "TEMPLATE_MISMATCH_FALLBACK_V2"

BROLL_CONSTANTS = r'''// VISUAL_RETRIEVAL_QUALITY_V2: bounded local semantic reranking before paid vision.
const LOCAL_RERANK_ENABLED = String(process.env.BROLL_LOCAL_RERANK_ENABLED || "true").toLowerCase() !== "false";
const LOCAL_RERANK_MODEL = process.env.BROLL_LOCAL_RERANK_MODEL || "Xenova/clip-vit-base-patch32";
const LOCAL_RERANK_CANDIDATES = Math.max(4, Number(process.env.BROLL_LOCAL_RERANK_CANDIDATES || 12));
// Total deadline for the entire local rerank stage, not per candidate.
const LOCAL_RERANK_TIMEOUT_MS = Math.max(1000, Number(process.env.BROLL_LOCAL_RERANK_TIMEOUT_MS || 18000));
const TEMPLATE_MISMATCH_THRESHOLD = Math.max(0, Math.min(100, Number(process.env.BROLL_TEMPLATE_FALLBACK_THRESHOLD || 60)));
let localClipPromise = null;
'''

BROLL_HELPERS = r'''// VISUAL_SOURCE_ROUTER_V2: specialist/archive source routing.
function stripHtml(value){return String(value||"").replace(/<[^>]+>/g," ").replace(/\s+/g," ").trim();}

function sourcePriorityFor(visualMode, requested){
  const allowed=new Set(["wikimedia","wikipedia","pexels_video","pexels","unsplash"]);
  const explicit=(Array.isArray(requested)?requested:[]).map(x=>String(x||"").trim()).filter(x=>allowed.has(x));
  if(explicit.length)return explicit.slice(0,5);
  if(visualMode==="archive_scientific")return ["wikimedia","wikipedia","pexels_video","pexels"];
  if(visualMode==="exact_real")return ["wikimedia","wikipedia","pexels_video","pexels","unsplash"];
  return ["pexels_video","pexels","unsplash","wikimedia","wikipedia"];
}

async function fromWikimediaCommons(query){
  if(!query)return [];
  const d=await safeGet(
    "https://commons.wikimedia.org/w/api.php?action=query&generator=search&gsrnamespace=6&gsrlimit="+
    encodeURIComponent(String(Math.min(12,SOURCE_PER_QUERY)))+"&gsrsearch="+encodeURIComponent(query)+
    "&prop=imageinfo&iiprop=url|mime|extmetadata&iiurlwidth=1600&format=json&origin=*",
    {headers:{"User-Agent":"yt-shorts-broll/1.0 (contact: channel owner)"}},20000);
  return Object.values(d?.query?.pages||{}).map(p=>{
    const ii=p?.imageinfo?.[0],meta=ii?.extmetadata||{},mime=String(ii?.mime||"");
    if(!["image/jpeg","image/png","image/webp"].includes(mime))return null;
    const url=ii?.thumburl||ii?.url;if(!url)return null;
    return {type:"image",url,thumb:ii?.thumburl||url,width:ii?.thumbwidth||ii?.width||null,height:ii?.thumbheight||ii?.height||null,
      alt:stripHtml(meta.ImageDescription?.value||p?.title||query),query,source:"wikimedia",
      attribution:stripHtml([meta.Artist?.value?"Image: "+meta.Artist.value:"",meta.LicenseShortName?.value||"",meta.Credit?.value||""].filter(Boolean).join(" | "))};
  }).filter(Boolean);
}

// LOCAL_CLIP_RERANK_V2: local CLIP is a cheap coarse filter; Claude vision remains the final semantic/aesthetic judge.
async function getLocalClip(){
  if(!LOCAL_RERANK_ENABLED)return null;
  if(!localClipPromise)localClipPromise=(async()=>{
    try{
      const mod=await import("@huggingface/transformers");
      if(mod.env){mod.env.cacheDir=process.env.HF_CACHE_DIR||"/app/data/hf-cache";mod.env.allowRemoteModels=true;}
      return await mod.pipeline("zero-shot-image-classification",LOCAL_RERANK_MODEL);
    }catch(err){console.warn("[broll] local CLIP unavailable; metadata rerank only:",err?.message||err);return null;}
  })();
  return localClipPromise;
}

async function vrWithTimeout(promise,ms){
  let timer;try{return await Promise.race([promise,new Promise(resolve=>{timer=setTimeout(()=>resolve(null),Math.max(1,ms));})]);}
  finally{if(timer)clearTimeout(timer);}
}

async function localSemanticRerank(candidates,target,sourcePriority,acceptableSubstitutes=[]){
  const base=[...(candidates||[])].sort((a,b)=>{
    const pa=sourcePriority.indexOf(a.source),pb=sourcePriority.indexOf(b.source);
    const sa=pa<0?999:pa,sb=pb<0?999:pb;if(sa!==sb)return sa-sb;
    return metadataOverlap(b,target)-metadataOverlap(a,target);
  });
  base.forEach(c=>{c.source_rank=Math.max(0,sourcePriority.indexOf(c.source));});
  if(!base.length)return base;
  const deadline=Date.now()+LOCAL_RERANK_TIMEOUT_MS;
  const classifier=await vrWithTimeout(getLocalClip(),Math.max(250,deadline-Date.now()));
  if(!classifier)return base;
  const positives=uniqStrings([target,...(Array.isArray(acceptableSubstitutes)?acceptableSubstitutes:[])])
    .map(x=>String(x).slice(0,160)).slice(0,4);
  const labels=[...positives,"generic unrelated stock footage","generic background scenery"];
  for(const c of base.slice(0,LOCAL_RERANK_CANDIDATES)){
    const remaining=deadline-Date.now();if(remaining<300)break;
    const image=c?.thumb||(c?.type==="image"?c?.url:null);if(!image)continue;
    try{
      const output=await vrWithTimeout(classifier(image,labels),remaining);
      const hits=Array.isArray(output)?output.filter(x=>positives.includes(x?.label)):[];
      const best=hits.reduce((m,x)=>Math.max(m,Number(x?.score)||0),0);
      if(best>0)c.local_similarity=Math.round(best*100);
    }catch{}
  }
  return base.sort((a,b)=>{
    const la=Number.isFinite(Number(a.local_similarity))?Number(a.local_similarity):-1;
    const lb=Number.isFinite(Number(b.local_similarity))?Number(b.local_similarity):-1;
    if(la!==lb)return lb-la;
    const ra=Number.isFinite(Number(a.source_rank))?Number(a.source_rank):999;
    const rb=Number.isFinite(Number(b.source_rank))?Number(b.source_rank):999;
    if(ra!==rb)return ra-rb;
    return metadataOverlap(b,target)-metadataOverlap(a,target);
  });
}

// TEMPLATE_MISMATCH_FALLBACK_V2: relevant deterministic graphics beat misleading low-match stock.
function templateFallbackResponse(best,context,reason){
  const fallback=context?.templateFallback&&typeof context.templateFallback==="object"?context.templateFallback:null;if(!fallback)return null;
  const mustShow=String(context.mustShow||"Key fact").replace(/\s+/g," ").trim().slice(0,72)||"Key fact";
  const rawName=String(fallback.template_name||"");const d=fallback.template_data&&typeof fallback.template_data==="object"?fallback.template_data:{};
  let templateName="kinetic_text",templateData={line:mustShow};
  if(rawName==="stat_reveal"&&String(d.statValue||"").trim()&&String(d.label||"").trim()){templateName=rawName;templateData=d;}
  else if(rawName==="comparison"&&String(d.leftLabel||"").trim()&&String(d.leftValue||"").trim()&&String(d.rightLabel||"").trim()&&String(d.rightValue||"").trim()){templateName=rawName;templateData=d;}
  else if(rawName==="kinetic_text"&&String(d.line||"").trim()){templateName=rawName;templateData=d;}
  return {ok:true,type:"template",visual_source:"template",visual_mode:context.visualMode||"template_explainer",
    template_name:templateName,template_data:templateData,degraded:true,quality_gate_passed:false,fallback_reason:reason,
    score:Number(best?.score||0),relevance:Number(best?.relevance||0),scroll_stop:Number(best?.scroll_stop||0),
    mobile_clarity:Number(best?.mobile_clarity||0),local_similarity:Number(best?.local_similarity||0),threshold:context.threshold,
    first_frame:context.isFirstFrame,selected_query:best?.query||context.queryList?.[0]||null,candidate_count:context.candidates?.length||0,
    scored_count:context.state?.scored?.length||0,vision_calls:context.state?.scene_vision_calls||0,queries_tried:context.queriesTried||[],attribution:""};
}
'''

COLLECT_SIGNATURE = 'async function collectCandidates(queries, subject, { includeWikipedia = true } = {}) {'
COLLECT_REPLACEMENT = r'''async function collectCandidates(queries, subject, { includeWikipedia = true, visualMode = "context_real", sourcePriority = [] } = {}) {
  const priority=sourcePriorityFor(visualMode,sourcePriority),jobs=[];
  // Bound free-source fanout too: at most four routed source families/query.
  const routed=priority.filter(x=>x!=="wikipedia").slice(0,4);
  for(const q of queries){
    for(const source of routed){
      if(source==="pexels_video")jobs.push(fromPexelsVideos(q));
      else if(source==="pexels")jobs.push(fromPexelsPhotos(q));
      else if(source==="unsplash")jobs.push(fromUnsplash(q));
      else if(source==="wikimedia")jobs.push(fromWikimediaCommons(q));
    }
  }
  if(includeWikipedia&&priority.includes("wikipedia"))jobs.push(fromWikipedia(subject));
  const groups=jobs.length?await Promise.all(jobs):[];return dedupeCandidates(groups.flat());
}'''

RANK_REPLACEMENT = r'''function rankCandidates(candidates, target) {
  return [...(candidates||[])].sort((a,b)=>{
    const la=Number.isFinite(Number(a?.local_similarity))?Number(a.local_similarity):-1;
    const lb=Number.isFinite(Number(b?.local_similarity))?Number(b.local_similarity):-1;
    if(la!==lb)return lb-la;
    const ra=Number.isFinite(Number(a?.source_rank))?Number(a.source_rank):999;
    const rb=Number.isFinite(Number(b?.source_rank))?Number(b.source_rank):999;
    if(ra!==rb)return ra-rb;
    const ma=metadataOverlap(a,target),mb=metadataOverlap(b,target);if(ma!==mb)return mb-ma;
    if(a?.type!==b?.type)return a?.type==="video"?-1:1;
    return 0;
  });
}'''

SUCCESS_REPLACEMENT = r'''function successResponse(best, context) {
  const { threshold, isFirstFrame, queryList, queriesTried, candidates, state, searchRounds, visualMode } = context;
  const runBudget = getRunBudgetState(state.run_id);
  return {
    ok: true,
    type: best.type,
    url: best.url,
    source: best.source,
    score: best.score,
    relevance: best.relevance,
    scroll_stop: best.scroll_stop,
    mobile_clarity: best.mobile_clarity,
    composition: best.composition,
    motion_energy: best.motion_energy,
    uniqueness: best.uniqueness,
    local_similarity: best.local_similarity ?? null,
    visual_mode: visualMode || null,
    quality_gate_passed: true,
    degraded: false,
    threshold,
    first_frame: isFirstFrame,
    selected_query: best.query || queryList[0],
    candidate_count: candidates.length,
    scored_count: state.scored.length,
    vision_calls: state.scene_vision_calls,
    cache_hits: state.cache_hits,
    search_rounds: searchRounds,
    queries_tried: queriesTried,
    run_vision_used: runBudget.used,
    run_vision_remaining: runBudget.remaining,
    attribution: best.attribution || "",
  };
}'''


def _replace_between(text: str, start_sig: str, next_sig: str, replacement: str) -> str:
    start = text.find(start_sig)
    if start < 0:
        raise ValueError(f"visual retrieval start anchor missing: {start_sig}")
    nxt = text.find(next_sig, start + len(start_sig))
    if nxt < 0:
        raise ValueError(f"visual retrieval next anchor missing: {next_sig}")
    return text[:start] + replacement + "\n\n" + text[nxt:]


def patch_visual_retrieval(text: str) -> str:
    if MARKER in text:
        return text
    anchor = "const scoreCache = new Map();"
    if anchor not in text:
        raise ValueError("score cache anchor missing before visual retrieval patch")
    text = text.replace(anchor, BROLL_CONSTANTS + "\n" + anchor, 1)
    if COLLECT_SIGNATURE not in text:
        raise ValueError("API-budget collectCandidates signature missing")
    text = text.replace(COLLECT_SIGNATURE, BROLL_HELPERS + "\n\n" + COLLECT_SIGNATURE, 1)
    text = _replace_between(text, COLLECT_SIGNATURE, "function rankCandidates(", COLLECT_REPLACEMENT)
    text = _replace_between(text, "function rankCandidates(", "function scoreCacheKey(", RANK_REPLACEMENT)

    old = "  creative_format,\n  run_id,\n} = {}) {"
    new = "  creative_format,\n  visual_mode,\n  must_show,\n  acceptable_substitutes,\n  source_priority,\n  template_fallback,\n  run_id,\n} = {}) {"
    if old not in text:
        raise ValueError("resolveBroll visual contract arg anchor missing")
    text = text.replace(old, new, 1)
    old = "  const target = subj || searchTarget || desc;"
    new = "  const mustShow=String(must_show||'').trim();\n  const visualMode=String(visual_mode||'context_real').trim();\n  const sourcePriority=sourcePriorityFor(visualMode,source_priority);\n  const acceptableSubstitutes=Array.isArray(acceptable_substitutes)?acceptable_substitutes.map(String).filter(Boolean).slice(0,3):[];\n  const target=mustShow||subj||searchTarget||desc;"
    if old not in text:
        raise ValueError("soft-fallback target anchor missing")
    text = text.replace(old, new, 1)
    old = "let candidates = await collectCandidates(initialQueries, subj, { includeWikipedia: true });"
    new = "let candidates = await collectCandidates(initialQueries, subj, { includeWikipedia: true, visualMode, sourcePriority });\n  candidates = await localSemanticRerank(candidates, target, sourcePriority, acceptableSubstitutes);"
    if old not in text:
        raise ValueError("initial candidate collection anchor missing")
    text = text.replace(old, new, 1)
    old = "const expanded = await collectCandidates(extraQueries, subj, { includeWikipedia: false });\n    candidates = dedupeCandidates([...candidates, ...expanded]);"
    new = "const expanded = await collectCandidates(extraQueries, subj, { includeWikipedia: false, visualMode, sourcePriority });\n    candidates = await localSemanticRerank(dedupeCandidates([...candidates, ...expanded]), target, sourcePriority, acceptableSubstitutes);"
    if old not in text:
        raise ValueError("expanded candidate collection anchor missing")
    text = text.replace(old, new, 1)
    old = "      score: result.dimensions.overall,\n      cache_hit: result.cache_hit === true,"
    new = "      score: result.dimensions.overall,\n      local_similarity: result.candidate.local_similarity ?? null,\n      source_rank: result.candidate.source_rank ?? null,\n      cache_hit: result.cache_hit === true,"
    if old not in text:
        raise ValueError("score telemetry anchor missing")
    text = text.replace(old, new, 1)
    text = _replace_between(text, "function successResponse(", "// BROLL_SOFT_FALLBACK: preserve completion while retaining quality telemetry.", SUCCESS_REPLACEMENT)
    text = text.replace("{ threshold, isFirstFrame, queryList, queriesTried, candidates, state, searchRounds });", "{ threshold, isFirstFrame, queryList, queriesTried, candidates, state, searchRounds, visualMode });")

    no_start = text.find("if (!candidates.length)")
    best_pos = text.find("const best", no_start)
    no_end = text.rfind("\n", no_start, best_pos) + 1 if best_pos >= 0 else -1
    if no_start < 0 or best_pos < 0 or no_end <= no_start:
        raise ValueError("no-candidates fallback anchors missing")
    no_start = text.rfind("\n", 0, no_start) + 1
    no_block = '''  if (!candidates.length) {
    const template=templateFallbackResponse(null,{templateFallback:template_fallback,mustShow,visualMode,threshold,isFirstFrame,queryList,queriesTried,candidates,state},"no_candidates");
    if(template)return template;
    return { ok: false, reason: "no_candidates", threshold, queries_tried: queriesTried, vision_calls: state.scene_vision_calls, search_rounds: searchRounds };
  }'''
    text = text[:no_start] + no_block + text[no_end:]

    sf_start = text.find("  const degraded = softFallbackResponse(fallback, {")
    sf_end_marker = "  if (degraded) return degraded;"
    sf_end = text.find(sf_end_marker, sf_start)
    if sf_start < 0 or sf_end < 0:
        raise ValueError("soft real-media fallback anchors missing")
    sf_end += len(sf_end_marker)
    sf_block = '''  if(best&&Number(best.score||0)<TEMPLATE_MISMATCH_THRESHOLD){
    const template=templateFallbackResponse(best,{templateFallback:template_fallback,mustShow,visualMode,threshold,isFirstFrame,queryList,queriesTried,candidates,state},"semantic_mismatch_below_"+TEMPLATE_MISMATCH_THRESHOLD);
    if(template)return template;
  }
  const degraded = softFallbackResponse(fallback, {
    threshold,
    isFirstFrame,
    queryList,
    queriesTried,
    candidates,
    state,
    searchRounds,
    runBudget,
  }, reason);
  if (degraded) {
    degraded.local_similarity=fallback?.local_similarity??null;
    degraded.visual_mode=visualMode;
    return degraded;
  }'''
    text = text[:sf_start] + sf_block + text[sf_end:]
    text = text.replace("// PREPROD_BROLL_HARDENING: one bounded retry for transient/free stock lookups.", "// VISUAL_RETRIEVAL_QUALITY_V2\n// PREPROD_BROLL_HARDENING: one bounded retry for transient/free stock lookups.", 1)
    return text


def self_test_visual_retrieval(text: str) -> None:
    for marker in [MARKER, ROUTER_MARKER, LOCAL_RERANK_MARKER, TEMPLATE_FALLBACK_MARKER, "fromWikimediaCommons", "templateFallbackResponse", "local_similarity"]:
        if marker not in text:
            raise RuntimeError(f"visual retrieval patch missing {marker}")
    start = text.index("function templateFallbackResponse(")
    end = text.index("\nasync function collectCandidates(", start)
    helper = text[start:end]
    harness = helper + r'''
const r=templateFallbackResponse(
 {score:54,relevance:45,scroll_stop:60,mobile_clarity:80,local_similarity:31,query:'underwater volcano'},
 {templateFallback:{template_name:'kinetic_text',template_data:{line:'New ocean floor forms here'}},mustShow:'new ocean floor forming',visualMode:'archive_scientific',threshold:72,isFirstFrame:false,queryList:['underwater volcano'],queriesTried:['underwater volcano'],candidates:[1,2],state:{scored:[1],scene_vision_calls:3}},
 'semantic_mismatch_below_60');
if(!r||r.ok!==true||r.type!=='template'||r.visual_source!=='template')throw new Error('template fallback did not return template');
if(r.score!==54||r.local_similarity!==31||r.template_name!=='kinetic_text')throw new Error('template fallback telemetry drifted');
const invalid=templateFallbackResponse({score:40},{templateFallback:{template_name:'comparison',template_data:{leftLabel:'only one'}},mustShow:'fallback line',threshold:72,state:{scored:[]}},'x');
if(invalid.template_name!=='kinetic_text'||!invalid.template_data.line)throw new Error('invalid complex template did not degrade safely');
console.log('visual retrieval template fallback OK');
'''
    p = subprocess.run(["node", "-e", harness], text=True, capture_output=True)
    if p.returncode != 0:
        raise RuntimeError("visual retrieval regression failed:\n" + p.stdout + p.stderr)
