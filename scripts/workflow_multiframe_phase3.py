#!/usr/bin/env python3
"""Expose phase-3 frame-sampling metrics through the existing retrieval trace."""
from __future__ import annotations

MARKER = "MULTIFRAME_TELEMETRY_V1"


def node_by_name(workflow: dict, name: str) -> dict:
    for node in workflow.get("nodes", []):
        if node.get("name") == name:
            return node
    raise RuntimeError(f"required workflow node missing: {name}")


def apply(workflow: dict) -> dict:
    tag = node_by_name(workflow, "Tag B-roll")
    code = str(tag["parameters"]["jsCode"])
    if MARKER in code:
        return workflow
    old = "local_similarity:r.local_similarity??null,top_local_similarity:r.top_local_similarity??null,threshold:r.threshold??null,"
    new = "local_similarity:r.local_similarity??null,frame_similarity:r.frame_similarity??null,frame_sample_count:r.frame_sample_count??null,frame_sampling_status:r.frame_sampling_status||null,frame_sampling_ms:r.frame_sampling_ms??null,frame_sampling:r.frame_sampling||{},top_local_similarity:r.top_local_similarity??null,threshold:r.threshold??null,"
    if old not in code:
        raise RuntimeError("Tag B-roll frame telemetry anchor missing")
    code = code.replace(old, new, 1)
    old = "asset_local_similarity:r.local_similarity??null,asset_degraded:r.degraded===true,"
    new = "asset_local_similarity:r.local_similarity??null,asset_frame_similarity:r.frame_similarity??null,asset_frame_sample_count:r.frame_sample_count??null,asset_frame_sampling_status:r.frame_sampling_status||null,asset_frame_sampling_ms:r.frame_sampling_ms??null,asset_degraded:r.degraded===true,"
    if old not in code:
        raise RuntimeError("Tag B-roll asset frame telemetry anchor missing")
    code = code.replace(old, new, 1)
    code = code.replace("// RETRIEVAL_TELEMETRY_V1", "// MULTIFRAME_TELEMETRY_V1\n// RETRIEVAL_TELEMETRY_V1", 1)
    tag["parameters"]["jsCode"] = code

    template = node_by_name(workflow, "Tag Template Video")
    tcode = str(template["parameters"]["jsCode"])
    if "frame_sampling_status" not in tcode:
        old = "local_similarity:null,top_local_similarity:null,threshold:null,"
        new = "local_similarity:null,frame_similarity:null,frame_sample_count:0,frame_sampling_status:'not_applicable',frame_sampling_ms:0,frame_sampling:{enabled:false,attempted:0,completed:0,elapsed_ms:0,deadline_exhausted:false},top_local_similarity:null,threshold:null,"
        if old not in tcode:
            raise RuntimeError("template frame telemetry anchor missing")
        tcode = tcode.replace(old, new, 1)
        template["parameters"]["jsCode"] = tcode
    return workflow


def assert_applied(workflow: dict) -> None:
    tag = str(node_by_name(workflow, "Tag B-roll")["parameters"]["jsCode"])
    for marker in [MARKER, "frame_similarity", "frame_sample_count", "frame_sampling_status", "frame_sampling_ms", "frame_sampling"]:
        if marker not in tag:
            raise RuntimeError(f"phase3 workflow telemetry missing {marker}")
