#!/usr/bin/env python3
"""Apply the Shorts creative-system V3 upgrade to a V2-upgraded n8n workflow."""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

MARKER = "CREATIVE_SYSTEM_V3"
POOL_NODE = "Parse Topic Pool (V3)"
COMMISSION_NODE = "Claude: Commission Topic Shortlist (V3)"
EDITOR_PARSE_NODE = "Parse Editorial For Visual Director (V3)"
VISUAL_NODE = "Claude: Visual Director (V3)"

ARCHETYPES = [
    "impossible_comparison", "visual_demonstration", "hidden_mechanism",
    "looks_fake_but_real", "counterfactual_consequence", "before_after",
    "misconception_reversal", "historical_moment", "breaking_point",
    "observable_experiment", "scale_transformation", "result_first_explanation",
]
FORMATS = [
    "documentary_cinematic", "comparison_reveal", "minimal_proof",
    "archival_history", "macro_detail", "kinetic_data",
]


def node_by_name(w: dict, name: str) -> dict:
    for n in w.get("nodes", []):
        if n.get("name") == name:
            return n
    raise KeyError(f"required n8n node not found: {name}")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        return text
    if old not in text:
        raise ValueError(f"could not patch {label}: anchor not found")
    return text.replace(old, new, 1)


def voice_bible() -> str:
    p = Path("shorts-compose/channel-voice.json")
    if not p.exists():
        raise FileNotFoundError(str(p))
    return json.dumps(json.loads(p.read_text()), separators=(",", ":"))


def patch_topic_search(w: dict) -> None:
    n = node_by_name(w, "Claude: Generate Topic")
    body = n["parameters"]["jsonBody"]
    if MARKER not in body:
        anchor = "Must NOT closely resemble any of these already-used topics:"
        rules = (
            f"{MARKER} - SEARCH A LARGE CREATIVE SPACE: every candidate must use one viewing archetype from: "
            + ", ".join(ARCHETYPES)
            + ". The archetype is the viewer experience, not the subject category. Rotate archetypes as aggressively as subjects. "
            "A true fact with generic footage or no satisfying payoff is not a strong Short.\\n\\n"
            "Archetype constraints: visual_demonstration must be observable; looks_fake_but_real needs defensible proof; breaking_point needs a real threshold; historical_moment is one event/detail, never a biography; observable_experiment must be safe and instantly legible; result_first_explanation opens on the visible result.\\n\\n"
            + anchor
        )
        body = replace_once(body, anchor, rules, "topic archetype rules")
    body = body.replace("GENERATE 12 DISTINCT candidate topics", "GENERATE 36 DISTINCT candidate topics")
    body = body.replace("max_tokens: 4000", "max_tokens: 9000")
    body = body.replace(
        "where each item has fields: topic (the fact as one plain sentence), research_query",
        "where each item has fields: topic (the fact as one plain sentence), archetype (one exact V3 archetype), research_query",
    )
    n["parameters"]["jsonBody"] = body


def add_topic_commissioning(w: dict) -> None:
    names = {n.get("name") for n in w.get("nodes", [])}
    gen = node_by_name(w, "Claude: Generate Topic")
    if POOL_NODE not in names:
        w["nodes"].append({
            "id": "b675bb82-bbeb-4efe-95ed-706a5ca43573", "name": POOL_NODE,
            "type": "n8n-nodes-base.code", "typeVersion": 2, "position": [2320, 140],
            "parameters": {"jsCode": """const response=$input.first().json;
if(response.error) throw new Error('Topic pool API error: '+JSON.stringify(response.error));
const tb=(response.content||[]).find(b=>b.type==='text'); let raw=String(tb?.text||'').trim().replace(/^```(?:json)?\\s*/i,'').replace(/```\\s*$/,'');
const a=raw.indexOf('{'), z=raw.lastIndexOf('}'); if(a<0||z<=a) throw new Error('Topic pool returned no JSON');
const obj=JSON.parse(raw.slice(a,z+1)); let pool=Array.isArray(obj.candidates)?obj.candidates:[];
pool=pool.filter(c=>c?.topic).map(c=>({topic:String(c.topic).trim(),archetype:String(c.archetype||'looks_fake_but_real').trim(),research_query:String(c.research_query||c.topic).trim(),first_frame_concept:String(c.first_frame_concept||'').trim(),share_reason:String(c.share_reason||'').trim(),evidence_score:Number(c.evidence_score)||0,visual_score:Number(c.visual_score)||0,share_score:Number(c.share_score)||0,reason:String(c.reason||''),score:Number(c.score)||0})).sort((x,y)=>y.score-x.score);
if(pool.length<8) throw new Error('Topic pool produced fewer than 8 usable candidates');
return {json:{pool,shortlist:pool.slice(0,8)}};"""},
        })
    if COMMISSION_NODE not in names:
        c = copy.deepcopy(gen)
        c["id"] = "44b8a598-b27f-4fe1-a760-dd6eb781ccda"
        c["name"] = COMMISSION_NODE
        c["position"] = [2480, 140]
        c["parameters"]["jsonBody"] = r'''={{ JSON.stringify({ model: "claude-sonnet-5", max_tokens: 6000, thinking: { type: "adaptive" }, output_config: { effort: "high" }, messages: [{ role: "user", content: "You are commissioning ONE production-worthy YouTube Short from an already harsh top-8 shortlist. Judge the underlying viewing experience, not clever wording.\n\nSHORTLIST: " + JSON.stringify($json.shortlist) + "\n\nDeep-score each 0-100 on concept_strength, evidence_strength, first_frame_strength, payoff_strength, shareability, novelty, production_feasibility, naturalness. Overall may not exceed the weakest of concept/evidence/first-frame/payoff/shareability by more than 5. 80 is merely good; 90 is rare. Prefer intrinsically visual, defensible concepts and protect archetype variety. Reject interchangeable trivia.\n\nReturn ONLY JSON with candidates sorted best-first. Preserve topic, archetype, research_query, first_frame_concept, share_reason. Add evidence_score, visual_score, share_score, concept_score, payoff_score, novelty_score, execution_score, reason, score." }] }) }}'''
        c["parameters"].setdefault("options", {})["timeout"] = 90000
        w["nodes"].append(c)

    con = w.setdefault("connections", {})
    con["Claude: Generate Topic"] = {"main": [[{"node": POOL_NODE, "type": "main", "index": 0}]]}
    con[POOL_NODE] = {"main": [[{"node": COMMISSION_NODE, "type": "main", "index": 0}]]}
    con[COMMISSION_NODE] = {"main": [[{"node": "Extract Generated Topic", "type": "main", "index": 0}]]}

    ex = node_by_name(w, "Extract Generated Topic")
    code = ex["parameters"]["jsCode"]
    old_map = ".map(c => ({ topic: String(c.topic).trim(), research_query: String(c.research_query || c.topic).trim(), first_frame_concept: String(c.first_frame_concept || ''), share_reason: String(c.share_reason || ''), evidence_score: Number(c.evidence_score) || 0, visual_score: Number(c.visual_score) || 0, share_score: Number(c.share_score) || 0, reason: String(c.reason || ''), score: Number(c.score) || 0 }))"
    new_map = ".map(c => ({ topic: String(c.topic).trim(), archetype: String(c.archetype || 'looks_fake_but_real').trim(), research_query: String(c.research_query || c.topic).trim(), first_frame_concept: String(c.first_frame_concept || ''), share_reason: String(c.share_reason || ''), evidence_score: Number(c.evidence_score) || 0, visual_score: Number(c.visual_score) || 0, share_score: Number(c.share_score) || 0, concept_score: Number(c.concept_score) || 0, payoff_score: Number(c.payoff_score) || 0, novelty_score: Number(c.novelty_score) || 0, execution_score: Number(c.execution_score) || 0, reason: String(c.reason || ''), score: Number(c.score) || 0 }))"
    code = replace_once(code, old_map, new_map, "topic commission parser")
    old_ret = "return { json: { topic: picked.topic, score: picked.score, research_query: picked.research_query || picked.topic, first_frame_concept: picked.first_frame_concept || '', share_reason: picked.share_reason || '', evidence_score: picked.evidence_score || 0, visual_score: picked.visual_score || 0, share_score: picked.share_score || 0, candidates } };"
    new_ret = "return { json: { topic: picked.topic, archetype: picked.archetype || 'looks_fake_but_real', score: picked.score, research_query: picked.research_query || picked.topic, first_frame_concept: picked.first_frame_concept || '', share_reason: picked.share_reason || '', evidence_score: picked.evidence_score || 0, visual_score: picked.visual_score || 0, share_score: picked.share_score || 0, concept_score: picked.concept_score || 0, payoff_score: picked.payoff_score || 0, novelty_score: picked.novelty_score || 0, execution_score: picked.execution_score || 0, candidates, candidate_pool: $('Parse Topic Pool (V3)').item.json.pool || candidates } };"
    ex["parameters"]["jsCode"] = replace_once(code, old_ret, new_ret, "topic commission return")


def patch_writer_editor(w: dict) -> None:
    voice = voice_bible().replace('"', '\\"')
    writer = node_by_name(w, "Claude: Draft Script (Stage 1)")
    body = writer["parameters"]["jsonBody"]
    if "CHANNEL VOICE BIBLE - CREATIVE_SYSTEM_V3" not in body:
        anchor = "HOOK - the single most important sentence in the video."
        body = replace_once(body, anchor, "CHANNEL VOICE BIBLE - CREATIVE_SYSTEM_V3: " + voice + "\\n\\nSound like this channel, not generic viral narration.\\n\\n" + anchor, "writer voice")
    if "ENGAGEMENT IS OPTIONAL - CREATIVE_SYSTEM_V3" not in body:
        anchor = "COMMENT MECHANIC (critical for engagement):"
        rule = "ENGAGEMENT IS OPTIONAL - CREATIVE_SYSTEM_V3: a comment question and share outro are optional. If either weakens the viewing experience, omit it, set the matching field to null, and do not hide a spoken CTA elsewhere in narration.\\n\\n" + anchor
        body = replace_once(body, anchor, rule, "writer engagement")
    body = body.replace('\\"comment_hook\\": string, \\"outro_line\\": string', '\\"comment_hook\\": string|null, \\"outro_line\\": string|null')
    topic_anchor = 'Topic: \\" + $json.topic + \\"\\nFirst-frame concept from selection:'
    if topic_anchor in body:
        body = body.replace(topic_anchor, 'Topic: \\" + $json.topic + \\"\\nConcept archetype: \\" + ($json.archetype || \'looks_fake_but_real\') + \\"\\nFirst-frame concept from selection:', 1)
    writer["parameters"]["jsonBody"] = body

    editor = node_by_name(w, "Claude: Editorial Rewrite (Stage 2)")
    body = editor["parameters"]["jsonBody"]
    if "ENGAGEMENT OPTIONAL - CREATIVE_SYSTEM_V3" not in body:
        # V2 has already prefixed the draft with its research-evidence block.
        anchor = "External research leads:"
        rules = (
            "20. ENGAGEMENT OPTIONAL - CREATIVE_SYSTEM_V3: keep a comment question or share outro only when it improves the Short. If removing one improves the ending/middle, remove its spoken line and set comment_hook/outro_line to null.\\n\\n"
            "21. CHANNEL VOICE - CREATIVE_SYSTEM_V3: judge the rewrite against this voice bible: " + voice + "\\n\\n" + anchor
        )
        body = replace_once(body, anchor, rules, "editor V3 rules")
    body = body.replace("naturalness, overall. Grade against the best Shorts", "naturalness, distinctiveness, voice_specificity, overall. Grade against the best Shorts")
    editor["parameters"]["jsonBody"] = body


def add_visual_director(w: dict) -> None:
    names = {n.get("name") for n in w.get("nodes", [])}
    editor = node_by_name(w, "Claude: Editorial Rewrite (Stage 2)")
    if EDITOR_PARSE_NODE not in names:
        w["nodes"].append({
            "id": "02939380-89c9-4580-ad8b-280d2402f6f8", "name": EDITOR_PARSE_NODE,
            "type": "n8n-nodes-base.code", "typeVersion": 2, "position": [3460, 180],
            "parameters": {"jsCode": """const response=$input.first().json;if(response.error)throw new Error('Editorial API error: '+JSON.stringify(response.error));let raw=String(response.content?.[0]?.text||'').trim().replace(/^```(?:json)?\\s*/i,'').replace(/```\\s*$/,'');function x(s){const a=s.indexOf('{');if(a<0)return null;let d=0,q=false,e=false;for(let i=a;i<s.length;i++){const c=s[i];if(q){if(e)e=false;else if(c==='\\\\')e=true;else if(c==='\"')q=false;}else if(c==='\"')q=true;else if(c==='{')d++;else if(c==='}'&&--d===0)return s.slice(a,i+1);}return null;}let p;for(const c of [raw,'{'+raw,x(raw),x('{'+raw)]){if(!c)continue;try{p=JSON.parse(c);break;}catch{}}if(!p)throw new Error('Editorial pass returned invalid JSON');return {json:{script:p}};"""},
        })
    if VISUAL_NODE not in names:
        v = copy.deepcopy(editor)
        v["id"] = "f5bc27a1-e53c-4a35-88e4-b89898f9eb5b"
        v["name"] = VISUAL_NODE
        v["position"] = [3620, 180]
        v["parameters"]["jsonBody"] = r'''={{ JSON.stringify({ model: "claude-sonnet-5", max_tokens: 8192, thinking: { type: "adaptive" }, output_config: { effort: "medium" }, messages: [{ role: "user", content: "You are the VISUAL DIRECTOR for a high-end YouTube Shorts channel. Editorial is locked. Do NOT change facts, hook, title, narration, payoff, scene order, or scene count.\n\nSCRIPT: " + JSON.stringify($json.script) + "\n\nChoose one creative_format: documentary_cinematic, comparison_reveal, minimal_proof, archival_history, macro_detail, kinetic_data. Set visual_grammar to that family. Scene 0 must work muted; set first_frame_type to hero_motion, macro_anomaly, face_reaction, scale_comparison, result_first, archive_proof, or kinetic_stat. Assign each content scene visual_role = hero/evidence/detail/comparison/breath/payoff. For each stock scene add 3-4 DISTINCT concrete search_queries (2-5 words) and set stock_search_query to the strongest. Preserve named_subject for exact real entities. Use templates only when the beat is fundamentally a number/comparison/punchy line. Choose caption_mode = karaoke/key_phrases/minimal. Set transition_style=hard_cut. Carry the editor CTA decision through and set engagement_mode=none/comment_only/share_only/comment_and_share; do not invent a CTA. Set open_loop_count honestly (usually 0-2). Set visual_plan_quality 0-100; generic scene 0 or repetitive roles must score below 88. Return ONLY the COMPLETE script JSON with all original fields plus these visual fields." }] }) }}'''
        v["parameters"].setdefault("options", {})["timeout"] = 90000
        w["nodes"].append(v)
    c = w.setdefault("connections", {})
    c["Claude: Editorial Rewrite (Stage 2)"] = {"main": [[{"node": EDITOR_PARSE_NODE, "type": "main", "index": 0}]]}
    c[EDITOR_PARSE_NODE] = {"main": [[{"node": VISUAL_NODE, "type": "main", "index": 0}]]}
    c[VISUAL_NODE] = {"main": [[{"node": "Validate Final Script", "type": "main", "index": 0}]]}


def patch_validator(w: dict) -> None:
    n = node_by_name(w, "Validate Final Script")
    code = n["parameters"]["jsCode"]
    code = code.replace("  naturalness: 84,\n  overall: 87,", "  naturalness: 84,\n  distinctiveness: 84,\n  voice_specificity: 82,\n  overall: 87,")
    code = code.replace(
        "if (!parsed.comment_hook || parsed.comment_hook.length < 8) {\n  errors.push('comment_hook missing or too short');\n}",
        "if (parsed.comment_hook != null && String(parsed.comment_hook).trim() && String(parsed.comment_hook).trim().length < 8) {\n  errors.push('comment_hook, when used, is too short');\n}",
    )
    old = """const outroLine = (parsed.outro_line && String(parsed.outro_line).trim())
  ? String(parsed.outro_line).trim()
  : 'If this got you, send it to someone who needs to see it.';
if (Array.isArray(parsed.scenes) && parsed.scenes.length) {
  const maxIdx = parsed.scenes.reduce((m, s) => Math.max(m, Number(s.scene_index) || 0), -1);
  parsed.scenes.push({
    scene_index: maxIdx + 1,
    point: 'outro',
    narration: outroLine,
    visual_source: 'template',
    template_name: 'kinetic_text',
    template_data: { line: 'Like, Share, Follow', is_outro: true },
  });
}
"""
    new = """const outroLine = (parsed.outro_line && String(parsed.outro_line).trim()) ? String(parsed.outro_line).trim() : '';
const wantsShareOutro = ['share_only', 'comment_and_share'].includes(parsed.engagement_mode);
if (outroLine && wantsShareOutro && Array.isArray(parsed.scenes) && parsed.scenes.length) {
  const maxIdx = parsed.scenes.reduce((m, s) => Math.max(m, Number(s.scene_index) || 0), -1);
  parsed.scenes.push({scene_index:maxIdx+1,point:'outro',narration:outroLine,visual_source:'template',template_name:'kinetic_text',template_data:{line:'Share',is_outro:true}});
}
"""
    code = replace_once(code, old, new, "optional outro")
    if "CREATIVE_SYSTEM_V3 visual commissioning gate" not in code:
        anchor = "// Medical/health exclusion backstop"
        gate = """// CREATIVE_SYSTEM_V3 visual commissioning gate.
const validFormats=['documentary_cinematic','comparison_reveal','minimal_proof','archival_history','macro_detail','kinetic_data'];
const validCaptionModes=['karaoke','key_phrases','minimal'];
const validEngagementModes=['none','comment_only','share_only','comment_and_share'];
if(!validFormats.includes(parsed.creative_format))errors.push('creative_format missing/invalid');
if(!validCaptionModes.includes(parsed.caption_mode))errors.push('caption_mode missing/invalid');
if(!validEngagementModes.includes(parsed.engagement_mode))errors.push('engagement_mode missing/invalid');
if(Number(parsed.visual_plan_quality)<88)errors.push(`visual_plan_quality=${parsed.visual_plan_quality} below publish threshold 88`);
if(!parsed.first_frame_type)errors.push('first_frame_type missing');
if(parsed.engagement_mode==='none'&&(parsed.comment_hook||parsed.outro_line))errors.push('engagement_mode=none but CTA fields populated');
if(parsed.engagement_mode==='comment_only'&&parsed.outro_line)errors.push('comment_only cannot carry a share outro');
if(Array.isArray(parsed.scenes)){parsed.scenes.forEach((s,i)=>{if(s?.template_data?.is_outro)return;if(!s.visual_role)errors.push(`scene ${i} missing visual_role`);if(s.visual_source!=='template'&&(!Array.isArray(s.search_queries)||s.search_queries.filter(Boolean).length<2))errors.push(`scene ${i} needs at least 2 search_queries`);});}

""" + anchor
        code = replace_once(code, anchor, gate, "visual validator")
    n["parameters"]["jsCode"] = code


def patch_broll_and_payload(w: dict) -> None:
    r = node_by_name(w, "Resolve B-roll")
    r["parameters"]["jsonBody"] = r'''={{ JSON.stringify({ query: ($('Split Out Scenes').item.json.stock_search_query || $('Split Out Scenes').item.json.visual_prompt), queries: ($('Split Out Scenes').item.json.search_queries || []), alternate_queries: ($('Split Out Scenes').item.json.search_queries || []).slice(1), subject: ($('Split Out Scenes').item.json.named_subject || ''), description: ($('Split Out Scenes').item.json.visual_prompt || $('Split Out Scenes').item.json.stock_search_query), scene_index: $('Split Out Scenes').item.json.scene_index, first_frame: Number($('Split Out Scenes').item.json.scene_index) === 0, creative_format: ($('Validate Final Script').item.json.creative_format || '') }) }}'''
    tag = node_by_name(w, "Tag B-roll")
    tag["parameters"]["jsCode"] = """const r=$json;const sceneIndex=$('Split Out Scenes').item.json.scene_index;if(!r||r.ok!==true||!r.url)throw new Error('B-roll commissioning rejected scene '+sceneIndex+': '+(r?.reason||'no asset')+' best_score='+(r?.best_score??'n/a')+' threshold='+(r?.threshold??'n/a'));const out={scene_index:sceneIndex,_source:r.source||'broll',_attribution:r.attribution||'',asset_score:r.score??null,asset_relevance:r.relevance??null,asset_scroll_stop:r.scroll_stop??null,asset_mobile_clarity:r.mobile_clarity??null,selected_query:r.selected_query||null};if(r.type==='video')out.video_url=r.url;else out.images=[r.url];return {json:out};"""
    merge = node_by_name(w, "Merge By scene_index (not position)")
    code = merge["parameters"]["jsCode"]
    code = code.replace("    template_data: v.template_data,\n    audio: match.audio,", "    template_data: v.template_data,\n    asset_score: v.asset_score,\n    asset_relevance: v.asset_relevance,\n    asset_scroll_stop: v.asset_scroll_stop,\n    asset_mobile_clarity: v.asset_mobile_clarity,\n    asset_source: v._source,\n    selected_query: v.selected_query,\n    audio: match.audio,")
    code = code.replace("    caption_style: $('Validate Final Script').item.json.caption_style,\n    data: merged", "    caption_style: $('Validate Final Script').item.json.caption_style,\n    caption_mode: $('Validate Final Script').item.json.caption_mode,\n    creative_format: $('Validate Final Script').item.json.creative_format,\n    visual_grammar: $('Validate Final Script').item.json.visual_grammar,\n    engagement_mode: $('Validate Final Script').item.json.engagement_mode,\n    outro_line: $('Validate Final Script').item.json.outro_line || null,\n    data: merged")
    merge["parameters"]["jsCode"] = code


def patch_performance_log(w: dict) -> None:
    n = node_by_name(w, "Log Published Video")
    n["parameters"]["jsonBody"] = r'''={{ JSON.stringify({ video_id: ($('YouTube: Upload Draft').item.json.uploadId || $('YouTube: Upload Draft').item.json.id), topic: $('Extract Generated Topic').item.json.topic, hook: $('Validate Final Script').item.json.hook, title: $('Validate Final Script').item.json.title, comment_hook: $('Validate Final Script').item.json.comment_hook || null, caption_style: $('Validate Final Script').item.json.caption_style, trigger: $('Validate Final Script').item.json.trigger, creative_dna: { concept_archetype: $('Extract Generated Topic').item.json.archetype || null, creative_format: $('Validate Final Script').item.json.creative_format || null, visual_grammar: $('Validate Final Script').item.json.visual_grammar || null, first_frame_type: $('Validate Final Script').item.json.first_frame_type || null, first_frame_source: (($('Validate Final Script').item.json.scenes || [])[0]?.visual_source || null), first_frame_score: $('Validate Final Script').item.json.quality?.first_frame_strength ?? null, scene_count: ($('Validate Final Script').item.json.scenes || []).filter(s => !s?.template_data?.is_outro).length, word_count: String($('Validate Final Script').item.json.full_script || '').trim().split(/\s+/).filter(Boolean).length, payoff_position_pct: (() => { const ss=($('Validate Final Script').item.json.scenes || []).filter(s => !s?.template_data?.is_outro); const ris=Number($('Validate Final Script').item.json.payoff?.resolved_in_scene); const idx=ss.findIndex(s => Number(s.scene_index) === ris); return idx >= 0 && ss.length ? Number(((idx + 1) / ss.length).toFixed(3)) : null; })(), open_loop_count: $('Validate Final Script').item.json.open_loop_count ?? null, template_count: ($('Validate Final Script').item.json.scenes || []).filter(s => !s?.template_data?.is_outro && s.visual_source === 'template').length, real_video_count: ($('Validate Final Script').item.json.scenes || []).filter(s => !s?.template_data?.is_outro && s.visual_source !== 'template' && s.visual_type === 'real').length, still_image_count: ($('Validate Final Script').item.json.scenes || []).filter(s => !s?.template_data?.is_outro && s.visual_source !== 'template' && s.visual_type !== 'real').length, caption_mode: $('Validate Final Script').item.json.caption_mode || null, transition_style: $('Validate Final Script').item.json.transition_style || 'hard_cut', engagement_mode: $('Validate Final Script').item.json.engagement_mode || null, comment_hook_present: Boolean($('Validate Final Script').item.json.comment_hook), outro_present: Boolean($('Validate Final Script').item.json.outro_line), asset_quality_min: null, asset_quality_avg: null } }) }}'''


def upgrade(w: dict) -> dict:
    patch_topic_search(w)
    add_topic_commissioning(w)
    patch_writer_editor(w)
    add_visual_director(w)
    patch_validator(w)
    patch_broll_and_payload(w)
    patch_performance_log(w)
    return w


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit("usage: upgrade-creative-system-v3.py INPUT_V2_WORKFLOW OUTPUT_V3_WORKFLOW")
    src, dst = map(Path, sys.argv[1:])
    w = json.loads(src.read_text())
    dst.write_text(json.dumps(upgrade(w), indent=2) + "\n")
    print(f"creative system V3 workflow written to {dst}")


if __name__ == "__main__":
    main()
