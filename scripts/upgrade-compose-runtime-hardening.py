#!/usr/bin/env python3
"""Stable entry point for final compose/B-roll runtime hardening.

VISUAL_MATCHING_V4 already contains the former phase-2 recall, local CLIP,
multi-frame verification, transient retries and fail-closed quality behavior.
Do not re-apply legacy text transforms to it: those transforms target the old
resolver shape and, critically, re-prioritize broad subject text over the exact
scene claim.
"""
from __future__ import annotations
import subprocess
import sys
from pathlib import Path
from compose_retrieval_telemetry import patch_file as patch_compose_retrieval_telemetry
from retrieval_observability import patch_file as patch_retrieval_observability
from retrieval_recall_phase2 import patch_file as patch_retrieval_recall_phase2
from runtime_hardening_impl import upgrade as _upgrade
from video_multiframe_phase3 import patch_file as patch_video_multiframe_phase3

V4_MARKER = "VISUAL_MATCHING_V4"


def _validate_v4(path: Path) -> None:
    text = path.read_text()
    required = [
        V4_MARKER,
        "API_BUDGET",
        "PREPROD_BROLL_HARDENING",
        "RETRIEVAL_RECALL_PHASE2",
        "SOURCE_QUERY_COMPILER_V1",
        "MULTIFRAME_VIDEO_RERANK_V1",
        "sampleVideoContactSheet",
        "frame_similarity",
        "localSemanticRerank",
        "materializeVerifiedClip",
        "passesSemanticGate",
        "fromPixabayVideos",
        "fromWikimediaCommons",
    ]
    missing = [x for x in required if x not in text]
    if missing:
        raise RuntimeError("V4 resolver missing production guarantees: " + ", ".join(missing))
    if "const target = subj ||" in text or "const target=subj||" in text.replace(" ", ""):
        raise RuntimeError("V4 regression: broad subject once again overrides the visual contract")
    p = subprocess.run(["node", "--check", str(path)], text=True, capture_output=True)
    if p.returncode != 0:
        raise RuntimeError("V4 resolver syntax check failed:\n" + p.stdout + p.stderr)


def upgrade(path: Path) -> None:
    text = path.read_text()
    if V4_MARKER in text:
        _validate_v4(path)
        # Compose telemetry is independent of the old resolver internals; apply
        # it when its anchors remain compatible, otherwise V4's own telemetry is
        # authoritative and deployment must not fail just to preserve an old
        # instrumentation transform.
        compose_path = path.with_name("compose.js")
        if compose_path.exists():
            try:
                patch_compose_retrieval_telemetry(compose_path)
            except Exception as exc:
                print(f"V4: compose retrieval telemetry transform skipped: {exc}")
        return

    _upgrade(path)
    patch_retrieval_observability(path)
    patch_retrieval_recall_phase2(path)
    patch_video_multiframe_phase3(path)
    compose_path = path.with_name("compose.js")
    if compose_path.exists():
        patch_compose_retrieval_telemetry(compose_path)


def main():
    if len(sys.argv) != 2:
        raise SystemExit("usage: upgrade-compose-runtime-hardening.py BROLL_RESOLVER_JS")
    path = Path(sys.argv[1])
    upgrade(path)
    print(f"runtime-hardening validation complete for {path}")


if __name__ == "__main__":
    main()
