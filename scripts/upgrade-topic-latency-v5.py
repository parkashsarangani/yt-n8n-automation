#!/usr/bin/env python3
"""Apply topic-generation latency/budget guardrails after the V4 workflow upgrade.

V3 widened topic ideation from 12 to 36 candidates and raised the Claude output
budget to 9k tokens, but the inherited n8n HTTP timeout remained 60s. This small
post-transform keeps the two-stage commissioning design while making the first
call less expensive and giving it enough wall-clock headroom to complete.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

MARKER = "TOPIC_LATENCY_V5"
TOPIC_NODE = "Claude: Generate Topic"
POOL_SIZE = 24
MAX_TOKENS = 6000
TIMEOUT_MS = 120000


def node_by_name(workflow: dict, name: str) -> dict:
    for node in workflow.get("nodes", []):
        if node.get("name") == name:
            return node
    raise KeyError(f"required n8n node not found: {name}")


def upgrade(workflow: dict) -> dict:
    node = node_by_name(workflow, TOPIC_NODE)
    params = node.setdefault("parameters", {})
    body = str(params.get("jsonBody", ""))

    if MARKER not in body:
        if "GENERATE 36 DISTINCT candidate topics" in body:
            body = body.replace(
                "GENERATE 36 DISTINCT candidate topics",
                f"{MARKER}: GENERATE {POOL_SIZE} DISTINCT candidate topics",
                1,
            )
        elif "GENERATE 24 DISTINCT candidate topics" in body:
            body = body.replace(
                "GENERATE 24 DISTINCT candidate topics",
                f"{MARKER}: GENERATE {POOL_SIZE} DISTINCT candidate topics",
                1,
            )
        else:
            raise ValueError("could not patch topic pool size: V3 generation anchor not found")

    if "max_tokens: 9000" in body:
        body = body.replace("max_tokens: 9000", f"max_tokens: {MAX_TOKENS}", 1)
    elif f"max_tokens: {MAX_TOKENS}" not in body:
        raise ValueError("could not patch topic max_tokens: V3 token anchor not found")

    params["jsonBody"] = body
    params.setdefault("options", {})["timeout"] = TIMEOUT_MS
    return workflow


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit("usage: upgrade-topic-latency-v5.py INPUT_V4_WORKFLOW OUTPUT_V5_WORKFLOW")
    src, dst = map(Path, sys.argv[1:])
    workflow = json.loads(src.read_text())
    dst.write_text(json.dumps(upgrade(workflow), indent=2) + "\n")
    print(f"topic latency V5 workflow written to {dst}")


if __name__ == "__main__":
    main()
