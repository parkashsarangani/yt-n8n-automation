#!/usr/bin/env python3
from __future__ import annotations
MARKER="RETRIEVAL_TELEMETRY_V1"
def node_by_name(workflow,name):
    for node in workflow.get("nodes",[]):
        if node.get("name")==name:return node
    raise RuntimeError(f"required workflow node missing: {name}")
TAG_BROLL=r"""// RETRIEVAL_TELEMETRY_V1
const r=$json;const scene=$('Split Out Scenes').item.json;const sceneIndex=scene.scene_index;
if(!r||r.ok!==true)throw new Error('B-roll commissioning rejected scene '+sceneIndex+': '+(r?.reason||r?.fallback_reason||'no asset')+' best_score='+(r?.best_score??r?.score??'n/a')+' threshold='+(r?.threshold??'n/a'));
const retrieval={scene_index:sceneIndex,visual_mode:r.visual_mode||scene.visual_mode||null,must_show:scene.must_show||null,requested_queries:Array.isArray(scene.search_queries)?scene.search_queries.slice(0,6):[],source_priority:Array.isArray(scene.source_priority)?scene.source_priority.slice(0,8):[],queries_tried:Array.isArray(r.queries_tried)?r.queries_tried.slice(0,8):[],candidate_count:r.candidate_count??null,candidate_source_counts:r.candidate_source_counts||{},candidate_type_counts:r.candidate_type_counts||{},scored_count:r.scored_count??null,vision_calls:r.vision_calls??null,cache_hits:r.cache_hits??null,search_rounds:r.search_rounds??null,selected_query:r.selected_query||null,selected_source:r.source||((r.type==='template'||r.visual_source==='template')?'template':null),score:r.score??null,relevance:r.relevance??null,local_similarity:r.local_similarity??null,top_local_similarity:r.top_local_similarity??null,threshold:r.threshold??null,degraded:r.degraded===true,quality_gate_passed:r.quality_gate_passed!==false,fallback_reason:r.fallback_reason||null,intentional_template:false};
const out={scene_index:sceneIndex,_source:r.source||'broll',_attribution:r.attribution||'',asset_score:r.score??null,asset_relevance:r.relevance??null,asset_scroll_stop:r.scroll_stop??null,asset_mobile_clarity:r.mobile_clarity??null,asset_local_similarity:r.local_similarity??null,asset_degraded:r.degraded===true,quality_gate_passed:r.quality_gate_passed!==false,fallback_reason:r.fallback_reason||null,selected_query:r.selected_query||null,visual_mode:r.visual_mode||scene.visual_mode||null,retrieval};
if(r.type==='template'||r.visual_source==='template'){out.visual_source='template';out.template_name=r.template_name||'kinetic_text';out.template_data=r.template_data||{line:String(scene.must_show||scene.point||'Key fact').slice(0,72)};return {json:out};}
if(!r.url)throw new Error('B-roll commissioning returned ok without media URL for scene '+sceneIndex);if(r.type==='video')out.video_url=r.url;else out.images=[r.url];return {json:out};"""
TAG_TEMPLATE=r"""// RETRIEVAL_TELEMETRY_V1
const scene=$('Split Out Scenes').item.json;return {json:{scene_index:scene.scene_index,visual_source:'template',template_name:scene.template_name,template_data:scene.template_data,retrieval:{scene_index:scene.scene_index,visual_mode:scene.visual_mode||'template_explainer',must_show:scene.must_show||scene.point||null,requested_queries:[],source_priority:[],queries_tried:[],candidate_count:0,candidate_source_counts:{},candidate_type_counts:{},scored_count:0,vision_calls:0,cache_hits:0,search_rounds:0,selected_query:null,selected_source:'template',score:null,relevance:null,local_similarity:null,top_local_similarity:null,threshold:null,degraded:false,quality_gate_passed:true,fallback_reason:null,intentional_template:true}}};"""
def apply(workflow):
    node_by_name(workflow,"Tag B-roll")["parameters"]["jsCode"]=TAG_BROLL
    node_by_name(workflow,"Tag Template Video")["parameters"]["jsCode"]=TAG_TEMPLATE
    merge=node_by_name(workflow,"Merge By scene_index (not position)");code=str(merge["parameters"]["jsCode"])
    if "retrieval: v.retrieval" not in code:
        anchor="    template_data: v.template_data,\n    asset_score: v.asset_score,";replacement="    template_data: v.template_data,\n    retrieval: v.retrieval || null,\n    asset_score: v.asset_score,"
        if anchor not in code:raise RuntimeError("merge per-scene telemetry anchor missing")
        code=code.replace(anchor,replacement,1)
    if "const retrieval_telemetry" not in code:
        anchor="const asset_quality_avg = assetScores.length ? Number((assetScores.reduce((s, x) => s + x, 0) / assetScores.length).toFixed(2)) : null;\n"
        if anchor not in code:raise RuntimeError("merge aggregate telemetry anchor missing")
        code=code.replace(anchor,anchor+"const retrieval_telemetry = merged.filter((v) => !v?.template_data?.is_outro).map((v) => v.retrieval || {scene_index:v.scene_index,selected_source:v.asset_source||v.visual_source||null});\n",1)
        anchor2="    asset_quality_avg,\n    data: merged";replacement2="    asset_quality_avg,\n    retrieval_telemetry,\n    data: merged"
        if anchor2 not in code:raise RuntimeError("merge return telemetry anchor missing")
        code=code.replace(anchor2,replacement2,1)
    merge["parameters"]["jsCode"]=code
    log=node_by_name(workflow,"Log Published Video");body=str(log["parameters"]["jsonBody"])
    if "retrieval_telemetry:" not in body:
        anchor="asset_quality_avg: ($('Merge By scene_index (not position)').item.json.asset_quality_avg ?? null) } }) }}";replacement="asset_quality_avg: ($('Merge By scene_index (not position)').item.json.asset_quality_avg ?? null) }, retrieval_telemetry: ($('Merge By scene_index (not position)').item.json.retrieval_telemetry || []) }) }}"
        if anchor not in body:raise RuntimeError("performance-log retrieval telemetry anchor missing")
        body=body.replace(anchor,replacement,1)
    log["parameters"]["jsonBody"]=body;return workflow
def assert_applied(workflow):
    tag=str(node_by_name(workflow,"Tag B-roll")["parameters"]["jsCode"]);template=str(node_by_name(workflow,"Tag Template Video")["parameters"]["jsCode"]);merge=str(node_by_name(workflow,"Merge By scene_index (not position)")["parameters"]["jsCode"]);log=str(node_by_name(workflow,"Log Published Video")["parameters"]["jsonBody"])
    if MARKER not in tag or MARKER not in template:raise RuntimeError("retrieval telemetry markers missing")
    for marker in ["candidate_source_counts","candidate_type_counts","top_local_similarity","requested_queries","queries_tried"]:
        if marker not in tag:raise RuntimeError(f"Tag B-roll missing retrieval field: {marker}")
    if "retrieval_telemetry" not in merge or "retrieval: v.retrieval" not in merge:raise RuntimeError("merge payload does not preserve retrieval telemetry")
    if "retrieval_telemetry:" not in log:raise RuntimeError("published-video log does not send retrieval telemetry")
