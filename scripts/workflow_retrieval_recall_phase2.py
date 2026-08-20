#!/usr/bin/env python3
"""Expose phase-2 retrieval sources/query plans in the generated n8n workflow."""
from __future__ import annotations

MARKER = "RETRIEVAL_RECALL_PHASE2"


def node_by_name(workflow: dict, name: str) -> dict:
    for node in workflow.get("nodes", []):
        if node.get("name") == name:
            return node
    raise RuntimeError(f"required workflow node missing: {name}")


def apply(workflow: dict) -> dict:
    visual = node_by_name(workflow, "Claude: Visual Director")
    body = str(visual["parameters"]["jsonBody"])
    body = body.replace(
        "source_priority as an ordered subset of wikimedia, wikipedia, pexels_video, pexels, unsplash.",
        "source_priority as an ordered subset of wikimedia, wikipedia, pexels_video, pixabay_video, pexels, pixabay, unsplash.",
    )
    if MARKER not in body:
        body = body.replace("VISUAL_SOURCE_ROUTER_V2 - EXECUTABLE VISUAL CONTRACT.", "VISUAL_SOURCE_ROUTER_V2 - EXECUTABLE VISUAL CONTRACT. RETRIEVAL_RECALL_PHASE2.", 1)
    visual["parameters"]["jsonBody"] = body

    validator = node_by_name(workflow, "Validate Final Script")
    code = str(validator["parameters"]["jsCode"])
    code = code.replace(
        "const allowedSources=new Set(['wikimedia','wikipedia','pexels_video','pexels','unsplash']);",
        "const allowedSources=new Set(['wikimedia','wikipedia','pexels_video','pixabay_video','pexels','pixabay','unsplash']);",
    )
    code = code.replace(
        "['wikimedia','wikipedia','pexels_video','pexels']",
        "['wikimedia','wikipedia','pixabay','pixabay_video','pexels_video','pexels']",
    )
    code = code.replace(
        "['wikimedia','wikipedia','pexels_video','pexels','unsplash']",
        "['pixabay_video','pexels_video','wikimedia','pixabay','pexels','wikipedia','unsplash']",
    )
    code = code.replace(
        "['pexels_video','pexels','unsplash','wikimedia','wikipedia']",
        "['pexels_video','pixabay_video','pexels','pixabay','unsplash','wikimedia','wikipedia']",
    )
    validator["parameters"]["jsCode"] = code

    tag = node_by_name(workflow, "Tag B-roll")
    tag_code = str(tag["parameters"]["jsCode"])
    if "compiled_query_plan:" not in tag_code:
        anchor = "const retrieval={scene_index:sceneIndex,"
        replacement = "const retrieval={compiled_query_plan:r.query_plan||{},scene_index:sceneIndex,"
        if anchor not in tag_code:
            raise RuntimeError("Tag B-roll retrieval object anchor missing")
        tag_code = tag_code.replace(anchor, replacement, 1)
    tag["parameters"]["jsCode"] = tag_code
    return workflow


def assert_applied(workflow: dict) -> None:
    visual = str(node_by_name(workflow, "Claude: Visual Director")["parameters"]["jsonBody"])
    validator = str(node_by_name(workflow, "Validate Final Script")["parameters"]["jsCode"])
    tag = str(node_by_name(workflow, "Tag B-roll")["parameters"]["jsCode"])
    if MARKER not in visual:
        raise RuntimeError("Visual Director lost phase2 retrieval marker")
    for source in ["pixabay_video", "pixabay"]:
        if source not in visual or source not in validator:
            raise RuntimeError(f"generated workflow does not expose source: {source}")
    if "compiled_query_plan:r.query_plan||{}" not in tag:
        raise RuntimeError("retrieval telemetry does not preserve compiled query plan")
