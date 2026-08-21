#!/usr/bin/env python3
"""Align Shorts prompts/runtime settings to reliable, retrievable video production."""
from __future__ import annotations

import re

MARKER = "QUALITY_ALIGNMENT"
RELIABILITY_MARKER = "RELIABILITY_FIRST_VIDEO"
VISUAL_ROUTER_MARKER = "VISUAL_SOURCE_ROUTER_V2"
VISUAL_TELEMETRY_MARKER = "VISUAL_RETRIEVAL_TELEMETRY_V2"

PUBLISH_MINIMUMS = {
    "concept_strength": 68,
    "hook_strength": 70,
    "evidence_strength": 70,
    "payoff_strength": 68,
    "information_density": 66,
    "first_frame_strength": 70,
    "visual_progression": 66,
    "shareability": 71,
    "naturalness": 66,
    "distinctiveness": 64,
    "voice_specificity": 62,
    "overall": 69,
}
VISUAL_PLAN_MINIMUM = 70


def node_by_name(workflow: dict, name: str) -> dict:
    for node in workflow.get("nodes", []):
        if node.get("name") == name:
            return node
    raise KeyError(f"required n8n node not found: {name}")


def _prepend_user_instruction(body: str, instruction: str) -> str:
    marker = 'content: "'
    if instruction in body:
        return body
    if marker not in body:
        raise ValueError("Claude JSON body has no user content anchor")
    return body.replace(marker, marker + instruction.replace('"', '\\"') + "\\n\\n", 1)


def patch_commissioning(workflow: dict) -> None:
    node = node_by_name(workflow, "Claude: Commission Topic Shortlist")
    node["parameters"]["jsonBody"] = r'''={{ JSON.stringify({ model: "claude-sonnet-5", max_tokens: 8192, thinking: { type: "disabled" }, messages: [{ role: "user", content: "You are commissioning ONE production-worthy YouTube Short from a shortlist. QUALITY_ALIGNMENT RELIABILITY_FIRST_VIDEO. Choose a truthful, visually retrievable idea that can actually be produced today. Do not spend output tokens explaining your reasoning.\n\nSHORTLIST: " + JSON.stringify($json.shortlist) + "\n\nEvaluate every input candidate internally for concept, evidence, first-frame strength, payoff, shareability, distinctiveness, novelty, production feasibility, and naturalness. Evidence and stock feasibility matter more than clever wording.\n\nFor the TWO strongest candidates only, return: topic, archetype, research_query, first_frame_concept, share_reason, evidence_score, visual_score, share_score, concept_score, payoff_score, novelty_score, execution_score, distinctiveness_score, share_trigger, send_to_person, novelty_delta, proof_visual, stock_feasibility, stock_query_seed, reason, score. share_trigger must be one of disbelief, identity, argument, useful_warning, awe, humor, status. stock_query_seed must contain 3 short high-inventory visible-noun/action queries. Keep reason under 20 words.\n\nReturn ONLY compact JSON in exactly this shape: {\"candidates\":[...]} with at most 2 candidates, sorted best-first. No prose, no markdown, no thinking text." }] }) }}'''
    node["parameters"].setdefault("options", {})["timeout"] = 120000


def patch_writer(workflow: dict) -> None:
    node = node_by_name(workflow, "Claude: Draft Script (Stage 1)")
    instruction = (
        f"{MARKER} WRITER - {RELIABILITY_MARKER}: Finish a COMPLETE truthful JSON script before optimizing flourishes. "
        "Keep claims inside supplied evidence boundaries. Prefer concrete retrievable visuals and a clear repeatable payoff. "
        "A competent natural Short is publishable; do not make the structure fragile while chasing premium polish."
    )
    node["parameters"]["jsonBody"] = _prepend_user_instruction(node["parameters"]["jsonBody"], instruction)


def patch_editor(workflow: dict) -> None:
    node = node_by_name(workflow, "Claude: Editorial Rewrite (Stage 2)")
    m = PUBLISH_MINIMUMS
    instruction = (
        f"{MARKER} EDITOR - {RELIABILITY_MARKER}: Prioritize a COMPLETE valid truthful script. "
        "Repair obvious weakness without inventing evidence. Prefer a clear producible Short over a more ambitious fragile one. "
        f"These reliability-first publish floors SUPERSEDE stricter numeric floors elsewhere in this prompt: "
        f"concept>={m['concept_strength']}, hook>={m['hook_strength']}, evidence>={m['evidence_strength']}, "
        f"payoff>={m['payoff_strength']}, information_density>={m['information_density']}, "
        f"first_frame>={m['first_frame_strength']}, visual_progression>={m['visual_progression']}, "
        f"shareability>={m['shareability']}, naturalness>={m['naturalness']}, distinctiveness>={m['distinctiveness']}, "
        f"voice_specificity>={m['voice_specificity']}, overall>={m['overall']}."
    )
    node["parameters"]["jsonBody"] = _prepend_user_instruction(node["parameters"]["jsonBody"], instruction)


def patch_visual_director(workflow: dict) -> None:
    node = node_by_name(workflow, "Claude: Visual Director")
    m = PUBLISH_MINIMUMS
    body = r'''={{ JSON.stringify({ model: "claude-sonnet-5", max_tokens: 8192, thinking: { type: "disabled" }, messages: [{ role: "user", content: "You are the INDEPENDENT QUALITY CRITIC and VISUAL DIRECTOR for a YouTube Shorts channel. QUALITY_ALIGNMENT RELIABILITY_FIRST_VIDEO. Return a COMPLETE production-ready JSON script. Reliability and truthfulness outrank perfection.\n\nSCRIPT: " + JSON.stringify($json.script) + "\n\nCOMMISSIONING INTENT: " + JSON.stringify({ share_trigger: $('Extract Generated Topic').item.json.share_trigger || '', send_to_person: $('Extract Generated Topic').item.json.send_to_person || '', novelty_delta: $('Extract Generated Topic').item.json.novelty_delta || '', proof_visual: $('Extract Generated Topic').item.json.proof_visual || '', stock_feasibility: $('Extract Generated Topic').item.json.stock_feasibility || 0, stock_query_seed: $('Extract Generated Topic').item.json.stock_query_seed || [] }) + "\n\nPHASE 1 - QUALITY CHECK\nJudge the actual script against these publish floors: concept_strength __CONCEPT__; hook_strength __HOOK__; evidence_strength __EVIDENCE__; payoff_strength __PAYOFF__; information_density __INFO__; first_frame_strength __FIRST__; visual_progression __VISUAL__; shareability __SHARE__; naturalness __NATURAL__; distinctiveness __DISTINCT__; voice_specificity __VOICE__; overall __OVERALL__. Overall may not exceed the weakest of concept/evidence/first-frame/payoff/shareability by more than 8.\n\nClassify internally as PASS, REPAIRABLE_NEAR_MISS, or HARD_REJECT. HARD_REJECT only if evidence is below its gate, the factual premise itself must change, or a core dimension is more than 8 points below its floor. REPAIRABLE_NEAR_MISS applies when evidence is sound and packaging/writing can be fixed in one pass. Perform at most ONE bounded repair. Preserve factual boundaries, scene order/count, and every scene_index. Rebuild full_script after any wording repair. If the script is competent and truthful, prefer PASS over discarding it for premium-level polish. Set quality_route to pass, repaired_near_miss, or hard_reject and score the FINAL returned script.\n\nPHASE 2 - RETRIEVABLE VISUALS\nChoose creative_format from documentary_cinematic, comparison_reveal, minimal_proof, archival_history, macro_detail, kinetic_data. Set visual_grammar to that family. Set first_frame_type to hero_motion, macro_anomaly, face_reaction, scale_comparison, result_first, archive_proof, or kinetic_stat. Assign visual_role=hero/evidence/detail/comparison/breath/payoff.\n\nVISUAL_SOURCE_ROUTER_V2 - EXECUTABLE VISUAL CONTRACT. The renderer has NO AI image/video generator. Never set visual_type=ai and never describe an impossible synthetic shot as if stock search can retrieve it. For every NON-OUTRO scene add visual_mode from exact_real, context_real, archive_scientific, template_explainer; must_show as one short literal visible subject/action/relationship; acceptable_substitutes as 0-3 short visible alternatives; source_priority as an ordered subset of wikimedia, wikipedia, pexels_video, pexels, unsplash. Use exact_real when the literal subject/action must appear. Use archive_scientific for anatomy, historical/scientific evidence, maps, specimens, spacecraft, oceanography, geology, or named artifacts. Use context_real only when contextual footage genuinely supports the narration. Use template_explainer when the beat requires an X-ray/cutaway, global route, map, scale comparison, before/after reconstruction, numeric comparison, timeline, impossible camera position, or anything stock libraries cannot literally contain. For template_explainer set visual_source=template and template_name ONLY stat_reveal, comparison, or kinetic_text with complete template_data. For every real/archive scene also provide template_fallback={template_name,template_data}; use stat_reveal for one number, comparison for two values, otherwise kinetic_text. A relevant simple template is better than beautiful misleading stock.\n\nFor every NON-TEMPLATE scene create at least 3 concrete Pexels/Unsplash/Wikipedia/Wikimedia search_queries: (1) literal query: visible subject/action, (2) broad fallback: high-inventory core visible noun, (3) a distinct visual variant. Scene 0 should have 4 when useful. Set stock_search_query to the strongest query. Queries must be short visible nouns/actions, not cinematic adjectives or abstract concepts.\n\nSet caption_mode=karaoke/key_phrases/minimal, transition_style=hard_cut, engagement_mode from the actual CTA fields, open_loop_count honestly, and visual_plan_quality 0-100. A usable coherent plan should clear __VISUAL_PLAN__; reserve lower scores for genuinely unrenderable plans.\n\nFINAL INTEGRITY PASS: return ONLY the COMPLETE script JSON. Every scene needs sequential scene_index and non-empty point. Every non-template scene needs visual_role, stock_search_query, >=3 search_queries, visual_mode, must_show, source_priority, and template_fallback. first_frame_type is required. Preserve/rebuild hook_candidates, caption_style, trigger, payoff, quality, full_script, title, tags, seo_description and all other required fields. No prose, markdown, or thinking text." }] }) }}'''
    replacements = {
        "__CONCEPT__": m["concept_strength"], "__HOOK__": m["hook_strength"], "__EVIDENCE__": m["evidence_strength"],
        "__PAYOFF__": m["payoff_strength"], "__INFO__": m["information_density"], "__FIRST__": m["first_frame_strength"],
        "__VISUAL__": m["visual_progression"], "__SHARE__": m["shareability"], "__NATURAL__": m["naturalness"],
        "__DISTINCT__": m["distinctiveness"], "__VOICE__": m["voice_specificity"], "__OVERALL__": m["overall"],
        "__VISUAL_PLAN__": VISUAL_PLAN_MINIMUM,
    }
    for token, value in replacements.items():
        body = body.replace(token, str(value))
    node["parameters"]["jsonBody"] = body
    node["parameters"].setdefault("options", {})["timeout"] = 120000

    # REPAIR_LOOP_V1: reuse the identical critic/visual-director template for
    # the repair pass, but source the script from the failed validation output
    # instead of the fresh editorial draft, and tell it exactly which
    # deterministic checks it needs to fix.
    repair_node = node_by_name(workflow, "Claude: Repair Script")
    script_source_old = "$json.script"
    script_source_new = r"$('Validate Final Script').item.json._failedScript"
    if script_source_old not in body:
        raise ValueError("repair pass: visual-director script-source anchor missing")
    repair_body = body.replace(script_source_old, script_source_new, 1)
    phase1_anchor = "PHASE 1 - QUALITY CHECK"
    if phase1_anchor not in repair_body:
        raise ValueError("repair pass: PHASE 1 anchor missing")
    repair_preamble = (
        "REPAIR PASS - this script already failed the deterministic quality "
        "gate on the exact checks below. Fix precisely these issues while "
        "preserving everything else that already worked, especially every "
        "scene's scene_index/point and full_script consistency. Do not "
        "start over or change the topic. For every field named in a failed "
        "check below (most commonly a scene's narration), the input SCRIPT "
        "already has that field missing, empty, or too short - preserving "
        "it unchanged would just fail the same check again. You MUST write "
        "real, complete content for that exact field; a still-missing field "
        "is a repair failure, not a preserved one.\\n\\nFAILED CHECKS: " + '" + '
        "JSON.stringify($('Validate Final Script').item.json._validationErrors || []) + \""
        "\\n\\n" + phase1_anchor
    )
    repair_body = repair_body.replace(phase1_anchor, repair_preamble, 1
    )
    repair_node["parameters"]["jsonBody"] = repair_body
    repair_node["parameters"].setdefault("options", {})["timeout"] = 120000


def _prioritize_complete_json(node: dict, max_tokens: int) -> None:
    body = str(node.get("parameters", {}).get("jsonBody", ""))
    body = re.sub(r"max_tokens:\s*\d+", f"max_tokens: {max_tokens}", body, count=1)
    body = body.replace('thinking: { type: "adaptive" }, output_config: { effort: "high" },', 'thinking: { type: "disabled" },', 1)
    body = body.replace('thinking: { type: "adaptive" }, output_config: { effort: "medium" },', 'thinking: { type: "disabled" },', 1)
    body = body.replace('thinking: { type: "adaptive" },', 'thinking: { type: "disabled" },', 1)
    if "thinking:" not in body:
        body = re.sub(r"(max_tokens:\s*\d+\s*,)", r'\1 thinking: { type: "disabled" },', body, count=1)
    node["parameters"]["jsonBody"] = body


VISUAL_CONTRACT_NORMALIZER = r"""// VISUAL_SOURCE_ROUTER_V2: make source routing executable and remove impossible AI-only scene requests.
const _vrModes=new Set(['exact_real','context_real','archive_scientific','template_explainer']);
const _vrClean=(v,max=140)=>String(v||'').replace(/\s+/g,' ').trim().slice(0,max);
const _vrStrings=(xs,max=3)=>Array.isArray(xs)?xs.map(x=>_vrClean(x,80)).filter(Boolean).slice(0,max):[];
const _vrKinetic=(s)=>({template_name:'kinetic_text',template_data:{line:_vrClean(s.must_show||s.point||s.narration||'Key fact',72)||'Key fact'}});
const _vrValidTemplate=(obj,s)=>{
  if(!obj||typeof obj!=='object')return _vrKinetic(s);
  const name=String(obj.template_name||''); const d=obj.template_data&&typeof obj.template_data==='object'?obj.template_data:{};
  if(name==='stat_reveal'&&_vrClean(d.statValue,40)&&_vrClean(d.label,72))return {template_name:name,template_data:d};
  if(name==='comparison'&&_vrClean(d.leftLabel,48)&&_vrClean(d.leftValue,48)&&_vrClean(d.rightLabel,48)&&_vrClean(d.rightValue,48))return {template_name:name,template_data:d};
  if(name==='kinetic_text'&&_vrClean(d.line,120))return {template_name:name,template_data:d};
  return _vrKinetic(s);
};
if(Array.isArray(parsed.scenes))parsed.scenes.forEach((s)=>{
  if(!s||s?.template_data?.is_outro)return;
  let mode=_vrClean(s.visual_mode,32);
  if(!_vrModes.has(mode))mode=s.visual_source==='template'?'template_explainer':(_vrClean(s.named_subject,80)?'exact_real':'context_real');
  s.visual_mode=mode;s.must_show=_vrClean(s.must_show||s.named_subject||s.stock_search_query||s.point||s.visual_prompt,120);s.acceptable_substitutes=_vrStrings(s.acceptable_substitutes,3);
  const allowedSources=new Set(['wikimedia','wikipedia','pexels_video','pexels','unsplash']);
  s.source_priority=_vrStrings(s.source_priority,7).filter(x=>allowedSources.has(x));
  if(!s.source_priority.length)s.source_priority=mode==='archive_scientific'?['wikimedia','wikipedia','pexels_video','pexels']:mode==='exact_real'?['wikimedia','wikipedia','pexels_video','pexels','unsplash']:['pexels_video','pexels','unsplash','wikimedia','wikipedia'];
  if(mode==='template_explainer'||s.visual_source==='template'){
    const chosen=_vrValidTemplate({template_name:s.template_name,template_data:s.template_data},s);
    s.visual_mode='template_explainer';s.visual_source='template';s.template_name=chosen.template_name;s.template_data=chosen.template_data;s.visual_type='template';
  }else{if(s.visual_type==='ai'||!s.visual_type)s.visual_type='real';s.template_fallback=_vrValidTemplate(s.template_fallback,s);}
});

"""

TAG_BROLL_CODE = r"""// VISUAL_RETRIEVAL_TELEMETRY_V2: accept real media or deterministic template fallback.
const r=$json;const sceneIndex=$('Split Out Scenes').item.json.scene_index;
if(!r||r.ok!==true)throw new Error('B-roll commissioning rejected scene '+sceneIndex+': '+(r?.reason||r?.fallback_reason||'no asset')+' best_score='+(r?.best_score??r?.score??'n/a')+' threshold='+(r?.threshold??'n/a'));
const out={scene_index:sceneIndex,_source:r.source||'broll',_attribution:r.attribution||'',asset_score:r.score??null,asset_relevance:r.relevance??null,asset_scroll_stop:r.scroll_stop??null,asset_mobile_clarity:r.mobile_clarity??null,asset_local_similarity:r.local_similarity??null,asset_degraded:r.degraded===true,quality_gate_passed:r.quality_gate_passed!==false,fallback_reason:r.fallback_reason||null,selected_query:r.selected_query||null,visual_mode:r.visual_mode||$('Split Out Scenes').item.json.visual_mode||null};
if(r.type==='template'||r.visual_source==='template'){out.visual_source='template';out.template_name=r.template_name||'kinetic_text';out.template_data=r.template_data||{line:String($('Split Out Scenes').item.json.must_show||$('Split Out Scenes').item.json.point||'Key fact').slice(0,72)};return {json:out};}
if(!r.url)throw new Error('B-roll commissioning returned ok without media URL for scene '+sceneIndex);if(r.type==='video')out.video_url=r.url;else out.images=[r.url];return {json:out};"""


def patch_visual_retrieval_contract(workflow: dict) -> None:
    validator = node_by_name(workflow, "Validate Final Script")
    code = str(validator["parameters"]["jsCode"])
    if VISUAL_ROUTER_MARKER not in code:
        anchor = "const errors = [];"
        if anchor not in code: raise ValueError("validator pre-error anchor missing for visual router")
        validator["parameters"]["jsCode"] = code.replace(anchor, VISUAL_CONTRACT_NORMALIZER + anchor, 1)
    resolver = node_by_name(workflow, "Resolve B-roll")
    body = str(resolver["parameters"]["jsonBody"])
    if "must_show:" not in body:
        anchor = "creative_format: ($('Validate Final Script').item.json.creative_format || ''), run_id: String($execution.id || '')"
        replacement = "creative_format: ($('Validate Final Script').item.json.creative_format || ''), visual_mode: ($('Split Out Scenes').item.json.visual_mode || 'context_real'), must_show: ($('Split Out Scenes').item.json.must_show || $('Split Out Scenes').item.json.named_subject || $('Split Out Scenes').item.json.stock_search_query || ''), acceptable_substitutes: ($('Split Out Scenes').item.json.acceptable_substitutes || []), source_priority: ($('Split Out Scenes').item.json.source_priority || []), template_fallback: ($('Split Out Scenes').item.json.template_fallback || null), run_id: String($execution.id || '')"
        if anchor not in body: raise ValueError("Resolve B-roll run_id anchor missing for visual contract")
        resolver["parameters"]["jsonBody"] = body.replace(anchor, replacement, 1)
    node_by_name(workflow, "Tag B-roll")["parameters"]["jsCode"] = TAG_BROLL_CODE
    merge = node_by_name(workflow, "Merge By scene_index (not position)")
    code = str(merge["parameters"]["jsCode"])
    if "asset_local_similarity:" not in code:
        anchor = "    selected_query: v.selected_query,\n    audio: match.audio,"
        replacement = "    selected_query: v.selected_query,\n    asset_local_similarity: v.asset_local_similarity,\n    asset_degraded: v.asset_degraded === true,\n    quality_gate_passed: v.quality_gate_passed !== false,\n    fallback_reason: v.fallback_reason || null,\n    visual_mode: v.visual_mode || match.visual_mode || null,\n    audio: match.audio,"
        if anchor not in code: raise ValueError("merge telemetry anchor missing")
        merge["parameters"]["jsCode"] = code.replace(anchor, replacement, 1)


def patch_reliability(workflow: dict) -> None:
    for name, tokens in {"Claude: Generate Topic":6000,"Claude: Commission Topic Shortlist":8192,"Claude: Draft Script (Stage 1)":8192,"Claude: Editorial Rewrite (Stage 2)":8192,"Claude: Visual Director":8192}.items():
        _prioritize_complete_json(node_by_name(workflow, name), tokens)
    validator=node_by_name(workflow,"Validate Final Script");code=validator["parameters"]["jsCode"]
    for metric,minimum in PUBLISH_MINIMUMS.items(): code=re.sub(rf"({re.escape(metric)}:\s*)\d+",rf"\g<1>{minimum}",code,count=1)
    code=code.replace("if(Number(parsed.visual_plan_quality)<78)errors.push(`visual_plan_quality=${parsed.visual_plan_quality} below publish threshold 78`);",f"if(Number(parsed.visual_plan_quality)<{VISUAL_PLAN_MINIMUM})errors.push(`visual_plan_quality=${{parsed.visual_plan_quality}} below publish threshold {VISUAL_PLAN_MINIMUM}`);")
    code=code.replace("overall > weakest + 5","overall > weakest + 8").replace("by more than 5 points","by more than 8 points")
    validator["parameters"]["jsCode"]=code;validator["notes"]=RELIABILITY_MARKER+": competent-video floors; evidence remains fail-closed"


def upgrade(workflow: dict) -> dict:
    patch_commissioning(workflow);patch_writer(workflow);patch_editor(workflow);patch_visual_director(workflow);patch_visual_retrieval_contract(workflow);patch_reliability(workflow);return workflow


def assert_alignment(workflow: dict) -> None:
    commission=node_by_name(workflow,"Claude: Commission Topic Shortlist")["parameters"]["jsonBody"];writer=node_by_name(workflow,"Claude: Draft Script (Stage 1)")["parameters"]["jsonBody"];editor=node_by_name(workflow,"Claude: Editorial Rewrite (Stage 2)")["parameters"]["jsonBody"];visual=node_by_name(workflow,"Claude: Visual Director")["parameters"]["jsonBody"];extractor=node_by_name(workflow,"Extract Generated Topic")["parameters"]["jsCode"];validator=node_by_name(workflow,"Validate Final Script")["parameters"]["jsCode"];resolver=node_by_name(workflow,"Resolve B-roll")["parameters"]["jsonBody"];tag=node_by_name(workflow,"Tag B-roll")["parameters"]["jsCode"]
    required=[(commission,RELIABILITY_MARKER,"commissioning reliability mode"),(commission,"TWO strongest candidates","bounded commissioner output"),(writer,f"{MARKER} WRITER","writer alignment"),(editor,f"{MARKER} EDITOR","editor alignment"),(visual,"REPAIRABLE_NEAR_MISS","independent near-miss repair"),(visual,"HARD_REJECT","independent hard reject"),(visual,"literal query","retrieval query taxonomy"),(visual,"broad fallback","retrieval broad fallback"),(visual,"quality_route","quality routing telemetry"),(visual,VISUAL_ROUTER_MARKER,"visual source router prompt"),(validator,VISUAL_ROUTER_MARKER,"visual source router normalizer"),(resolver,"must_show:","resolver visual contract"),(resolver,"template_fallback:","resolver template fallback contract"),(tag,VISUAL_TELEMETRY_MARKER,"template/telemetry tagger"),(extractor,"stock_feasibility","commissioning metadata preservation"),(extractor,"novelty_delta","novelty metadata preservation")]
    missing=[label for text,marker,label in required if marker not in text]
    if missing: raise RuntimeError("quality alignment did not land: "+", ".join(missing))
    for name in ["Claude: Generate Topic","Claude: Commission Topic Shortlist","Claude: Draft Script (Stage 1)","Claude: Editorial Rewrite (Stage 2)","Claude: Visual Director"]:
        body=str(node_by_name(workflow,name)["parameters"]["jsonBody"]).strip()
        if not(body.startswith("={{") and body.endswith("}}") and "JSON.stringify(" in body): raise RuntimeError(f"{name} JSON Body lost its n8n expression wrapper")
        if 'thinking: { type: "adaptive" }' in body or 'thinking: { type: "disabled" }' not in body: raise RuntimeError(f"{name} is not configured to prioritize complete JSON")
    if "max_tokens: 8192" not in commission: raise RuntimeError("commissioner response budget is below reliability target")
    if f"concept_strength: {PUBLISH_MINIMUMS['concept_strength']}" not in validator: raise RuntimeError("validator concept floor did not move to reliability calibration")
    if f"shareability: {PUBLISH_MINIMUMS['shareability']}" not in validator: raise RuntimeError("validator shareability floor did not move to reliability calibration")
    if f"visual_plan_quality)<{VISUAL_PLAN_MINIMUM}" not in validator: raise RuntimeError("visual-plan floor did not move to reliability calibration")
    if "at most ONE bounded repair" not in visual: raise RuntimeError("quality repair is no longer explicitly bounded")
    if "Never set visual_type=ai" not in visual: raise RuntimeError("Visual Director can still commission non-existent AI shots")
    if "r.type==='template'" not in tag: raise RuntimeError("Tag B-roll cannot pass template fallbacks into compose")
