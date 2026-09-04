#!/usr/bin/env python3
"""Build the exact production workflow + compose artifacts in one deterministic pass.

Historically CI and deploy each reimplemented a long, mutable sequence of string
transforms. That allowed the two paths to drift and made the checked-in source a
poor predictor of what actually ran. This script is now the single production
build entrypoint. Both CI and deploy call it, consume its outputs, and verify the
same manifest.

The older upgrade modules remain as migration stages for now, but ordering lives
in exactly one place and final workflow policy changes are applied structurally
against parsed JSON rather than through another shell/string-patch chain.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

BUILD_VERSION = "5"
INTERNAL_SERVICE_ORIGIN = "http://shorts-compose:4000"
PUBLIC_SERVICE_ORIGIN = "https://shorts.interviewbuddy.cloud"


def run(*args: str, cwd: Path) -> None:
    subprocess.run([sys.executable, *args], cwd=str(cwd), check=True)


def node_by_name(workflow: dict, name: str) -> dict:
    for node in workflow.get("nodes", []):
        if node.get("name") == name:
            return node
    raise KeyError(f"required workflow node not found: {name}")


def internalize_compose_service_urls(workflow: dict) -> None:
    """Keep n8n->compose traffic on the Docker network, never the public proxy."""
    for node in workflow.get("nodes", []):
        params = node.get("parameters", {})
        value = params.get("url")
        if isinstance(value, str) and PUBLIC_SERVICE_ORIGIN in value:
            params["url"] = value.replace(PUBLIC_SERVICE_ORIGIN, INTERNAL_SERVICE_ORIGIN)


def clean_visual_director_annotation_contract(workflow: dict) -> None:
    """Redefine annotated_real as a clean verified still, not a CV overlay task."""
    visual = node_by_name(workflow, "Claude: Visual Director")
    body = str(visual.get("parameters", {}).get("jsonBody", ""))
    legacy = (
        "annotated_real MUST remain a real-media retrieval scene, not a template at planning time: "
        "the resolver will select the exact real image, visually locate callout boxes on those pixels, "
        "then convert it into the annotated_real Remotion composition."
    )
    replacement = (
        "annotated_real MUST remain a real-media retrieval scene, not a template at planning time: "
        "the resolver selects and visually verifies the exact real image, then the renderer presents that verified image cleanly. "
        "Do NOT request callout boxes, labels, coordinates, arrows, diagnostic overlays, or explanatory UI for annotated_real."
    )
    if legacy in body:
        body = body.replace(legacy, replacement, 1)
    body = body.replace(
        "visually locate callout boxes on those pixels, then convert it into the annotated_real Remotion composition",
        "visually verify those pixels, then render the real image cleanly without diagnostic overlays",
    )
    visual["parameters"]["jsonBody"] = body


def clean_tag_broll(workflow: dict) -> None:
    """Consume verified-real images and deterministic fallback templates."""
    tag = node_by_name(workflow, "Tag B-roll")
    tag["parameters"]["jsCode"] = r'''const r=$json;const s=$('Split Out Scenes').item.json;const sceneIndex=s.scene_index;
if(!r||r.ok!==true)throw new Error('B-roll commissioning rejected scene '+sceneIndex+': '+(r?.reason||'no acceptable asset')+' best_score='+(r?.best_score??r?.score??'n/a')+' threshold='+(r?.threshold??'n/a')+' proof_mode='+(r?.recommended_visual_proof_mode||s.visual_proof_mode||'n/a'));
const proofByTemplate={stat_reveal:'number_visualization',comparison:'comparison',kinetic_text:'kinetic_text',map:'map',timeline:'timeline',diagram:'diagram'};
const out={scene_index:sceneIndex,point:s.point,narration:s.narration,visual_prompt:s.visual_prompt,named_subject:s.named_subject||'',visual_claim:s.visual_claim||s.must_show||s.visual_prompt||'',global_subject:s.global_subject||$('Extract Generated Topic').item.json.topic||'',required_entities:s.required_entities||[],required_actions:s.required_actions||[],required_relationships:s.required_relationships||[],forbidden_visuals:s.forbidden_visuals||[],acceptable_visuals:s.acceptable_visuals||s.acceptable_substitutes||[],visual_proof_mode:s.visual_proof_mode||r.recommended_visual_proof_mode||'',_source:r.source||'broll',_attribution:r.attribution||'',asset_score:r.score??null,asset_semantic_match:r.semantic_match??null,asset_entity_match:r.entity_match??null,asset_action_match:r.action_match??null,asset_relationship_match:r.relationship_match??null,asset_local_similarity:r.local_similarity??null,asset_frame_similarity:r.frame_similarity??null,frame_similarity:r.frame_similarity??null,frame_sampling_status:r.frame_sampling_status||null,asset_scroll_stop:r.scroll_stop??null,asset_mobile_clarity:r.mobile_clarity??null,selected_query:r.selected_query||null,actual_video_verified:r.actual_video_verified===true,in_point_sec:r.in_point_sec??null,out_point_sec:r.out_point_sec??null,verified_frame_indices:r.verified_frame_indices||null,library_hit:r.library_hit===true};
if(r.type==='template'){
  if(!r.template_name||!r.template_data)throw new Error('deterministic fallback for scene '+sceneIndex+' is incomplete');
  out.visual_source='template';out.template_name=r.template_name;out.template_data=r.template_data;out.visual_proof_mode=proofByTemplate[r.template_name]||out.visual_proof_mode;return {json:out};
}
if(!r.url)throw new Error('B-roll resolver returned no media URL for scene '+sceneIndex);
if(out.visual_proof_mode==='annotated_real'){
  if(r.type!=='image')throw new Error('verified-real scene '+sceneIndex+' requires a verified still image');
  out.visual_source='template';out.template_name='annotated_real';out.template_data={imageUrl:r.url,imageWidth:r.width||1080,imageHeight:r.height||1920};
}else if(r.type==='video')out.video_url=r.url;else out.images=[r.url];return {json:out};'''


def replace_merge_node(workflow: dict) -> None:
    merge = node_by_name(workflow, "Merge By scene_index (not position)")
    merge["parameters"]["jsCode"] = r'''// Both aggregate branches arrive through a real Merge node, so this executes
// only after visuals and audio are complete. Join strictly by scene_index.
const allItems=$input.all().map(i=>i.json);
const visualAgg=allItems.find(i=>Array.isArray(i.data)&&i.data[0]&&(i.data[0].images||i.data[0].video_url||i.data[0].visual_source==='template'));
const audioAgg=allItems.find(i=>Array.isArray(i.data)&&i.data[0]&&i.data[0].audio);
if(!visualAgg)throw new Error('Could not find visual branch in merged input');
if(!audioAgg)throw new Error('Could not find audio branch in merged input');
const audios=audioAgg.data;
const merged=visualAgg.data.map(v=>{const match=audios.find(a=>a.scene_index===v.scene_index);if(!match)throw new Error(`No audio found for scene_index ${v.scene_index}`);return {
  scene_index:v.scene_index,images:v.images,video_url:v.video_url,source_duration:v.source_duration,source_width:v.source_width,source_height:v.source_height,
  visual_source:v.visual_source,template_name:v.template_name,template_data:v.template_data,point:v.point,narration:v.narration,visual_prompt:v.visual_prompt,named_subject:v.named_subject,
  visual_claim:v.visual_claim,global_subject:v.global_subject,required_entities:v.required_entities,required_actions:v.required_actions,required_relationships:v.required_relationships,
  forbidden_visuals:v.forbidden_visuals,acceptable_visuals:v.acceptable_visuals,visual_proof_mode:v.visual_proof_mode,asset_semantic_match:v.asset_semantic_match,asset_entity_match:v.asset_entity_match,
  asset_action_match:v.asset_action_match,asset_relationship_match:v.asset_relationship_match,asset_local_similarity:v.asset_local_similarity,asset_frame_similarity:v.asset_frame_similarity,
  actual_video_verified:v.actual_video_verified,in_point_sec:v.in_point_sec,out_point_sec:v.out_point_sec,verified_frame_indices:v.verified_frame_indices,library_hit:v.library_hit,
  selected_query:v.selected_query,_source:v._source,_attribution:v._attribution,audio:match.audio
};});
merged.sort((a,b)=>a.scene_index-b.scene_index);
const sceneCredits=merged.map(s=>String(s._attribution||'').replace(/\s+/g,' ').trim()).filter(Boolean);
const credits=[...new Set([...sceneCredits,'Motion icon assets: useanimations.com (CC BY 4.0)'])];
const baseDescription=[$('Validate Final Script').item.json.seo_description,$('Validate Final Script').item.json.full_script].filter(Boolean).join('\n\n');
const publicationDescription=baseDescription+'\n\nSources / credits:\n'+credits.map(c=>'• '+c).join('\n');
return {json:{hook:$('Validate Final Script').item.json.hook,comment_hook:$('Validate Final Script').item.json.comment_hook,full_script:$('Validate Final Script').item.json.full_script,caption_style:$('Validate Final Script').item.json.caption_style,publication_description:publicationDescription,data:merged}};'''


def patch_publication_metadata(workflow: dict) -> None:
    upload = node_by_name(workflow, "YouTube: Upload Draft")
    upload.setdefault("parameters", {}).setdefault("options", {})["description"] = "={{ $('Merge By scene_index (not position)').item.json.publication_description }}"
    disclosure = node_by_name(workflow, "Disclose AI-Generated Content")
    disclosure["parameters"]["jsonBody"] = r'''={{ JSON.stringify({ id: $json.uploadId || $json.id, status: { privacyStatus: $json.status?.privacyStatus || 'public', selfDeclaredMadeForKids: $json.status?.selfDeclaredMadeForKids ?? false, containsSyntheticMedia: true }, snippet: { title: (($('Validate Final Script').item.json.title || $('Validate Final Script').item.json.hook) || '').slice(0, 50), categoryId: '22', description: ($('Merge By scene_index (not position)').item.json.publication_description || ''), tags: ($('Validate Final Script').item.json.tags || []), defaultLanguage: 'en', defaultAudioLanguage: 'en' } }) }}'''


def add_resolver_topology(workflow: dict) -> None:
    resolver = node_by_name(workflow, "Resolve B-roll")
    body = str(resolver.get("parameters", {}).get("jsonBody", ""))
    if "retrieval_scene_count:" not in body and ", run_id:" in body:
        topology = ", retrieval_scene_count: ($('Validate Final Script').item.json.scenes || []).filter((sc) => sc && sc.visual_source !== 'template').length, retrieval_scene_position: ($('Validate Final Script').item.json.scenes || []).filter((sc) => sc && sc.visual_source !== 'template').findIndex((sc) => Number(sc.scene_index) === Number($('Split Out Scenes').item.json.scene_index))"
        body = body.replace(", run_id:", topology + ", run_id:", 1)
    resolver["parameters"]["jsonBody"] = body
    resolver["parameters"].setdefault("options", {})["timeout"] = 160000


def postprocess_workflow(path: Path) -> None:
    workflow = json.loads(path.read_text())
    internalize_compose_service_urls(workflow)
    clean_visual_director_annotation_contract(workflow)
    clean_tag_broll(workflow)
    replace_merge_node(workflow)
    patch_publication_metadata(workflow)
    add_resolver_topology(workflow)
    workflow.setdefault("meta", {})["production_build_version"] = BUILD_VERSION
    workflow["meta"]["compose_service_transport"] = "docker_internal"
    path.write_text(json.dumps(workflow, indent=2) + "\n")


def build(root: Path, output: Path) -> dict:
    output.mkdir(parents=True, exist_ok=True)

    # Workflow migration pipeline: one authoritative order.
    w0 = root / "n8n" / "workflow.json"
    stages = [output / f"workflow-stage-{i}.json" for i in range(1, 7)]
    run("scripts/upgrade-viral-shorts.py", str(w0), str(stages[0]), cwd=root)
    run("scripts/upgrade-creative-system.py", str(stages[0]), str(stages[1]), cwd=root)
    run("scripts/visual_matching_v4_workflow.py", str(stages[1]), str(stages[2]), cwd=root)
    run("scripts/upgrade-workflow-api-budget.py", str(stages[2]), str(stages[3]), cwd=root)
    run("scripts/upgrade-topic-latency.py", str(stages[3]), str(stages[4]), cwd=root)
    run("scripts/upgrade-anthropic-parser.py", str(stages[4]), str(stages[5]), cwd=root)
    workflow_out = output / "workflow.json"
    shutil.copy2(stages[5], workflow_out)
    postprocess_workflow(workflow_out)

    # Compose/resolver pipeline. Legacy runtime-hardening rewrites are no longer
    # re-applied to the V5 resolver; resolver_v5_runtime owns the small runtime
    # mechanics while semantic policy stays in the checked-in resolver.
    compose_out = output / "compose.js"
    resolver_out = output / "brollResolver.js"
    shutil.copy2(root / "shorts-compose" / "compose.js", compose_out)
    shutil.copy2(root / "shorts-compose" / "brollResolver.js", resolver_out)
    run("scripts/upgrade-compose-creative-system.py", str(compose_out), cwd=root)
    run("scripts/upgrade-compose-api-budget.py", str(compose_out), str(resolver_out), cwd=root)
    run("scripts/resolver_v5_runtime.py", str(resolver_out), cwd=root)
    run("scripts/visual_matching_v4_compose.py", str(compose_out), cwd=root)

    workflow = json.loads(workflow_out.read_text())
    tag_code = node_by_name(workflow, "Tag B-roll")["parameters"]["jsCode"]
    merge_code = node_by_name(workflow, "Merge By scene_index (not position)")["parameters"]["jsCode"]
    resolver_url = str(node_by_name(workflow, "Resolve B-roll")["parameters"].get("url", ""))
    visual_body = str(node_by_name(workflow, "Claude: Visual Director")["parameters"].get("jsonBody", ""))
    if "annotation_plan" in tag_code or "annotations:" in tag_code:
        raise RuntimeError("production Tag B-roll still exposes legacy VLM annotations")
    if "visually locate callout boxes" in visual_body or "locate callout boxes on those pixels" in visual_body:
        raise RuntimeError("production Visual Director still requests CV callout geometry")
    if "Do NOT request callout boxes" not in visual_body:
        raise RuntimeError("verified-real clean-frame contract missing from Visual Director")
    if "deterministic fallback" not in tag_code or "r.type==='template'" not in tag_code:
        raise RuntimeError("production Tag B-roll does not consume deterministic resolver fallback")
    if "publication_description" not in merge_code or "_attribution" not in merge_code:
        raise RuntimeError("publication attribution propagation missing")
    if not resolver_url.startswith(INTERNAL_SERVICE_ORIGIN):
        raise RuntimeError(f"resolver still traverses public proxy: {resolver_url}")

    compose_text = compose_out.read_text()
    resolver_text = resolver_out.read_text()
    for marker in ("VISUAL_MATCHING_V4_COMPOSE", "CATASTROPHIC_FINAL_QA_GATE", "PRODUCTION_BT709_RANGE_NORMALIZATION", "reviewFinalVideo"):
        if marker not in compose_text:
            raise RuntimeError(f"compose artifact missing {marker}")
    for marker in ("candidatePassesGate", "below_semantic_quality_gate", "deterministic_template_fallback", "RESOLVE_DEADLINE_MS", "RESOLVER_V5_RUNTIME", "V5_VIDEO_SAMPLE_STAGING", "V5_PROOF_MEDIA_TYPE_FILTER"):
        if marker not in resolver_text:
            raise RuntimeError(f"resolver artifact missing {marker}")
    if "normalizeAnnotationPlan" in resolver_text or "return annotations as an array" in resolver_text or "annotation_plan" in resolver_text:
        raise RuntimeError("resolver artifact still generates annotation geometry")

    for stage in stages:
        stage.unlink(missing_ok=True)

    artifact_paths = [workflow_out, compose_out, resolver_out]
    manifest = {
        "build_version": BUILD_VERSION,
        "artifacts": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in artifact_paths},
    }
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    root = args.root.resolve()
    output = args.output_dir.resolve()
    manifest = build(root, output)
    print(json.dumps(manifest, sort_keys=True))


if __name__ == "__main__":
    main()
