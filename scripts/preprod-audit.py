#!/usr/bin/env python3
"""Pre-production audit for the V5 Shorts pipeline.

This audit validates the same generated artifacts that deploy consumes instead
of rebuilding an older transform chain with contradictory assumptions. It
protects the explicit production policy that quality scores and rendered-pixel
QA are advisory: they improve ranking, retries and telemetry but never block an
otherwise renderable scheduled Short.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def die(message: str) -> None:
    raise RuntimeError(message)


def run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    p = subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True)
    if p.returncode != 0:
        raise RuntimeError(f"command failed ({' '.join(cmd)}):\nSTDOUT:\n{p.stdout}\nSTDERR:\n{p.stderr}")
    return p


def node_by_name(workflow: dict, name: str) -> dict:
    for node in workflow.get("nodes", []):
        if node.get("name") == name:
            return node
    die(f"required workflow node missing: {name}")


def require(text: str, markers: list[str], label: str) -> None:
    missing = [m for m in markers if m not in text]
    if missing:
        die(f"{label} missing: {', '.join(missing)}")


def forbid(text: str, markers: list[str], label: str) -> None:
    present = [m for m in markers if m in text]
    if present:
        die(f"{label} contains forbidden behavior: {', '.join(present)}")


def audit_workflow(path: Path) -> None:
    workflow = json.loads(path.read_text())
    meta = workflow.get("meta", {})
    if meta.get("visual_matching_version") != "4":
        die("generated workflow lost visual_matching_version=4 contract")
    if meta.get("production_build_version") != "5":
        die("generated workflow is not a V5 production build")
    if meta.get("compose_service_transport") != "docker_internal":
        die("generated workflow is not using Docker-internal compose transport")

    visual = str(node_by_name(workflow, "Claude: Visual Director").get("parameters", {}).get("jsonBody", ""))
    require(visual, [
        "VISUAL_MATCHING_V4", "visual_claim", "required_entities", "required_actions",
        "required_relationships", "forbidden_visuals", "visual_proof_mode",
        "Do NOT request callout boxes",
    ], "Visual Director contract")
    forbid(visual, ["visually locate callout boxes on those pixels", "return annotations as an array"], "Visual Director contract")

    validator = str(node_by_name(workflow, "Validate Final Script").get("parameters", {}).get("jsCode", ""))
    require(validator, ["VISUAL_MATCHING_V4 contract gate", "needs at least 3 search_queries", "deterministicModes"], "script validator")

    resolver_node = node_by_name(workflow, "Resolve B-roll")
    resolver_url = str(resolver_node.get("parameters", {}).get("url", ""))
    if not resolver_url.startswith("http://shorts-compose:4000/"):
        die(f"Resolve B-roll still traverses public proxy: {resolver_url}")
    resolver_body = str(resolver_node.get("parameters", {}).get("jsonBody", ""))
    require(resolver_body, [
        "visual_claim", "required_entities", "required_actions", "required_relationships",
        "forbidden_visuals", "visual_proof_mode", "template_fallback", "run_id",
        "retrieval_scene_count", "retrieval_scene_position", "$execution.id",
    ], "resolver workflow payload")
    if int(resolver_node.get("parameters", {}).get("options", {}).get("timeout", 0)) < 150000:
        die("Resolve B-roll node timeout is below the V5 internal-service deadline envelope")

    tag = str(node_by_name(workflow, "Tag B-roll").get("parameters", {}).get("jsCode", ""))
    require(tag, [
        "asset_semantic_match", "asset_entity_match", "asset_action_match", "asset_relationship_match",
        "verified_frame_indices", "actual_video_verified", "verified-real scene",
        "deterministic fallback", "r.type==='template'", "quality_gate_passed", "selection_reason",
    ], "Tag B-roll")
    forbid(tag, ["annotation_plan", "annotations:"], "Tag B-roll")

    merge = str(node_by_name(workflow, "Merge By scene_index (not position)").get("parameters", {}).get("jsCode", ""))
    require(merge, ["_attribution", "publicationDescription", "Sources / credits", "useanimations.com (CC BY 4.0)"], "publication metadata merge")
    upload_description = str(node_by_name(workflow, "YouTube: Upload Draft").get("parameters", {}).get("options", {}).get("description", ""))
    if "publication_description" not in upload_description:
        die("YouTube upload description no longer uses the attribution-bearing publication description")
    disclosure = str(node_by_name(workflow, "Disclose AI-Generated Content").get("parameters", {}).get("jsonBody", ""))
    if "publication_description" not in disclosure:
        die("post-upload disclosure step would overwrite source credits")

    for node in workflow.get("nodes", []):
        url = node.get("parameters", {}).get("url")
        if isinstance(url, str) and "shorts.interviewbuddy.cloud" in url:
            die(f"public compose proxy remains in workflow node {node.get('name')}: {url}")


def audit_resolver(path: Path) -> None:
    text = path.read_text()
    require(text, [
        "VISUAL_MATCHING_V4", "RETRIEVAL_RECALL_PHASE2", "SOURCE_QUERY_COMPILER_V1",
        "MULTIFRAME_VIDEO_RERANK_V1", "localSemanticRerank", "diversifyCandidates",
        "fromPexelsVideos", "fromPixabayVideos", "fromPixabayPhotos", "fromWikimediaCommons",
        "candidatePassesGate", "passesSemanticGate", "deterministic_template_fallback",
        "RESOLVE_DEADLINE_MS", "RESOLVER_V5_RUNTIME", "V5_VIDEO_VERIFY_USES_SCENE_BUDGET",
        "V5_VIDEO_SAMPLE_STAGING", "V5_FULL_GATE_EARLY_ACCEPT", "V5_ALWAYS_PUBLISH_BEST_AVAILABLE",
        "best_available_below_quality_target", "no_technically_usable_candidate", "downloadVideoSample",
        "video_contact_sheet_ffmpeg_failed", "materializeVerifiedClip", "verifiedRangeFromFrameIndices",
        "vision_call_limit", "failure_reasons", "quality_gate_passed", "selection_reason",
    ], "production resolver")
    forbid(text, [
        "normalizeAnnotationPlan", "annotation_plan", "return annotations as an array",
        "annotated_real_missing_grounded_callouts", "const target = subj ||",
        "best_start_sec", "best_end_sec", "V5_PROOF_MEDIA_TYPE_FILTER",
        'reason: state.budget_exhausted || "below_semantic_quality_gate"',
    ], "production resolver")
    run(["node", "--check", str(path)])


def audit_compose(path: Path) -> None:
    text = path.read_text()
    require(text, [
        "VISUAL_MATCHING_V4_COMPOSE", "reviewFinalVideo", "NON_BLOCKING_FINAL_QA",
        "publishing anyway", "PRODUCTION_BT709_RANGE_NORMALIZATION", '"-color_range", "tv"',
        "MapVisual", "TimelineVisual", "DiagramVisual", "AnnotatedReal",
    ], "production compose")
    forbid(text, ["Final visual QA rejected catastrophic render defects", "CATASTROPHIC_FINAL_QA_GATE"], "production compose")
    run(["node", "--check", str(path)])


def audit_static_runtime() -> None:
    budget = (ROOT / "shorts-compose/visualBudget.js").read_text()
    require(budget, [
        "BROLL_RUN_MAX_VISION_CALLS || 28", "BROLL_BUDGET_STATE_PATH",
        "STATE_PATH", "acquireLock", "writeState", "durable_state: true",
    ], "durable visual budget")
    forbid(budget, ["const runBudgets = new Map()", "const resultCache = new Map()"], "durable visual budget")
    run(["node", "--check", str(ROOT / "shorts-compose/visualBudget.js")])

    final_qa = (ROOT / "shorts-compose/finalVisualQa.js").read_text()
    require(final_qa, [
        "debug_artifact", "critical_content_clipped", "editorial_cleanliness",
        "safe_area", "caption_integrity", "hard_failed", "hard_issues", "soft_issues",
    ], "final rendered QA telemetry")
    run(["node", "--check", str(ROOT / "shorts-compose/finalVisualQa.js")])

    annotated = (ROOT / "shorts-compose/remotion/src/compositions/AnnotatedReal.tsx").read_text()
    forbid(annotated, [
        "Callouts are positioned from visual verification", "annotations.slice", "annotations.map",
        "<line", "<circle", "{a.label}",
    ], "AnnotatedReal audience renderer")
    require(annotated, ['objectFit: "contain"', "must never leak into the final Short"], "AnnotatedReal audience renderer")

    dc = (ROOT / "docker-compose.yml").read_text()
    require(dc, [
        "BROLL_BUDGET_STATE_PATH=${BROLL_BUDGET_STATE_PATH:-/app/data/visual_budget_state.json}",
        "BROLL_RESOLVE_DEADLINE_MS=${BROLL_RESOLVE_DEADLINE_MS:-135000}",
        "BROLL_FINAL_QA_HARD_SCORE=${BROLL_FINAL_QA_HARD_SCORE:-65}",
        "BROLL_FINAL_QA_HARD_LAYOUT=${BROLL_FINAL_QA_HARD_LAYOUT:-55}",
    ], "docker production settings")

    m = re.search(r"BROLL_RUN_MAX_VISION_CALLS=\$\{BROLL_RUN_MAX_VISION_CALLS:-(\d+)\}", dc)
    if not m or int(m.group(1)) < 28:
        die("run-wide vision budget unexpectedly dropped below 28")


def audit_build_wiring() -> None:
    quality = (ROOT / ".github/workflows/quality-check.yml").read_text()
    deploy = (ROOT / ".github/workflows/deploy.yml").read_text()
    for text, label in [(quality, "quality CI"), (deploy, "deploy")]:
        require(text, ["scripts/build_production_artifacts.py"], label)
    if "upgrade-compose-runtime-hardening.py" in quality or "upgrade-compose-runtime-hardening.py" in deploy:
        die("CI/deploy reintroduced an independent legacy runtime transform chain")
    require(quality, ["cmp /tmp/production-a/manifest.json /tmp/production-b/manifest.json"], "quality deterministic-build check")
    require(deploy, ["/tmp/yt-shorts-production/workflow.json", "/tmp/yt-shorts-production/compose.js", "/tmp/yt-shorts-production/brollResolver.js"], "deploy artifact consumption")


def audit() -> None:
    with tempfile.TemporaryDirectory(prefix="shorts-preprod-v5-") as td:
        out = Path(td) / "production"
        run([sys.executable, str(ROOT / "scripts/build_production_artifacts.py"), "--output-dir", str(out)])
        manifest = json.loads((out / "manifest.json").read_text())
        if manifest.get("build_version") != "5" or set(manifest.get("artifacts", {})) != {"workflow.json", "compose.js", "brollResolver.js"}:
            die(f"invalid production artifact manifest: {manifest}")
        audit_workflow(out / "workflow.json")
        audit_resolver(out / "brollResolver.js")
        audit_compose(out / "compose.js")

    audit_static_runtime()
    audit_build_wiring()
    print("PREPROD AUDIT PASSED: V5 best-available publishing, non-blocking rendered QA, clean verified-real rendering, attribution, durable budgets, internal transport, and deterministic build wiring are consistent")


if __name__ == "__main__":
    try:
        audit()
    except Exception as exc:
        print(f"PREPROD AUDIT FAILED: {exc}", file=sys.stderr)
        raise