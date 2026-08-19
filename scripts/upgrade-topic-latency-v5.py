#!/usr/bin/env python3
"""Apply topic-generation latency/budget guardrails after the V4 workflow upgrade.

V3 widens topic ideation from 12 to 36 candidates while the exported Anthropic
request still carries an 8,192-token ceiling, a 60s HTTP timeout, and n8n's
3-attempt automatic retry. This post-transform keeps the two-stage commissioning
design while bounding the first call's latency, output size, and duplicate spend.

POOL_SIZE was originally cut to 24 here, which still overflowed MAX_TOKENS in
production: with the V3 archetype-enriched schema (10 fields/candidate vs the
original 3) plus adaptive thinking sharing the same 6,000-token ceiling,
Claude's response was truncated mid-array, crashing "Parse Topic Pool (V3)"
with a raw JSON.parse SyntaxError. Rather than raise MAX_TOKENS (more latency
per call, the thing V5 exists to bound), POOL_SIZE is brought back down to the
last candidate count proven to fit comfortably in a similar budget.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

MARKER = "TOPIC_LATENCY_V5"
TOPIC_NODE = "Claude: Generate Topic"
POOL_SIZE = 12
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

    token_anchors = ("max_tokens: 9000", "max_tokens: 8192")
    if f"max_tokens: {MAX_TOKENS}" not in body:
        for anchor in token_anchors:
            if anchor in body:
                body = body.replace(anchor, f"max_tokens: {MAX_TOKENS}", 1)
                break
        else:
            raise ValueError("could not patch topic max_tokens: known token anchors not found")

    params["jsonBody"] = body
    params.setdefault("options", {})["timeout"] = TIMEOUT_MS

    # A timeout must not fan out into three expensive duplicate topic calls.
    # A later scheduled run is a safer retry boundary than n8n retrying the same
    # large prompt immediately.
    node["retryOnFail"] = False
    node["maxTries"] = 1
    node["waitBetweenTries"] = 0
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
