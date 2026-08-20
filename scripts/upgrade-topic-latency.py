#!/usr/bin/env python3
"""Apply topic/model latency guardrails and dataflow-independent compose polling.

This transform keeps expensive Anthropic calls single-attempt at the n8n
transport layer and makes the async render poll counter independent of paired
item lineage. Scheduled executions are the retry boundary for transport errors;
the explicit fresh-topic loop remains the retry boundary for script quality.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

MARKER = "TOPIC_LATENCY"
RUNTIME_MARKER = "WORKFLOW_RUNTIME_GUARDS"
POLL_MARKER = "COMPOSE_POLL_STATE"
TOPIC_NODE = "Claude: Generate Topic"
POOL_SIZE = 4
MAX_TOKENS = 6000
TIMEOUT_MS = 120000


def node_by_name(workflow: dict, name: str) -> dict:
    for node in workflow.get("nodes", []):
        if node.get("name") == name:
            return node
    raise KeyError(f"required n8n node not found: {name}")


def patch_single_attempt_model(node: dict, timeout_ms: int) -> None:
    node["retryOnFail"] = False
    node["maxTries"] = 1
    node["waitBetweenTries"] = 0
    node.setdefault("parameters", {}).setdefault("options", {})["timeout"] = timeout_ms
    node["notes"] = RUNTIME_MARKER + ": single bounded model call; do not duplicate paid requests after a client timeout"


def patch_compose_polling(workflow: dict) -> None:
    init = node_by_name(workflow, "Init Poll Counter")
    init["parameters"]["jsCode"] = f"""// {POLL_MARKER}: execution-scoped render polling state.\nconst staticData=$getWorkflowStaticData('node');\nconst runId=String($execution.id||'unknown');\nstaticData.composePolls=staticData.composePolls||{{}};\nconst now=Date.now();\nfor(const [key,value] of Object.entries(staticData.composePolls)){{if(!value||now-Number(value.updatedAt||0)>21600000)delete staticData.composePolls[key];}}\nconst jobId=String($input.first().json.job_id||'').trim();\nif(!jobId)throw new Error('Start Compose Job response missing job_id');\nstaticData.composePolls[runId]={{jobId,pollAttempt:0,updatedAt:now}};\nreturn {{json:{{jobId,pollAttempt:0}}}};"""

    check = node_by_name(workflow, "Check Compose Status")
    check["parameters"]["url"] = "={{ 'https://shorts.interviewbuddy.cloud/compose-status/' + encodeURIComponent(String($json.jobId || '')) }}"

    increment = node_by_name(workflow, "Increment Poll Attempt")
    increment["parameters"]["jsCode"] = f"""// {POLL_MARKER}: dataflow-independent poll counter.\nconst staticData=$getWorkflowStaticData('node');\nconst runId=String($execution.id||'unknown');\nconst state=staticData.composePolls?.[runId];\nif(!state||!state.jobId)throw new Error('Compose poll state missing for execution '+runId);\nconst next=Number(state.pollAttempt||0)+1;\nstate.pollAttempt=next;state.updatedAt=Date.now();\nreturn {{json:{{jobId:state.jobId,pollAttempt:next}}}};"""

    cleanup = f"// {POLL_MARKER}: terminal render-state cleanup.\nconst staticData=$getWorkflowStaticData('node');\nconst runId=String($execution.id||'unknown');\nif(staticData.composePolls)delete staticData.composePolls[runId];\n"
    validate = node_by_name(workflow, "Validate Compose Result")
    if POLL_MARKER not in validate["parameters"]["jsCode"]:
        validate["parameters"]["jsCode"] = cleanup + validate["parameters"]["jsCode"]

    fail = node_by_name(workflow, "Fail: Compose Polling Timeout")
    fail["parameters"]["jsCode"] = cleanup + "throw new Error('Compose job did not finish within 40 poll attempts (~320s) - job_id: '+$input.first().json.jobId+'. The render may be stuck; check shorts-compose logs directly.');"


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
            raise ValueError("could not patch topic pool size: creative-system generation anchor not found")

    token_anchors = ("max_tokens: 9000", "max_tokens: 8192")
    if f"max_tokens: {MAX_TOKENS}" not in body:
        for anchor in token_anchors:
            if anchor in body:
                body = body.replace(anchor, f"max_tokens: {MAX_TOKENS}", 1)
                break
        else:
            raise ValueError("could not patch topic max_tokens: known token anchors not found")

    params["jsonBody"] = body
    patch_single_attempt_model(node, TIMEOUT_MS)
    patch_single_attempt_model(node_by_name(workflow, "Claude: Draft Script (Stage 1)"), 120000)
    patch_single_attempt_model(node_by_name(workflow, "Claude: Editorial Rewrite (Stage 2)"), 120000)
    patch_compose_polling(workflow)
    return workflow


def assert_guardrails(workflow: dict) -> None:
    for name in [TOPIC_NODE, "Claude: Draft Script (Stage 1)", "Claude: Editorial Rewrite (Stage 2)"]:
        node = node_by_name(workflow, name)
        if node.get("retryOnFail") is not False or node.get("maxTries") != 1:
            raise RuntimeError(f"automatic retry survived on {name}")
    init_code = node_by_name(workflow, "Init Poll Counter")["parameters"]["jsCode"]
    increment_code = node_by_name(workflow, "Increment Poll Attempt")["parameters"]["jsCode"]
    if POLL_MARKER not in init_code or POLL_MARKER not in increment_code:
        raise RuntimeError("compose polling state hardening did not land")
    if "$('Init Poll Counter').item" in increment_code:
        raise RuntimeError("compose poll counter still depends on paired-item lineage")
    if "$json.jobId" not in node_by_name(workflow, "Check Compose Status")["parameters"]["url"]:
        raise RuntimeError("compose status lookup lost loop-carried jobId")


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit("usage: upgrade-topic-latency.py INPUT_WORKFLOW OUTPUT_WORKFLOW")
    src, dst = map(Path, sys.argv[1:])
    workflow = json.loads(src.read_text())
    upgraded = upgrade(workflow)
    assert_guardrails(upgraded)
    dst.write_text(json.dumps(upgraded, indent=2) + "\n")
    print(f"topic/runtime latency workflow written to {dst}")


if __name__ == "__main__":
    main()
