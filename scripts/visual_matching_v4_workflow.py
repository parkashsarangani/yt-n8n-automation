#!/usr/bin/env python3
"""Apply VISUAL_MATCHING_V4 contracts to the generated n8n workflow.

This patch is intentionally idempotent and compatible with both the early
creative-system Visual Director and the final QUALITY_ALIGNMENT Visual Director.
The final parser transform reapplies it after quality alignment, so no late
prompt replacement can silently remove the semantic visual contract.
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

MARKER = "VISUAL_MATCHING_V4"
CONTRACT_GATE = "VISUAL_MATCHING_V4 contract gate"
LEGACY_AI_GATE_REMOVED = "V4_LEGACY_AI_VISUAL_GATE_REMOVED"
DETERMINISTIC_TEMPLATE_NORMALIZER = "V4_DETERMINISTIC_TEMPLATE_NORMALIZER"
LEGACY_TEMPLATE_RULE = "For template_explainer set visual_source=template and template_name ONLY stat_reveal, comparison, or kinetic_text with complete template_data."
V4_TEMPLATE_RULE = (
    "For template_explainer set visual_source=template and make template_name match visual_proof_mode exactly: "
    "comparison=>comparison, number_visualization=>stat_reveal, kinetic_text=>kinetic_text, diagram=>diagram, timeline=>timeline, map=>map; "
    "always provide the complete template_data required by that renderer."
)
OBSOLETE_AI_VISUAL_ERRORS = (
    "visual_prompt too short/missing",
    "missing negative_prompt",
    "visual_prompt likely requires readable text/numbers in the AI-generated video",
    "negative_prompt does not explicitly exclude readable text/numbers",
)


def node(workflow: dict, name: str) -> dict:
    for n in workflow.get("nodes", []):
        if n.get("name") == name:
            return n
    raise KeyError(name)


V4_INSTRUCTION = (
    "VISUAL_MATCHING_V4 - EXACT SCRIPT-TO-PIXEL CONTRACT. Before choosing a source, define the exact visual proof for EVERY content scene. "
    "Add visual_claim (one literal sentence describing what the pixels must communicate), global_subject (the overall selected topic/entity active throughout the Short), "
    "required_entities (array of concrete visible entities), required_actions (array of visible actions/states), required_relationships (array of visible spatial/scale/comparison relationships), "
    "forbidden_visuals (array including the tempting generic filler that would be topically related but narratively wrong), acceptable_visuals (0-3 valid alternate depictions), and visual_proof_mode. "
    "visual_proof_mode must be exactly one of literal_video, literal_image, annotated_real, comparison, number_visualization, kinetic_text, diagram, timeline, map. "
    "visual_prompt and negative_prompt are legacy AI-generation fields and are NOT required by V4; do not spend repair attempts recreating them. "
    "Do NOT collapse a scene into its broad named subject: if narration says an octopus squeezes through a narrow gap, visual_claim must require the squeezing-through-gap action, not merely 'octopus'. "
    "Resolve pronouns and vague local wording using OVERALL SELECTED TOPIC / MACRO CONTEXT. "
    "REPRESENTATION ROUTER: comparison=>visual_source template + template_name comparison; number_visualization=>template + stat_reveal; kinetic_text=>template + kinetic_text; "
    "map=>template + map with template_data {title,locations:[{label,lat,lon}],connections:[{from,to,label?}]}; timeline=>template + timeline with template_data {title,events:[{date,label,detail?}]}; "
    "diagram=>template + diagram with template_data {title,nodes:[{id,label,detail?}],edges:[{from,to,label?}]}. Use map only when the script/context supports trustworthy coordinates; otherwise use annotated_real/archive proof. "
    "annotated_real MUST remain a real-media retrieval scene, not a template at planning time: the resolver will select the exact real image, visually locate callout boxes on those pixels, then convert it into the annotated_real Remotion composition. "
    "If a fact is fundamentally abstract and stock cannot literally prove it, choose annotated_real or a deterministic template instead of generic symbolic stock. literal_video is preferred whenever an observable action is required. "
    "For real/archive scenes, search_queries must separately cover the subject, action, and relationship where applicable. A beautiful broad-topic shot that omits the narrated action/relationship is wrong."
)


def _insert_once(body: str, anchor: str, text: str, *, after: bool = True) -> str:
    if text in body:
        return body
    if anchor not in body:
        return body
    if after:
        return body.replace(anchor, anchor + " " + text, 1)
    return body.replace(anchor, text + " " + anchor, 1)


def _strip_obsolete_ai_visual_gates(code: str) -> str:
    """Remove inherited AI-image-era validator errors that are invalid under V4."""
    lines = code.splitlines()
    cleaned = [line for line in lines if not any(token in line for token in OBSOLETE_AI_VISUAL_ERRORS)]
    code = "\n".join(cleaned)
    if LEGACY_AI_GATE_REMOVED not in code:
        marker = (
            f"// {LEGACY_AI_GATE_REMOVED}: visual_prompt/negative_prompt are legacy AI-generation fields; "
            "V4 validates visual_claim + semantic proof fields instead."
        )
        anchor = "const errors = [];"
        code = code.replace(anchor, anchor + "\n" + marker, 1) if anchor in code else marker + "\n" + code
    return code


def _patch_legacy_v2_template_normalizer(code: str) -> str:
    """Make the older V2 runtime normalizer preserve all V4 deterministic renderers.

    The V2 normalizer used to recognize only stat_reveal/comparison/kinetic_text
    and silently rewrite map/timeline/diagram to kinetic_text before the V4 gate
    ran. V4 proof mode is authoritative; deterministic routing is derivable and
    must not consume a model repair attempt. Invalid structured data is preserved
    under the correct renderer name so the V4 validator can report the real
    missing-data error instead of a fake template-name mismatch.
    """
    if "VISUAL_SOURCE_ROUTER_V2" not in code:
        return code
    if DETERMINISTIC_TEMPLATE_NORMALIZER in code:
        return code

    old_helper = """const _vrValidTemplate=(obj,s)=>{
  if(!obj||typeof obj!=='object')return _vrKinetic(s);
  const name=String(obj.template_name||''); const d=obj.template_data&&typeof obj.template_data==='object'?obj.template_data:{};
  if(name==='stat_reveal'&&_vrClean(d.statValue,40)&&_vrClean(d.label,72))return {template_name:name,template_data:d};
  if(name==='comparison'&&_vrClean(d.leftLabel,48)&&_vrClean(d.leftValue,48)&&_vrClean(d.rightLabel,48)&&_vrClean(d.rightValue,48))return {template_name:name,template_data:d};
  if(name==='kinetic_text'&&_vrClean(d.line,120))return {template_name:name,template_data:d};
  return _vrKinetic(s);
};"""
    new_helper = f"""// {DETERMINISTIC_TEMPLATE_NORMALIZER}: V4 proof mode owns deterministic renderer selection.
const _vrProofTemplate={{comparison:'comparison',number_visualization:'stat_reveal',kinetic_text:'kinetic_text',diagram:'diagram',timeline:'timeline',map:'map'}};
const _vrValidTemplate=(obj,s)=>{{
  if(!obj||typeof obj!=='object')return _vrKinetic(s);
  const name=String(obj.template_name||''); const d=obj.template_data&&typeof obj.template_data==='object'?obj.template_data:{{}};
  if(name==='stat_reveal'&&_vrClean(d.statValue,40)&&_vrClean(d.label,72))return {{template_name:name,template_data:d}};
  if(name==='comparison'&&_vrClean(d.leftLabel,48)&&_vrClean(d.leftValue,48)&&_vrClean(d.rightLabel,48)&&_vrClean(d.rightValue,48))return {{template_name:name,template_data:d}};
  if(name==='kinetic_text'&&_vrClean(d.line,120))return {{template_name:name,template_data:d}};
  if(name==='diagram'&&Array.isArray(d.nodes)&&d.nodes.length>=2&&Array.isArray(d.edges))return {{template_name:name,template_data:d}};
  if(name==='timeline'&&Array.isArray(d.events)&&d.events.length>=2)return {{template_name:name,template_data:d}};
  if(name==='map'&&Array.isArray(d.locations)&&d.locations.length>=1)return {{template_name:name,template_data:d}};
  const expected=_vrProofTemplate[String(s&&s.visual_proof_mode||'')];
  if(expected)return {{template_name:expected,template_data:d}};
  return _vrKinetic(s);
}};"""
    if old_helper not in code:
        raise ValueError("V2 template normalizer helper changed; refusing to leave destructive V4 downgrade in place")
    code = code.replace(old_helper, new_helper, 1)

    old_route = """  if(mode==='template_explainer'||s.visual_source==='template'){
    const chosen=_vrValidTemplate({template_name:s.template_name,template_data:s.template_data},s);
    s.visual_mode='template_explainer';s.visual_source='template';s.template_name=chosen.template_name;s.template_data=chosen.template_data;s.visual_type='template';
  }else{s.visual_source='stock';if(s.visual_type==='ai'||!s.visual_type)s.visual_type='real';s.template_fallback=_vrValidTemplate(s.template_fallback,s);}"""
    new_route = """  const proofTemplate=_vrProofTemplate[String(s.visual_proof_mode||'')];
  if(proofTemplate){
    const chosen=_vrValidTemplate({template_name:proofTemplate,template_data:s.template_data},s);
    s.visual_mode='template_explainer';s.visual_source='template';s.template_name=proofTemplate;s.template_data=chosen.template_data;s.visual_type='template';
  }else if(mode==='template_explainer'||s.visual_source==='template'){
    const chosen=_vrValidTemplate({template_name:s.template_name,template_data:s.template_data},s);
    s.visual_mode='template_explainer';s.visual_source='template';s.template_name=chosen.template_name;s.template_data=chosen.template_data;s.visual_type='template';
  }else{s.visual_source='stock';if(s.visual_type==='ai'||!s.visual_type)s.visual_type='real';s.template_fallback=_vrValidTemplate(s.template_fallback,s);}"""
    if old_route not in code:
        raise ValueError("V2 template routing block changed; refusing to leave V4 proof mode non-authoritative")
    return code.replace(old_route, new_route, 1)


def _align_visual_prompt(body: str) -> str:
    """Remove the V2 three-template-only instruction that contradicts V4."""
    return body.replace(LEGACY_TEMPLATE_RULE, V4_TEMPLATE_RULE)


def patch_visual_director(workflow: dict) -> None:
    n = node(workflow, "Claude: Visual Director")
    body = str(n["parameters"]["jsonBody"])
    if MARKER not in body:
        quality_anchor = "PHASE 2 - RETRIEVABLE VISUALS"
        legacy_anchor = "For each stock scene, REQUIRED: add 3-4 DISTINCT concrete search_queries (2-5 words, at least 2 required) and set stock_search_query to the strongest - never leave a stock scene without both."
        if quality_anchor in body:
            body = _insert_once(body, quality_anchor, V4_INSTRUCTION, after=True)
        elif legacy_anchor in body:
            body = _insert_once(body, legacy_anchor, V4_INSTRUCTION, after=True)
        else:
            raise ValueError("Visual Director has neither QUALITY_ALIGNMENT nor creative-system V4 insertion anchor")
    body = _align_visual_prompt(body)

    if "OVERALL SELECTED TOPIC / MACRO CONTEXT" not in body:
        old_quality = 'SCRIPT: " + JSON.stringify($json.draft) + "\\n\\nCOMMISSIONING INTENT:'
        new_quality = 'SCRIPT: " + JSON.stringify($json.draft) + "\\n\\nOVERALL SELECTED TOPIC / MACRO CONTEXT: " + String($(\'Extract Generated Topic\').item.json.topic || \'\') + "\\n\\nCOMMISSIONING INTENT:'
        old_legacy = 'SCRIPT: " + JSON.stringify($json.draft) + "\\n\\nChoose one creative_format:'
        new_legacy = 'SCRIPT: " + JSON.stringify($json.draft) + "\\n\\nOVERALL SELECTED TOPIC / MACRO CONTEXT: " + String($(\'Extract Generated Topic\').item.json.topic || \'\') + "\\n\\nChoose one creative_format:'
        if old_quality in body:
            body = body.replace(old_quality, new_quality, 1)
        elif old_legacy in body:
            body = body.replace(old_legacy, new_legacy, 1)
        else:
            raise ValueError("Visual Director macro-context SCRIPT anchor missing")
    n["parameters"]["jsonBody"] = body

    try:
        repair = node(workflow, "Claude: Repair Script")
        repair_body = str(repair["parameters"].get("jsonBody", ""))
        if repair_body and MARKER not in repair_body:
            if "PHASE 2 - RETRIEVABLE VISUALS" in repair_body:
                repair_body = _insert_once(repair_body, "PHASE 2 - RETRIEVABLE VISUALS", V4_INSTRUCTION, after=True)
            elif "PHASE 1 - QUALITY CHECK" in repair_body:
                repair_body = _insert_once(repair_body, "PHASE 1 - QUALITY CHECK", V4_INSTRUCTION, after=False)
        repair["parameters"]["jsonBody"] = _align_visual_prompt(repair_body)
    except KeyError:
        pass


def patch_validator(workflow: dict) -> None:
    n = node(workflow, "Validate Final Script")
    code = _strip_obsolete_ai_visual_gates(str(n["parameters"]["jsCode"]))
    code = _patch_legacy_v2_template_normalizer(code)
    n["parameters"]["jsCode"] = code
    if CONTRACT_GATE in code:
        return
    anchor = "// Medical/health exclusion backstop"
    if anchor not in code:
        anchor = "const errors = [];"
        before = False
    else:
        before = True
    gate = r'''// VISUAL_MATCHING_V4 contract gate.
const proofModes=['literal_video','literal_image','annotated_real','comparison','number_visualization','kinetic_text','diagram','timeline','map'];
const deterministicModes=['comparison','number_visualization','kinetic_text','diagram','timeline','map'];
const expectedTemplate={comparison:'comparison',number_visualization:'stat_reveal',kinetic_text:'kinetic_text',diagram:'diagram',timeline:'timeline',map:'map'};
if(Array.isArray(parsed.scenes)){parsed.scenes.forEach((s,i)=>{
  if(s?.template_data?.is_outro)return;
  if(!s.visual_claim||String(s.visual_claim).trim().length<8)errors.push(`scene ${i} missing visual_claim`);
  if(!Array.isArray(s.required_entities))errors.push(`scene ${i} missing required_entities array`);
  if(!Array.isArray(s.required_actions))errors.push(`scene ${i} missing required_actions array`);
  if(!Array.isArray(s.required_relationships))errors.push(`scene ${i} missing required_relationships array`);
  if(!Array.isArray(s.forbidden_visuals)||s.forbidden_visuals.length<1)errors.push(`scene ${i} missing forbidden_visuals`);
  if(!Array.isArray(s.acceptable_visuals))errors.push(`scene ${i} missing acceptable_visuals array`);
  if(!proofModes.includes(s.visual_proof_mode))errors.push(`scene ${i} invalid visual_proof_mode=${s.visual_proof_mode}`);
  if(deterministicModes.includes(s.visual_proof_mode)){
    if(s.visual_source!=='template')errors.push(`scene ${i} proof mode ${s.visual_proof_mode} must use deterministic template`);
    if(s.template_name!==expectedTemplate[s.visual_proof_mode])errors.push(`scene ${i} proof mode ${s.visual_proof_mode} requires template_name=${expectedTemplate[s.visual_proof_mode]}`);
  }
  if(s.visual_proof_mode==='annotated_real'&&s.visual_source==='template')errors.push(`scene ${i} annotated_real must retrieve a verified real image before template conversion`);
  if(s.visual_proof_mode==='literal_video'&&s.visual_source==='template')errors.push(`scene ${i} literal_video cannot be represented by a template`);
  if(s.visual_source!=='template'&&s.required_actions.length>0&&s.visual_proof_mode==='literal_image')errors.push(`scene ${i} requires visible action but is routed as literal_image`);
  if(s.visual_proof_mode==='map'){
    const locs=s?.template_data?.locations;
    if(!Array.isArray(locs)||locs.length<1)errors.push(`scene ${i} map requires template_data.locations`);
    else locs.forEach((p,j)=>{if(!p?.label||!Number.isFinite(Number(p.lat))||!Number.isFinite(Number(p.lon))||Number(p.lat)<-90||Number(p.lat)>90||Number(p.lon)<-180||Number(p.lon)>180)errors.push(`scene ${i} map location ${j} invalid`);});
  }
  if(s.visual_proof_mode==='timeline'&&(!Array.isArray(s?.template_data?.events)||s.template_data.events.length<2))errors.push(`scene ${i} timeline requires at least two events`);
  if(s.visual_proof_mode==='diagram'){
    if(!Array.isArray(s?.template_data?.nodes)||s.template_data.nodes.length<2)errors.push(`scene ${i} diagram requires at least two nodes`);
    if(!Array.isArray(s?.template_data?.edges))errors.push(`scene ${i} diagram requires edges array`);
  }
});}

'''
    if anchor not in code:
        raise ValueError("validator V4 gate anchor missing")
    if before:
        code = code.replace(anchor, gate + anchor, 1)
    else:
        code = code.replace(anchor, anchor + "\n" + gate, 1)
    n["parameters"]["jsCode"] = code


def contract_expr(prefix: str = "$('Split Out Scenes').item.json") -> str:
    p = prefix
    return (
        f"narration: ({p}.narration || ''), point: ({p}.point || ''), global_subject: ({p}.global_subject || $('Extract Generated Topic').item.json.topic || ''), "
        f"visual_claim: ({p}.visual_claim || {p}.must_show || {p}.visual_prompt || ''), required_entities: ({p}.required_entities || []), required_actions: ({p}.required_actions || []), "
        f"required_relationships: ({p}.required_relationships || []), forbidden_visuals: ({p}.forbidden_visuals || []), acceptable_visuals: ({p}.acceptable_visuals || {p}.acceptable_substitutes || []), "
        f"visual_proof_mode: ({p}.visual_proof_mode || ''), prefer_template: ['comparison','number_visualization','kinetic_text','diagram','timeline','map'].includes({p}.visual_proof_mode)"
    )


def patch_resolver(workflow: dict) -> None:
    r = node(workflow, "Resolve B-roll")
    p = "$('Split Out Scenes').item.json"
    body = (
        "={{ JSON.stringify({ query: (" + p + ".stock_search_query || " + p + ".visual_prompt), queries: (" + p + ".search_queries || []), "
        "alternate_queries: (" + p + ".search_queries || []).slice(1), subject: (" + p + ".named_subject || ''), description: (" + p + ".visual_prompt || " + p + ".must_show || " + p + ".stock_search_query), "
        "scene_index: " + p + ".scene_index, first_frame: Number(" + p + ".scene_index) === 0, creative_format: ($('Validate Final Script').item.json.creative_format || ''), "
        + contract_expr(p) + ", run_id: String($execution.id || '') }) }}"
    )
    r["parameters"]["jsonBody"] = body
    r["parameters"].setdefault("options", {})["timeout"] = 180000

    tag = node(workflow, "Tag B-roll")
    tag["parameters"]["jsCode"] = r'''const r=$json;const s=$('Split Out Scenes').item.json;const sceneIndex=s.scene_index;
if(!r||r.ok!==true||!r.url)throw new Error('B-roll commissioning rejected scene '+sceneIndex+': '+(r?.reason||'no asset')+' best_score='+(r?.best_score??'n/a')+' threshold='+(r?.threshold??'n/a')+' proof_mode='+(r?.recommended_visual_proof_mode||s.visual_proof_mode||'n/a'));
const out={scene_index:sceneIndex,point:s.point,narration:s.narration,visual_prompt:s.visual_prompt,named_subject:s.named_subject||'',visual_claim:s.visual_claim||s.must_show||s.visual_prompt||'',global_subject:s.global_subject||$('Extract Generated Topic').item.json.topic||'',required_entities:s.required_entities||[],required_actions:s.required_actions||[],required_relationships:s.required_relationships||[],forbidden_visuals:s.forbidden_visuals||[],acceptable_visuals:s.acceptable_visuals||s.acceptable_substitutes||[],visual_proof_mode:s.visual_proof_mode||r.recommended_visual_proof_mode||'',_source:r.source||'broll',_attribution:r.attribution||'',asset_score:r.score??null,asset_semantic_match:r.semantic_match??null,asset_entity_match:r.entity_match??null,asset_action_match:r.action_match??null,asset_relationship_match:r.relationship_match??null,asset_local_similarity:r.local_similarity??null,asset_frame_similarity:r.frame_similarity??null,frame_similarity:r.frame_similarity??null,frame_sampling_status:r.frame_sampling_status||null,asset_scroll_stop:r.scroll_stop??null,asset_mobile_clarity:r.mobile_clarity??null,selected_query:r.selected_query||null,actual_video_verified:r.actual_video_verified===true,in_point_sec:r.in_point_sec??null,out_point_sec:r.out_point_sec??null,verified_frame_indices:r.verified_frame_indices||null,annotation_plan:r.annotation_plan||null,library_hit:r.library_hit===true};
if(out.visual_proof_mode==='annotated_real'){
  if(r.type!=='image'||!Array.isArray(r.annotation_plan)||r.annotation_plan.length<1)throw new Error('annotated_real scene '+sceneIndex+' lacks a verified image/callout plan');
  out.visual_source='template';out.template_name='annotated_real';out.template_data={imageUrl:r.url,imageWidth:r.width||1080,imageHeight:r.height||1920,title:s?.template_data?.title||s.visual_claim||s.point||'',annotations:r.annotation_plan};
}else if(r.type==='video')out.video_url=r.url;else out.images=[r.url];return {json:out};'''

    template = node(workflow, "Tag Template Video")
    template["parameters"]["jsCode"] = r'''const s=$('Split Out Scenes').item.json;return {json:{scene_index:s.scene_index,point:s.point,narration:s.narration,visual_source:'template',template_name:s.template_name,template_data:s.template_data,visual_prompt:s.visual_prompt||'',named_subject:s.named_subject||'',visual_claim:s.visual_claim||s.must_show||s.point||s.narration||'',global_subject:s.global_subject||$('Extract Generated Topic').item.json.topic||'',required_entities:s.required_entities||[],required_actions:s.required_actions||[],required_relationships:s.required_relationships||[],forbidden_visuals:s.forbidden_visuals||[],acceptable_visuals:s.acceptable_visuals||s.acceptable_substitutes||[],visual_proof_mode:s.visual_proof_mode||''}};'''


def patch_merge(workflow: dict) -> None:
    n = node(workflow, "Merge By scene_index (not position)")
    code = str(n["parameters"]["jsCode"])
    if "asset_semantic_match: v.asset_semantic_match" in code:
        return
    common = "point: v.point, narration: v.narration, visual_prompt: v.visual_prompt, named_subject: v.named_subject, visual_claim: v.visual_claim, global_subject: v.global_subject, required_entities: v.required_entities, required_actions: v.required_actions, required_relationships: v.required_relationships, forbidden_visuals: v.forbidden_visuals, acceptable_visuals: v.acceptable_visuals, visual_proof_mode: v.visual_proof_mode, asset_semantic_match: v.asset_semantic_match, asset_entity_match: v.asset_entity_match, asset_action_match: v.asset_action_match, asset_relationship_match: v.asset_relationship_match, asset_local_similarity: v.asset_local_similarity, asset_frame_similarity: v.asset_frame_similarity, actual_video_verified: v.actual_video_verified, in_point_sec: v.in_point_sec, out_point_sec: v.out_point_sec, verified_frame_indices: v.verified_frame_indices, annotation_plan: v.annotation_plan, library_hit: v.library_hit,"
    stock_extra = "visual_source: v.visual_source, template_name: v.template_name, template_data: v.template_data, " + common
    anchors = [
        ("    selected_query: v.selected_query,\n    audio: match.audio,", "    selected_query: v.selected_query,\n    " + stock_extra + "\n    audio: match.audio,"),
        ("    template_data: v.template_data,\n    audio: match.audio,", "    template_data: v.template_data,\n    " + common + "\n    audio: match.audio,"),
    ]
    for old, new in anchors:
        if old in code:
            n["parameters"]["jsCode"] = code.replace(old, new, 1)
            return
    raise ValueError("merge visual metadata anchor missing")


def upgrade(workflow: dict) -> dict:
    patch_visual_director(workflow)
    patch_validator(workflow)
    patch_resolver(workflow)
    patch_merge(workflow)
    workflow.setdefault("meta", {})["visual_matching_version"] = "4"
    return workflow


def assert_applied(workflow: dict) -> None:
    if workflow.get("meta", {}).get("visual_matching_version") != "4":
        raise RuntimeError("V4 workflow marker missing")
    names = {n.get("name"): n for n in workflow.get("nodes", [])}
    visual = str(names["Claude: Visual Director"]["parameters"]["jsonBody"])
    for marker in [MARKER, "visual_claim", "required_entities", "required_actions", "required_relationships", "forbidden_visuals", "visual_proof_mode", "OVERALL SELECTED TOPIC / MACRO CONTEXT", "map=>template + map", "annotated_real"]:
        if marker not in visual:
            raise RuntimeError(f"V4 Visual Director contract missing {marker}")
    if LEGACY_TEMPLATE_RULE in visual:
        raise RuntimeError("V4 Visual Director still limits template_explainer to three legacy renderers")
    validate = str(names["Validate Final Script"]["parameters"]["jsCode"])
    for marker in [CONTRACT_GATE, LEGACY_AI_GATE_REMOVED, "deterministicModes", "template_data.locations", "timeline requires at least two events", "diagram requires at least two nodes"]:
        if marker not in validate:
            raise RuntimeError(f"V4 validator gate missing {marker}")
    if "VISUAL_SOURCE_ROUTER_V2" in validate and DETERMINISTIC_TEMPLATE_NORMALIZER not in validate:
        raise RuntimeError("V2 runtime normalizer can still downgrade V4 deterministic templates")
    for obsolete in OBSOLETE_AI_VISUAL_ERRORS:
        if obsolete in validate:
            raise RuntimeError(f"V4 validator still contains obsolete AI-generation requirement: {obsolete}")
    resolver = str(names["Resolve B-roll"]["parameters"]["jsonBody"])
    for marker in ["visual_claim", "required_entities", "required_actions", "required_relationships", "forbidden_visuals", "visual_proof_mode", "run_id", "$execution.id"]:
        if marker not in resolver:
            raise RuntimeError(f"V4 resolver payload missing {marker}")
    tag = str(names["Tag B-roll"]["parameters"]["jsCode"])
    for marker in ["annotated_real", "annotation_plan", "verified_frame_indices", "template_name='annotated_real'"]:
        if marker not in tag:
            raise RuntimeError(f"V4 B-roll tag missing {marker}")


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit("usage: visual_matching_v4_workflow.py INPUT OUTPUT")
    src, dst = map(Path, sys.argv[1:])
    workflow = json.loads(src.read_text())
    upgraded = upgrade(workflow)
    assert_applied(upgraded)
    dst.write_text(json.dumps(upgraded, indent=2) + "\n")
    print(f"{MARKER} workflow written to {dst}")


if __name__ == "__main__":
    main()
