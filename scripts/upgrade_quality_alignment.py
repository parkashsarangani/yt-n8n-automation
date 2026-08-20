#!/usr/bin/env python3
"""Stable entry point for quality alignment plus final production guardrails."""
from __future__ import annotations

import quality_alignment_impl as _impl
from workflow_contracts import OVERALL_WEAKEST_CAP, QUALITY_MINIMUMS, VISUAL_PLAN_MINIMUM
from workflow_guardrails import assert_workflow_contracts, finalize_workflow

# Explicit policy decision: now that retrieval can fall back to relevant
# templates instead of killing the run, restore the pre-reliability script bar
# rather than leaving the emergency lowered floors as a silent permanent state.
_impl.PUBLISH_MINIMUMS = dict(QUALITY_MINIMUMS)
_impl.VISUAL_PLAN_MINIMUM = VISUAL_PLAN_MINIMUM

# Preserve the historical import surface used by upgrade-anthropic-parser.py.
from quality_alignment_impl import *  # noqa: F401,F403,E402


def upgrade(workflow: dict) -> dict:
    _impl.PUBLISH_MINIMUMS = dict(QUALITY_MINIMUMS)
    _impl.VISUAL_PLAN_MINIMUM = VISUAL_PLAN_MINIMUM
    upgraded = _impl.upgrade(workflow)

    # The reliability hotfix widened the overall-score cap to +8. Restore the
    # earlier +5 calibration while leaving the separate HARD_REJECT repair
    # tolerance untouched.
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
    # This assertion is invoked by upgrade-anthropic-parser.py only after all
    # parser/runtime transforms have landed.  Use that final point to normalize
    # cross-transform issues and enforce the shared contract table.
    finalize_workflow(workflow)
    _impl.assert_alignment(workflow)
    assert_workflow_contracts(workflow)
