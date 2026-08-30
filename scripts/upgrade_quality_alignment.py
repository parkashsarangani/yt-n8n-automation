#!/usr/bin/env python3
"""Stable entry point for quality alignment, production guardrails, retrieval telemetry, and Visual Matching V4."""
from __future__ import annotations

import quality_alignment_impl as _impl
from workflow_contracts import OVERALL_WEAKEST_CAP, QUALITY_MINIMUMS, VISUAL_PLAN_MINIMUM
from workflow_guardrails import assert_workflow_contracts, finalize_workflow
from workflow_retrieval_telemetry import apply as apply_retrieval_telemetry, assert_applied as assert_retrieval_telemetry
from workflow_retrieval_recall_phase2 import apply as apply_retrieval_recall_phase2, assert_applied as assert_retrieval_recall_phase2
from workflow_multiframe_phase3 import apply as apply_multiframe_phase3, assert_applied as assert_multiframe_phase3
from visual_matching_v4_workflow import upgrade as apply_visual_matching_v4, assert_applied as assert_visual_matching_v4

_impl.PUBLISH_MINIMUMS = dict(QUALITY_MINIMUMS)
_impl.VISUAL_PLAN_MINIMUM = VISUAL_PLAN_MINIMUM

from quality_alignment_impl import *  # noqa: F401,F403,E402


MACRO_CONTEXT_EXPR = "OVERALL SELECTED TOPIC / MACRO CONTEXT: \" + String($('Extract Generated Topic').item.json.topic || '')"


def _prepare_preexisting_v4_for_alignment(workflow: dict) -> None:
    """Preserve the legacy compatibility subset when V4 was applied early.

    Some validation/deploy paths intentionally exercise V4 before the final
    quality-alignment pass. The legacy implementation skips its resolver/merge
    compatibility patch when those fields are already present, so make the
    pre-applied V4 payload a strict superset before delegating to it.
    """
    resolver = _impl.node_by_name(workflow, "Resolve B-roll")
    body = str(resolver["parameters"].get("jsonBody", ""))
    if workflow.get("meta", {}).get("visual_matching_version") == "4" and "must_show:" not in body:
        anchor = "run_id: String($execution.id || '')"
        if anchor not in body:
            raise RuntimeError("pre-applied V4 resolver lost run_id anchor")
        legacy = (
            "visual_mode: ($('Split Out Scenes').item.json.visual_mode || 'context_real'), "
            "must_show: ($('Split Out Scenes').item.json.must_show || $('Split Out Scenes').item.json.visual_claim || $('Split Out Scenes').item.json.named_subject || $('Split Out Scenes').item.json.stock_search_query || ''), "
            "acceptable_substitutes: ($('Split Out Scenes').item.json.acceptable_substitutes || $('Split Out Scenes').item.json.acceptable_visuals || []), "
            "source_priority: ($('Split Out Scenes').item.json.source_priority || []), "
            "template_fallback: ($('Split Out Scenes').item.json.template_fallback || null), "
        )
        resolver["parameters"]["jsonBody"] = body.replace(anchor, legacy + anchor, 1)

    merge = _impl.node_by_name(workflow, "Merge By scene_index (not position)")
    code = str(merge["parameters"].get("jsCode", ""))
    if workflow.get("meta", {}).get("visual_matching_version") == "4" and "asset_local_similarity:" in code and "asset_degraded:" not in code:
        anchor = "    audio: match.audio,"
        if anchor not in code:
            raise RuntimeError("pre-applied V4 merge lost audio compatibility anchor")
        legacy = (
            "    asset_degraded: v.asset_degraded === true,\n"
            "    quality_gate_passed: v.quality_gate_passed !== false,\n"
            "    fallback_reason: v.fallback_reason || null,\n"
            "    visual_mode: v.visual_mode || match.visual_mode || null,\n"
        )
        merge["parameters"]["jsCode"] = code.replace(anchor, legacy + anchor, 1)


def _ensure_macro_context_expression(workflow: dict) -> None:
    """Put the actual chosen topic into both V4 planning calls, not just instructions."""
    for node_name in ["Claude: Visual Director", "Claude: Repair Script"]:
        try:
            visual = _impl.node_by_name(workflow, node_name)
        except KeyError:
            continue
        body = str(visual["parameters"].get("jsonBody", ""))
        if not body or MACRO_CONTEXT_EXPR in body:
            continue
        anchors = [
            'SCRIPT: " + JSON.stringify($json.draft) + "\\n\\nCOMMISSIONING INTENT:',
            'SCRIPT: " + JSON.stringify($(\'Validate Final Script\').item.json._failedScript) + "\\n\\nCOMMISSIONING INTENT:',
        ]
        replacement_suffix = 'SCRIPT: " + JSON.stringify(__SCRIPT__) + "\\n\\nOVERALL SELECTED TOPIC / MACRO CONTEXT: " + String($(\'Extract Generated Topic\').item.json.topic || \'\') + "\\n\\nCOMMISSIONING INTENT:'
        replaced = False
        for anchor in anchors:
            if anchor not in body:
                continue
            script_expr = "$json.draft" if "$json.draft" in anchor else "$('Validate Final Script').item.json._failedScript"
            replacement = replacement_suffix.replace("__SCRIPT__", script_expr)
            body = body.replace(anchor, replacement, 1)
            replaced = True
            break
        if not replaced:
            raise RuntimeError(f"{node_name} lost SCRIPT/COMMISSIONING macro-context insertion anchor")
        visual["parameters"]["jsonBody"] = body


def _preserve_legacy_visual_guardrails(workflow: dict) -> None:
    """Keep the useful V2 safety metadata as a compatibility subset of V4."""
    resolver = _impl.node_by_name(workflow, "Resolve B-roll")
    body = str(resolver["parameters"]["jsonBody"])
    if "must_show:" in body and "template_fallback:" in body:
        return
    anchor = "run_id: String($execution.id || '')"
    if anchor not in body:
        raise RuntimeError("V4 resolver run_id anchor missing while preserving V2 guardrails")
    prefix = (
        "visual_mode: ($('Split Out Scenes').item.json.visual_mode || 'context_real'), "
        "must_show: ($('Split Out Scenes').item.json.must_show || $('Split Out Scenes').item.json.visual_claim || $('Split Out Scenes').item.json.named_subject || $('Split Out Scenes').item.json.stock_search_query || ''), "
        "acceptable_substitutes: ($('Split Out Scenes').item.json.acceptable_substitutes || $('Split Out Scenes').item.json.acceptable_visuals || []), "
        "source_priority: ($('Split Out Scenes').item.json.source_priority || []), "
        "template_fallback: ($('Split Out Scenes').item.json.template_fallback || null), "
    )
    resolver["parameters"]["jsonBody"] = body.replace(anchor, prefix + anchor, 1)


def upgrade(workflow: dict) -> dict:
    _impl.PUBLISH_MINIMUMS = dict(QUALITY_MINIMUMS)
    _impl.VISUAL_PLAN_MINIMUM = VISUAL_PLAN_MINIMUM
    _prepare_preexisting_v4_for_alignment(workflow)
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

    apply_visual_matching_v4(upgraded)
    _ensure_macro_context_expression(upgraded)
    _preserve_legacy_visual_guardrails(upgraded)
    return upgraded


def assert_alignment(workflow: dict) -> None:
    assert_visual_matching_v4(workflow)
    _ensure_macro_context_expression(workflow)
    _preserve_legacy_visual_guardrails(workflow)
    finalize_workflow(workflow)
    apply_retrieval_telemetry(workflow)
    apply_retrieval_recall_phase2(workflow)
    apply_multiframe_phase3(workflow)
    _impl.assert_alignment(workflow)
    assert_workflow_contracts(workflow)
    assert_retrieval_telemetry(workflow)
    assert_retrieval_recall_phase2(workflow)
    assert_multiframe_phase3(workflow)
    assert_visual_matching_v4(workflow)
    final_visual = str(_impl.node_by_name(workflow, "Claude: Visual Director")["parameters"]["jsonBody"])
    if MACRO_CONTEXT_EXPR not in final_visual:
        raise RuntimeError("V4 Visual Director contains macro-context instructions but not the actual selected topic expression")
