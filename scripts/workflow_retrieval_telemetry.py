#!/usr/bin/env python3
"""Persist compact per-scene retrieval traces without changing selection behavior.

V4 extends the original observational trace with semantic contract, grounded
annotations, sampled-frame verification fields, and paid-vision budget context.
Legacy keys remain so existing analytics and later transforms continue to work.
"""
from __future__ import annotations

MARKER = "RETRIEVAL_TELEMETRY_V1"
V4_MARKER = "VISUAL_MATCHING_V4_TELEMETRY"
BUDGET_TOPOLOGY_MARKER = "V4_RETRIEVAL_SCENE_TOPOLOGY"


def node_by_name(workflow: dict, name: str) -> dict:
    for node in workflow.get("nodes", []):
        if node.get("name") == name:
            return node
    raise RuntimeError(f"required workflow node missing: {name}")


TAG_BROLL = r"""// VISUAL_RETRIEVAL_TELEMETRY_V2
// VISUAL_MATCHING_V4_TELEMETRY
// RETRIEVAL_TELEMETRY_V1: observational trace only; selection was already fail-closed in resolver.
const r=$json;const scene=$('Split Out Scenes').item.json;const sceneIndex=scene.scene_index;
if(!r||r.ok!==true){const failures=Array.isArray(r?.failure_reasons)&&r.failure_reasons.length?r.failure_reasons.join(','):'n/a';throw new Error('B-roll commissioning rejected scene '+sceneIndex+': '+(r?.reason||r?.fallback_reason||'no asset')+' best_score='+(r?.best_score??r?.score??'n/a')+' threshold='+(r?.threshold??'n/a')+' scene_calls='+(r?.scene_used??r?.vision_calls??'n/a')+'/'+(r?.scene_limit??r?.vision_call_limit??'n/a')+' run_used='+(r?.run_used??r?.run_vision_used??'n/a')+' run_remaining='+(r?.run_remaining??r?.run_vision_remaining??'n/a')+' candidates='+(r?.candidate_count??'n/a')+' scored='+(r?.scored_count??'n/a')+' failures='+failures);}
if(!r.url&&r.type!=='template'&&r.visual_source!=='template')throw new Error('B-roll commissioning returned ok without media URL for scene '+sceneIndex);
const retrieval={scene_index:sceneIndex,visual_mode:r.visual_mode||scene.visual_mode||null,must_show:scene.must_show||scene.visual_claim||null,requested_queries:Array.isArray(scene.search_queries)?scene.search_queries.slice(0,6):[],source_priority:Array.isArray(scene.source_priority)?scene.source_priority.slice(0,8):[],queries_tried:Array.isArray(r.queries_tried)?r.queries_tried.slice(0,8):[],candidate_count:r.candidate_count??null,candidate_source_counts:r.candidate_source_counts||{},candidate_type_counts:r.candidate_type_counts||{},scored_count:r.scored_count??null,vision_calls:r.vision_calls??r.scene_used??null,vision_call_limit:r.vision_call_limit??r.scene_limit??null,cache_hits:r.cache_hits??null,search_rounds:r.search_rounds??null,selected_query:r.selected_query||null,selected_source:r.source||((r.type==='template'||r.visual_source==='template')?'template':null),score:r.score??null,relevance:r.relevance??null,semantic_match:r.semantic_match??null,entity_match:r.entity_match??null,action_match:r.action_match??null,relationship_match:r.relationship_match??null,local_similarity:r.local_similarity??null,top_local_similarity:r.top_local_similarity??r.local_similarity??null,threshold:r.threshold??null,run_used:r.run_used??null,run_remaining:r.run_remaining??null,scene_used:r.scene_used??null,scene_limit:r.scene_limit??r.vision_call_limit??null,scene_remaining:r.scene_remaining??null,early_accept:r.early_accept===true,failure_reasons:Array.isArray(r.failure_reasons)?r.failure_reasons.slice(0,6):[],actual_video_verified:r.actual_video_verified===true,in_point_sec:r.in_point_sec??null,out_point_sec:r.out_point_sec??null,verified_frame_indices:Array.isArray(r.verified_frame_indices)?r.verified_frame_indices:[],annotation_count:Array.isArray(r.annotation_plan)?r.annotation_plan.length:0,library_hit:r.library_hit===true,degraded:false,quality_gate_passed:true,fallback_reason:null,intentional_template:false};
const out={scene_index:sceneIndex,point:scene.point,narration:scene.narration,visual_prompt:scene.visual_prompt,named_subject:scene.named_subject||'',visual_claim:scene.visual_claim||scene.must_show||scene.visual_prompt||'',global_subject:scene.global_subject||$('Extract Generated Topic').item.json.topic||'',required_entities:scene.required_entities||[],required_actions:scene.required_actions||[],required_relationships:scene.required_relationships||[],forbidden_visuals:scene.forbidden_visuals||[],acceptable_visuals:scene.acceptable_visuals||scene.acceptable_substitutes||[],visual_proof_mode:scene.visual_proof_mode||r.recommended_visual_proof_mode||'',_source:r.source||'broll',_attribution:r.attribution||'',asset_score:r.score??null,asset_relevance:r.relevance??null,asset_semantic_match:r.semantic_match??null,asset_entity_match:r.entity_match??null,asset_action_match:r.action_match??null,asset_relationship_match:r.relationship_match??null,asset_scroll_stop:r.scroll_stop??null,asset_mobile_clarity:r.mobile_clarity??null,asset_local_similarity:r.local_similarity??null,asset_degraded:false,quality_gate_passed:true,fallback_reason:null,selected_query:r.selected_query||null,visual_mode:r.visual_mode||scene.visual_mode||null,actual_video_verified:r.actual_video_verified===true,in_point_sec:r.in_point_sec??null,out_point_sec:r.out_point_sec??null,verified_frame_indices:Array.isArray(r.verified_frame_indices)?r.verified_frame_indices:[],annotation_plan:Array.isArray(r.annotation_plan)?r.annotation_plan:null,library_hit:r.library_hit===true,retrieval};
if(r.type==='template'||r.visual_source==='template'){out.visual_source='template';out.template_name=r.template_name||scene.template_name||'kinetic_text';out.template_data=r.template_data||scene.template_data||{line:String(scene.must_show||scene.point||'Key fact').slice(0,72)};return {json:out};}
if(out.visual_proof_mode==='annotated_real'){
  if(r.type!=='image'||!Array.isArray(r.annotation_plan)||r.annotation_plan.length<1)throw new Error('annotated_real scene '+sceneIndex+' lacks a verified image/callout plan');
  out.visual_source='template';out.template_name='annotated_real';out.template_data={imageUrl:r.url,imageWidth:r.width||1080,imageHeight:r.height||1920,title:scene?.template_data?.title||scene.visual_claim||scene.point||'',annotations:r.annotation_plan};return {json:out};
}
if(r.type==='video')out.video_url=r.url;else out.images=[r.url];return {json:out};"""

TAG_TEMPLATE = r"""// VISUAL_MATCHING_V4_TELEMETRY
// RETRIEVAL_TELEMETRY_V1: intentional deterministic template route; no media retrieval attempted.
const scene=$('Split Out Scenes').item.json;
return {json:{scene_index:scene.scene_index,point:scene.point,narration:scene.narration,visual_prompt:scene.visual_prompt||'',named_subject:scene.named_subject||'',visual_claim:scene.visual_claim||scene.must_show||scene.point||scene.narration||'',global_subject:scene.global_subject||$('Extract Generated Topic').item.json.topic||'',required_entities:scene.required_entities||[],required_actions:scene.required_actions||[],required_relationships:scene.required_relationships||[],forbidden_visuals:scene.forbidden_visuals||[],acceptable_visuals:scene.acceptable_visuals||scene.acceptable_substitutes||[],visual_proof_mode:scene.visual_proof_mode||'',visual_source:'template',template_name:scene.template_name,template_data:scene.template_data,retrieval:{scene_index:scene.scene_index,visual_mode:scene.visual_mode||'template_explainer',must_show:scene.must_show||scene.visual_claim||scene.point||null,requested_queries:[],source_priority:[],queries_tried:[],candidate_count:0,candidate_source_counts:{},candidate_type_counts:{},scored_count:0,vision_calls:0,vision_call_limit:0,cache_hits:0,search_rounds:0,selected_query:null,selected_source:'template',score:null,relevance:null,semantic_match:null,entity_match:null,action_match:null,relationship_match:null,local_similarity:null,top_local_similarity:null,threshold:null,run_used:null,run_remaining:null,scene_used:0,scene_limit:0,scene_remaining:0,early_accept:false,failure_reasons:[],actual_video_verified:false,in_point_sec:null,out_point_sec:null,verified_frame_indices:[],annotation_count:0,library_hit:false,degraded:false,quality_gate_passed:true,fallback_reason:null,intentional_template:true}}};"""


def apply(workflow: dict) -> dict:
    resolver = node_by_name(workflow, "Resolve B-roll")
    resolver_body = str(resolver["parameters"].get("jsonBody", ""))
    if BUDGET_TOPOLOGY_MARKER not in resolver_body:
        anchor = "run_id: String($execution.id || '')"
        if anchor not in resolver_body:
            raise RuntimeError("Resolve B-roll lost run_id anchor before retrieval topology patch")
        topology = (
            f"/* {BUDGET_TOPOLOGY_MARKER} */ "
            "retrieval_scene_count: (($('Validate Final Script').item.json.scenes || []).filter(s => s && !s?.template_data?.is_outro && s.visual_source !== 'template').length), "
            "retrieval_scene_position: (($('Validate Final Script').item.json.scenes || []).filter(s => s && !s?.template_data?.is_outro && s.visual_source !== 'template').findIndex(s => Number(s.scene_index) === Number($('Split Out Scenes').item.json.scene_index))), "
        )
        resolver["parameters"]["jsonBody"] = resolver_body.replace(anchor, topology + anchor, 1)

    node_by_name(workflow, "Tag B-roll")["parameters"]["jsCode"] = TAG_BROLL
    node_by_name(workflow, "Tag Template Video")["parameters"]["jsCode"] = TAG_TEMPLATE

    merge = node_by_name(workflow, "Merge By scene_index (not position)")
    code = str(merge["parameters"]["jsCode"])
    if "retrieval: v.retrieval" not in code:
        anchors = [
            (
                "    template_data: v.template_data,\n    asset_score: v.asset_score,",
                "    template_data: v.template_data,\n    retrieval: v.retrieval || null,\n    asset_score: v.asset_score,",
            ),
            (
                "    template_data: v.template_data,\n    point: v.point,",
                "    template_data: v.template_data,\n    retrieval: v.retrieval || null,\n    point: v.point,",
            ),
        ]
        for anchor, replacement in anchors:
            if anchor in code:
                code = code.replace(anchor, replacement, 1)
                break
        else:
            raise RuntimeError("merge per-scene telemetry anchor missing")

    if "const retrieval_telemetry" not in code:
        anchors = [
            "const quality_gate_fail_count = merged.filter(v => v.quality_gate_passed === false).length;",
            "const asset_quality_avg = assetScores.length ? Number((assetScores.reduce((s, x) => s + x, 0) / assetScores.length).toFixed(2)) : null;",
        ]
        for anchor in anchors:
            if anchor in code:
                code = code.replace(anchor, anchor + "\nconst retrieval_telemetry = merged.filter((v) => !v?.template_data?.is_outro).map((v) => v.retrieval || {scene_index:v.scene_index,selected_source:v.asset_source||v.visual_source||null});", 1)
                break
        else:
            raise RuntimeError("merge aggregate telemetry anchor missing")

        if "    degraded_scene_indexes,\n    data: merged" in code:
            code = code.replace("    degraded_scene_indexes,\n    data: merged", "    degraded_scene_indexes,\n    retrieval_telemetry,\n    data: merged", 1)
        elif "    asset_quality_avg,\n    data: merged" in code:
            code = code.replace("    asset_quality_avg,\n    data: merged", "    asset_quality_avg,\n    retrieval_telemetry,\n    data: merged", 1)
        else:
            raise RuntimeError("merge return telemetry anchor missing")
    merge["parameters"]["jsCode"] = code

    log = node_by_name(workflow, "Log Published Video")
    body = str(log["parameters"]["jsonBody"])
    if "retrieval_telemetry:" not in body:
        guarded_anchor = "degraded_scene_indexes: ($('Merge By scene_index (not position)').item.json.degraded_scene_indexes || []) } }) }}"
        guarded_replacement = "degraded_scene_indexes: ($('Merge By scene_index (not position)').item.json.degraded_scene_indexes || []) }, retrieval_telemetry: ($('Merge By scene_index (not position)').item.json.retrieval_telemetry || []) }) }}"
        legacy_anchor = "asset_quality_avg: ($('Merge By scene_index (not position)').item.json.asset_quality_avg ?? null) } }) }}"
        legacy_replacement = "asset_quality_avg: ($('Merge By scene_index (not position)').item.json.asset_quality_avg ?? null) }, retrieval_telemetry: ($('Merge By scene_index (not position)').item.json.retrieval_telemetry || []) }) }}"
        if guarded_anchor in body:
            body = body.replace(guarded_anchor, guarded_replacement, 1)
        elif legacy_anchor in body:
            body = body.replace(legacy_anchor, legacy_replacement, 1)
        else:
            raise RuntimeError("performance-log retrieval telemetry anchor missing")
    log["parameters"]["jsonBody"] = body
    return workflow


def assert_applied(workflow: dict) -> None:
    resolver = str(node_by_name(workflow, "Resolve B-roll")["parameters"]["jsonBody"])
    tag = str(node_by_name(workflow, "Tag B-roll")["parameters"]["jsCode"])
    template = str(node_by_name(workflow, "Tag Template Video")["parameters"]["jsCode"])
    merge = str(node_by_name(workflow, "Merge By scene_index (not position)")["parameters"]["jsCode"])
    log = str(node_by_name(workflow, "Log Published Video")["parameters"]["jsonBody"])
    if BUDGET_TOPOLOGY_MARKER not in resolver or "retrieval_scene_count" not in resolver or "retrieval_scene_position" not in resolver:
        raise RuntimeError("Resolve B-roll does not carry actual retrieval-scene topology for adaptive budgeting")
    if MARKER not in tag or MARKER not in template or V4_MARKER not in tag:
        raise RuntimeError("retrieval telemetry markers missing")
    for marker in ["candidate_source_counts", "candidate_type_counts", "top_local_similarity", "requested_queries", "queries_tried", "semantic_match", "entity_match", "action_match", "relationship_match", "actual_video_verified", "verified_frame_indices", "annotation_plan", "annotated_real", "vision_call_limit", "scene_calls=", "failure_reasons", "early_accept"]:
        if marker not in tag:
            raise RuntimeError(f"Tag B-roll missing retrieval field: {marker}")
    if "retrieval_telemetry" not in merge or "retrieval: v.retrieval" not in merge:
        raise RuntimeError("merge payload does not preserve retrieval telemetry")
    if "retrieval_telemetry:" not in log:
        raise RuntimeError("published-video log does not send retrieval telemetry")
