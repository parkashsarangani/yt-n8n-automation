#!/usr/bin/env python3
"""Stable entry point for quality alignment, production guardrails, and retrieval telemetry."""
from __future__ import annotations

import quality_alignment_impl as _impl
from workflow_contracts import OVERALL_WEAKEST_CAP, QUALITY_MINIMUMS, VISUAL_PLAN_MINIMUM
from workflow_guardrails import assert_workflow_contracts, finalize_workflow
from workflow_retrieval_telemetry import apply as apply_retrieval_telemetry, assert_applied as assert_retrieval_telemetry
from workflow_retrieval_recall_phase2 import apply as apply_retrieval_recall_phase2, assert_applied as assert_retrieval_recall_phase2

_impl.PUBLISH_MINIMUMS = dict(QUALITY_MINIMUMS)
_impl.VISUAL_PLAN_MINIMUM = VISUAL_PLAN_MINIMUM

from quality_alignment_impl import *  # noqa: F401,F403,E402


def upgrade(workflow: dict) -> dict:
    _impl.PUBLISH_MINIMUMS = dict(QUALITY_MINIMUMS)
    _impl.VISUAL_PLAN_MINIMUM = VISUAL_PLAN_MINIMUM
    upgraded = _impl.upgrade(workflow)

    visual = _impl.node_by_name(upgraded, "Claude: Visual Director")
    body = str(visual["parameters"]["jsonBody"])
    body = body.replace(
        "Overall may not exceed the weakest of concept/evidence/first-frame/payoff/shareability by more than 8.",
        f"Overall may not exceed the weakest of concept/evidence/first-frame/payoff/shareability by more than {OVERALL_WEAKEST_CAP}.",
        1,
    )
    visual["parameters"]["jsonBody"] = body

    validator = _impl.node_by_name(upgraded, "Validate Final Script")
    code = str(validator["parameters"]["jsCode"])
    code = code.replace("overall > weakest + 8", f"overall > weakest + {OVERALL_WEAKEST_CAP}")
    code = code.replace("by more than 8 points", f"by more than {OVERALL_WEAKEST_CAP} points")
    validator["parameters"]["jsCode"] = code
    return upgraded


def assert_alignment(workflow: dict) -> None:
    finalize_workflow(workflow)
    apply_retrieval_telemetry(workflow)
    apply_retrieval_recall_phase2(workflow)
    _impl.assert_alignment(workflow)
    assert_workflow_contracts(workflow)
    assert_retrieval_telemetry(workflow)
    assert_retrieval_recall_phase2(workflow)
