#!/usr/bin/env python3
"""Align Shorts prompts and runtime settings to reliable video completion.

This transform is imported and executed by upgrade-anthropic-parser.py. Keep n8n
HTTP JSON bodies as literal n8n expressions; do not wrap the expression itself
in a Python f-string because ``{{``/``}}`` are significant to both syntaxes.
"""
from __future__ import annotations

import re

MARKER = "QUALITY_ALIGNMENT"
RELIABILITY_MARKER = "RELIABILITY_FIRST_VIDEO"

PUBLISH_MINIMUMS = {
    "concept_strength": 68,
    "hook_strength": 70,
    "evidence_strength": 70,
    "payoff_strength": 68,
    "information_density": 66,
    "first_frame_strength": 70,
    "visual_progression": 66,
    "shareability": 71,
    "naturalness": 66,
    "distinctiveness": 64,
    "voice_specificity": 62,
    "overall": 69,
}
VISUAL_PLAN_MINIMUM = 70


def node_by_name(workflow: dict, name: str) -> dict:
    for node in workflow.get("nodes", []):
        if node.get("name") == name:
            return node
    raise KeyError(f"required n8n node not found: {name}")


def _prepend_user_instruction(body: str, instruction: str) -> str:
    marker = 'content: "'
    if instruction in body:
        return body
    if marker not in body:
        raise ValueError("Claude JSON body has no user content anchor")
    return body.replace(marker, marker + instruction.replace('"', '\\"') + "\\n\\n", 1)


def patch_commissioning(workflow: dict) -> None:
    node = node_by_name(workflow, "Claude: Commission Topic Shortlist")
    node["parameters"]["jsonBody"] = r'''={{ JSON.stringify({ model: "claude-sonnet-5", max_tokens: 8192, thinking: { type: "disabled" }, messages: [{ role: "user", content: "You are commissioning ONE production-worthy YouTube Short from a shortlist. QUALITY_ALIGNMENT RELIABILITY_FIRST_VIDEO. Choose a truthful, visually retrievable idea that can actually be produced today. Do not spend output tokens explaining your reasoning.\n\nSHORTLIST: " + JSON.stringify($json.shortlist) + "\n\nEvaluate every input candidate internally for concept, evidence, first-frame strength, payoff, shareability, distinctiveness, novelty, production feasibility, and naturalness. Evidence and stock feasibility matter more than clever wording.\n\nFor the TWO strongest candidates only, return: topic, archetype, research_query, first_frame_concept, share_reason, evidence_score, visual_score, share_score, concept_score, payoff_score, novelty_score, execution_score, distinctiveness_score, share_trigger, send_to_person, novelty_delta, proof_visual, stock_feasibility, stock_query_seed, reason, score. share_trigger must be one of disbelief, identity, argument, useful_warning, awe, humor, status. stock_query_seed must contain 3 short high-inventory visible-noun/action queries. Keep reason under 20 words.\n\nReturn ONLY compact JSON in exactly this shape: {\"candidates\":[...]} with at most 2 candidates, sorted best-first. No prose, no markdown, no thinking text." }] }) }}'''
    node["parameters"].setdefault("options", {})["timeout"] = 120000


def patch_writer(workflow: dict) -> None:
    node = node_by_name(workflow, "Claude: Draft Script (Stage 1)")
    instruction = (
        f"{MARKER} WRITER - {RELIABILITY_MARKER}: Finish a COMPLETE truthful JSON script before optimizing flourishes. "
        "Keep claims inside supplied evidence boundaries. Prefer concrete retrievable visuals and a clear repeatable payoff. "
        "A competent natural Short is publishable; do not make the structure fragile while chasing premium polish."
    )
    node["parameters"]["jsonBody"] = _prepend_user_instruction(node["parameters"]["jsonBody"], instruction)


def patch_editor(workflow: dict) -> None:
    node = node_by_name(workflow, "Claude: Editorial Rewrite (Stage 2)")
    m = PUBLISH_MINIMUMS
    instruction = (
        f"{MARKER} EDITOR - {RELIABILITY_MARKER}: Prioritize a COMPLETE valid truthful script. "
        "Repair obvious weakness without inventing evidence. Prefer a clear producible Short over a more ambitious fragile one. "
        f"These reliability-first publish floors SUPERSEDE stricter numeric floors elsewhere in this prompt: "
        f"concept>={m['concept_strength']}, hook>={m['hook_strength']}, evidence>={m['evidence_strength']}, "
        f"payoff>={m['payoff_strength']}, information_density>={m['information_density']}, "
        f"first_frame>={m['first_frame_strength']}, visual_progression>={m['visual_progression']}, "
        f"shareability>={m['shareability']}, naturalness>={m['naturalness']}, distinctiveness>={m['distinctiveness']}, "
        f"voice_specificity>={m['voice_specificity']}, overall>={m['overall']}."
    )
    node["parameters"]["jsonBody"] = _prepend_user_instruction(node["parameters"]["jsonBody"], instruction)


def patch_visual_director(workflow: dict) -> None:
    node = node_by_name(workflow, "Claude: Visual Director")
    m = PUBLISH_MINIMUMS

    # IMPORTANT: this is deliberately a raw string, not an f-string. n8n needs
    # the literal expression wrapper `={{ ... }}`. Interpolate numeric values
    # afterwards so Python cannot consume one brace from that wrapper.
    body = r'''={{ JSON.stringify({ model: "claude-sonnet-5", max_tokens: 8192, thinking: { type: "disabled" }, messages: [{ role: "user", content: "You are the INDEPENDENT QUALITY CRITIC and VISUAL DIRECTOR for a YouTube Shorts channel. QUALITY_ALIGNMENT RELIABILITY_FIRST_VIDEO. Return a COMPLETE production-ready JSON script. Reliability and truthfulness outrank perfection.\n\nSCRIPT: " + JSON.stringify($json.script) + "\n\nCOMMISSIONING INTENT: " + JSON.stringify({ share_trigger: $('Extract Generated Topic').item.json.share_trigger || '', send_to_person: $('Extract Generated Topic').item.json.send_to_person || '', novelty_delta: $('Extract Generated Topic').item.json.novelty_delta || '', proof_visual: $('Extract Generated Topic').item.json.proof_visual || '', stock_feasibility: $('Extract Generated Topic').item.json.stock_feasibility || 0, stock_query_seed: $('Extract Generated Topic').item.json.stock_query_seed || [] }) + "\n\nPHASE 1 - QUALITY CHECK\nJudge the actual script against these publish floors: concept_strength __CONCEPT__; hook_strength __HOOK__; evidence_strength __EVIDENCE__; payoff_strength __PAYOFF__; information_density __INFO__; first_frame_strength __FIRST__; visual_progression __VISUAL__; shareability __SHARE__; naturalness __NATURAL__; distinctiveness __DISTINCT__; voice_specificity __VOICE__; overall __OVERALL__. Overall may not exceed the weakest of concept/evidence/first-frame/payoff/shareability by more than 8.\n\nClassify internally as PASS, REPAIRABLE_NEAR_MISS, or HARD_REJECT. HARD_REJECT only if evidence is below its gate, the factual premise itself must change, or a core dimension is more than 8 points below its floor. REPAIRABLE_NEAR_MISS applies when evidence is sound and packaging/writing can be fixed in one pass. Perform at most ONE bounded repair. Preserve factual boundaries, scene order/count, and every scene_index. Rebuild full_script after any wording repair. If the script is competent and truthful, prefer PASS over discarding it for premium-level polish. Set quality_route to pass, repaired_near_miss, or hard_reject and score the FINAL returned script.\n\nPHASE 2 - RETRIEVABLE VISUALS\nChoose creative_format from documentary_cinematic, comparison_reveal, minimal_proof, archival_history, macro_detail, kinetic_data. Set visual_grammar to that family. Set first_frame_type to hero_motion, macro_anomaly, face_reaction, scale_comparison, result_first, archive_proof, or kinetic_stat. Assign visual_role=hero/evidence/detail/comparison/breath/payoff.\n\nFor every NON-TEMPLATE scene create at least 3 concrete Pexels/Unsplash/Wikipedia search_queries: (1) literal query: visible subject/action, (2) broad fallback: high-inventory core visible noun, (3) a distinct visual variant. Scene 0 should have 4 when useful. Set stock_search_query to the strongest query. Queries must be short visible nouns/actions, not cinematic adjectives or abstract concepts. If stock would be generic or obscure, use a template instead.\n\nSet caption_mode=karaoke/key_phrases/minimal, transition_style=hard_cut, engagement_mode from the actual CTA fields, open_loop_count honestly, and visual_plan_quality 0-100. A usable coherent plan should clear __VISUAL_PLAN__; reserve lower scores for genuinely unrenderable plans.\n\nFINAL INTEGRITY PASS: return ONLY the COMPLETE script JSON. Every scene needs sequential scene_index and non-empty point. Every non-template scene needs visual_role, stock_search_query, and >=3 search_queries. first_frame_type is required. Preserve/rebuild hook_candidates, caption_style, trigger, payoff, quality, full_script, title, tags, seo_description and all other required fields. No prose, markdown, or thinking text." }] }) }}'''
    replacements = {
        "__CONCEPT__": m["concept_strength"],
        "__HOOK__": m["hook_strength"],
        "__EVIDENCE__": m["evidence_strength"],
        "__PAYOFF__": m["payoff_strength"],
        "__INFO__": m["information_density"],
        "__FIRST__": m["first_frame_strength"],
        "__VISUAL__": m["visual_progression"],
        "__SHARE__": m["shareability"],
        "__NATURAL__": m["naturalness"],
        "__DISTINCT__": m["distinctiveness"],
        "__VOICE__": m["voice_specificity"],
        "__OVERALL__": m["overall"],
        "__VISUAL_PLAN__": VISUAL_PLAN_MINIMUM,
    }
    for token, value in replacements.items():
        body = body.replace(token, str(value))
    node["parameters"]["jsonBody"] = body
    node["parameters"].setdefault("options", {})["timeout"] = 120000


def _prioritize_complete_json(node: dict, max_tokens: int) -> None:
    body = str(node.get("parameters", {}).get("jsonBody", ""))
    body = re.sub(r"max_tokens:\s*\d+", f"max_tokens: {max_tokens}", body, count=1)
    body = body.replace(
        'thinking: { type: "adaptive" }, output_config: { effort: "high" },',
        'thinking: { type: "disabled" },',
        1,
    )
    body = body.replace(
        'thinking: { type: "adaptive" }, output_config: { effort: "medium" },',
        'thinking: { type: "disabled" },',
        1,
    )
    body = body.replace('thinking: { type: "adaptive" },', 'thinking: { type: "disabled" },', 1)
    if "thinking:" not in body:
        body = re.sub(
            r"(max_tokens:\s*\d+\s*,)",
            r'\1 thinking: { type: "disabled" },',
            body,
            count=1,
        )
    node["parameters"]["jsonBody"] = body


def patch_reliability(workflow: dict) -> None:
    for name, tokens in {
        "Claude: Generate Topic": 6000,
        "Claude: Commission Topic Shortlist": 8192,
        "Claude: Draft Script (Stage 1)": 8192,
        "Claude: Editorial Rewrite (Stage 2)": 8192,
        "Claude: Visual Director": 8192,
    }.items():
        _prioritize_complete_json(node_by_name(workflow, name), tokens)

    validator = node_by_name(workflow, "Validate Final Script")
    code = validator["parameters"]["jsCode"]
    for metric, minimum in PUBLISH_MINIMUMS.items():
        code = re.sub(rf"({re.escape(metric)}:\s*)\d+", rf"\g<1>{minimum}", code, count=1)
    code = code.replace(
        "if(Number(parsed.visual_plan_quality)<78)errors.push(`visual_plan_quality=${parsed.visual_plan_quality} below publish threshold 78`);",
        f"if(Number(parsed.visual_plan_quality)<{VISUAL_PLAN_MINIMUM})errors.push(`visual_plan_quality=${{parsed.visual_plan_quality}} below publish threshold {VISUAL_PLAN_MINIMUM}`);",
    )
    code = code.replace("overall > weakest + 5", "overall > weakest + 8")
    code = code.replace("by more than 5 points", "by more than 8 points")
    validator["parameters"]["jsCode"] = code
    validator["notes"] = RELIABILITY_MARKER + ": competent-video floors; evidence remains fail-closed"


def upgrade(workflow: dict) -> dict:
    patch_commissioning(workflow)
    patch_writer(workflow)
    patch_editor(workflow)
    patch_visual_director(workflow)
    patch_reliability(workflow)
    return workflow


def assert_alignment(workflow: dict) -> None:
    commission = node_by_name(workflow, "Claude: Commission Topic Shortlist")["parameters"]["jsonBody"]
    writer = node_by_name(workflow, "Claude: Draft Script (Stage 1)")["parameters"]["jsonBody"]
    editor = node_by_name(workflow, "Claude: Editorial Rewrite (Stage 2)")["parameters"]["jsonBody"]
    visual = node_by_name(workflow, "Claude: Visual Director")["parameters"]["jsonBody"]
    extractor = node_by_name(workflow, "Extract Generated Topic")["parameters"]["jsCode"]
    validator = node_by_name(workflow, "Validate Final Script")["parameters"]["jsCode"]

    required = [
        (commission, RELIABILITY_MARKER, "commissioning reliability mode"),
        (commission, "TWO strongest candidates", "bounded commissioner output"),
        (writer, f"{MARKER} WRITER", "writer alignment"),
        (editor, f"{MARKER} EDITOR", "editor alignment"),
        (visual, "REPAIRABLE_NEAR_MISS", "independent near-miss repair"),
        (visual, "HARD_REJECT", "independent hard reject"),
        (visual, "literal query", "retrieval query taxonomy"),
        (visual, "broad fallback", "retrieval broad fallback"),
        (visual, "quality_route", "quality routing telemetry"),
        (extractor, "stock_feasibility", "commissioning metadata preservation"),
        (extractor, "novelty_delta", "novelty metadata preservation"),
    ]
    missing = [label for text, marker, label in required if marker not in text]
    if missing:
        raise RuntimeError("quality alignment did not land: " + ", ".join(missing))

    # Regression guard for the production failure on 2026-08-20: an f-string
    # collapsed `={{ ... }}` to `={ ... }`, which n8n treated as invalid JSON.
    for name in [
        "Claude: Generate Topic",
        "Claude: Commission Topic Shortlist",
        "Claude: Draft Script (Stage 1)",
        "Claude: Editorial Rewrite (Stage 2)",
        "Claude: Visual Director",
    ]:
        body = str(node_by_name(workflow, name)["parameters"]["jsonBody"]).strip()
        if not (body.startswith("={{") and body.endswith("}}") and "JSON.stringify(" in body):
            raise RuntimeError(f"{name} JSON Body lost its n8n expression wrapper")
        if 'thinking: { type: "adaptive" }' in body or 'thinking: { type: "disabled" }' not in body:
            raise RuntimeError(f"{name} is not configured to prioritize complete JSON")

    if "max_tokens: 8192" not in commission:
        raise RuntimeError("commissioner response budget is below reliability target")
    if f"concept_strength: {PUBLISH_MINIMUMS['concept_strength']}" not in validator:
        raise RuntimeError("validator concept floor did not move to reliability calibration")
    if f"shareability: {PUBLISH_MINIMUMS['shareability']}" not in validator:
        raise RuntimeError("validator shareability floor did not move to reliability calibration")
    if f"visual_plan_quality)<{VISUAL_PLAN_MINIMUM}" not in validator:
        raise RuntimeError("visual-plan floor did not move to reliability calibration")
    if "at most ONE bounded repair" not in visual:
        raise RuntimeError("quality repair is no longer explicitly bounded")
