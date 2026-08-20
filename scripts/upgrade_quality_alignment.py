#!/usr/bin/env python3
"""Align Shorts prompts and runtime settings to reliable video completion."""
from __future__ import annotations

import re

MARKER = "QUALITY_ALIGNMENT"
RELIABILITY_MARKER = "RELIABILITY_FIRST_VIDEO"

# These are deliberately competent-video floors, not premium-commissioning
# floors. Evidence remains comparatively strict; packaging/voice/novelty are
# allowed more latitude so a truthful usable Short reaches render/publish.
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


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        return text
    if old not in text:
        raise ValueError(f"could not patch {label}: anchor not found")
    return text.replace(old, new, 1)


def patch_commissioning(workflow: dict) -> None:
    node = node_by_name(workflow, "Claude: Commission Topic Shortlist")
    node["parameters"]["jsonBody"] = r'''={{ JSON.stringify({ model: "claude-sonnet-5", max_tokens: 8192, thinking: { type: "disabled" }, messages: [{ role: "user", content: "You are commissioning ONE production-worthy YouTube Short from a shortlist. QUALITY_ALIGNMENT RELIABILITY_FIRST_VIDEO. Choose a truthful, visually retrievable idea that can actually be produced today. Do not spend output tokens explaining your reasoning.\n\nSHORTLIST: " + JSON.stringify($json.shortlist) + "\n\nEvaluate every input candidate internally for concept, evidence, first-frame strength, payoff, shareability, distinctiveness, novelty, production feasibility, and naturalness. Evidence and stock feasibility matter more than clever wording.\n\nFor the TWO strongest candidates only, return: topic, archetype, research_query, first_frame_concept, share_reason, evidence_score, visual_score, share_score, concept_score, payoff_score, novelty_score, execution_score, distinctiveness_score, share_trigger, send_to_person, novelty_delta, proof_visual, stock_feasibility, stock_query_seed, reason, score. share_trigger must be one of disbelief, identity, argument, useful_warning, awe, humor, status. stock_query_seed must contain 3 short high-inventory visible-noun/action queries. Keep reason under 20 words.\n\nReturn ONLY compact JSON in exactly this shape: {\"candidates\":[...]} with at most 2 candidates, sorted best-first. No prose, no markdown, no thinking text." }] }) }}'''
    node["parameters"].setdefault("options", {})["timeout"] = 120000


def patch_extractor(workflow: dict) -> None:
    node = node_by_name(workflow, "Extract Generated Topic")
    code = node["parameters"]["jsCode"]
    code = replace_once(
        code,
        "execution_score: Number(c.execution_score) || 0, reason:",
        "execution_score: Number(c.execution_score) || 0, distinctiveness_score: Number(c.distinctiveness_score) || 0, share_trigger: String(c.share_trigger || ''), send_to_person: String(c.send_to_person || ''), novelty_delta: String(c.novelty_delta || ''), proof_visual: String(c.proof_visual || ''), stock_feasibility: Number(c.stock_feasibility) || 0, stock_query_seed: Array.isArray(c.stock_query_seed) ? c.stock_query_seed.map(String).slice(0, 4) : [], reason:",
        "commissioning metadata parser",
    )
    code = replace_once(
        code,
        "execution_score: picked.execution_score || 0, candidates,",
        "execution_score: picked.execution_score || 0, distinctiveness_score: picked.distinctiveness_score || 0, share_trigger: picked.share_trigger || '', send_to_person: picked.send_to_person || '', novelty_delta: picked.novelty_delta || '', proof_visual: picked.proof_visual || '', stock_feasibility: picked.stock_feasibility || 0, stock_query_seed: picked.stock_query_seed || [], candidates,",
        "commissioning metadata return",
    )
    node["parameters"]["jsCode"] = code


def patch_writer(workflow: dict) -> None:
    node = node_by_name(workflow, "Claude: Draft Script (Stage 1)")
    body = node["parameters"]["jsonBody"]
    if f"{MARKER} WRITER" not in body:
        anchor = "HOOK - the single most important sentence in the video."
        rules = (
            f"{MARKER} WRITER - RELIABILITY_FIRST_VIDEO:\\n"
            "- Finish a complete, truthful script before optimizing flourishes.\\n"
            "- Keep claims inside the supplied evidence boundaries; never invent precision.\\n"
            "- Make the payoff repeatable in one sentence and scene 0 visually retrievable.\\n"
            "- Prefer concrete visible nouns/actions over abstract or obscure visuals.\\n"
            "- A competent natural Short is publishable; do not overcomplicate the structure to chase a perfect score.\\n\\n"
            + anchor
        )
        body = replace_once(body, anchor, rules, "writer quality alignment")
    node["parameters"]["jsonBody"] = body


def patch_editor(workflow: dict) -> None:
    node = node_by_name(workflow, "Claude: Editorial Rewrite (Stage 2)")
    body = node["parameters"]["jsonBody"]
    if f"{MARKER} EDITOR" not in body:
        anchor = "External research leads:"
        m = PUBLISH_MINIMUMS
        rules = (
            f"23. {MARKER} EDITOR - RELIABILITY_FIRST_VIDEO:\\n"
            "- Repair obvious weakness, but prioritize returning a complete valid script.\\n"
            "- Never raise factual confidence beyond the supplied evidence.\\n"
            "- Prefer a clear, natural, producible Short over a more ambitious fragile one.\\n"
            "- Use templates for abstract numbers/comparisons rather than demanding impossible stock.\\n"
            f"- CALIBRATION: validator floors are concept>={m['concept_strength']}, hook>={m['hook_strength']}, evidence>={m['evidence_strength']}, payoff>={m['payoff_strength']}, information_density>={m['information_density']}, first_frame>={m['first_frame_strength']}, visual_progression>={m['visual_progression']}, shareability>={m['shareability']}, naturalness>={m['naturalness']}, distinctiveness>={m['distinctiveness']}, voice_specificity>={m['voice_specificity']}, overall>={m['overall']}. Score honestly; a competent truthful script should not be discarded merely for lacking premium polish.\\n\\n"
            + anchor
        )
        body = replace_once(body, anchor, rules, "editor quality alignment")
    node["parameters"]["jsonBody"] = body


def patch_visual_director(workflow: dict) -> None:
    node = node_by_name(workflow, "Claude: Visual Director")
    m = PUBLISH_MINIMUMS
    node["parameters"]["jsonBody"] = rf'''={{ JSON.stringify({{ model: "claude-sonnet-5", max_tokens: 8192, thinking: {{ type: "disabled" }}, messages: [{{ role: "user", content: "You are the INDEPENDENT QUALITY CRITIC and VISUAL DIRECTOR for a YouTube Shorts channel. QUALITY_ALIGNMENT RELIABILITY_FIRST_VIDEO. Return a COMPLETE production-ready JSON script. Reliability and truthfulness outrank perfection.\n\nSCRIPT: " + JSON.stringify($json.script) + "\n\nCOMMISSIONING INTENT: " + JSON.stringify({{ share_trigger: $('Extract Generated Topic').item.json.share_trigger || '', send_to_person: $('Extract Generated Topic').item.json.send_to_person || '', novelty_delta: $('Extract Generated Topic').item.json.novelty_delta || '', proof_visual: $('Extract Generated Topic').item.json.proof_visual || '', stock_feasibility: $('Extract Generated Topic').item.json.stock_feasibility || 0, stock_query_seed: $('Extract Generated Topic').item.json.stock_query_seed || [] }}) + "\n\nPHASE 1 - QUALITY CHECK\nJudge the actual script against these publish floors: concept_strength {m['concept_strength']}; hook_strength {m['hook_strength']}; evidence_strength {m['evidence_strength']}; payoff_strength {m['payoff_strength']}; information_density {m['information_density']}; first_frame_strength {m['first_frame_strength']}; visual_progression {m['visual_progression']}; shareability {m['shareability']}; naturalness {m['naturalness']}; distinctiveness {m['distinctiveness']}; voice_specificity {m['voice_specificity']}; overall {m['overall']}. Overall may not exceed the weakest of concept/evidence/first-frame/payoff/shareability by more than 8.\n\nClassify internally as PASS, REPAIRABLE_NEAR_MISS, or HARD_REJECT. HARD_REJECT only if evidence is below its gate, the factual premise itself must change, or a core dimension is more than 8 points below its floor. REPAIRABLE_NEAR_MISS applies when evidence is sound and packaging/writing can be fixed in one pass. Perform at most ONE bounded repair. Preserve factual boundaries, scene order/count, and every scene_index. Rebuild full_script after any wording repair. If the script is competent and truthful, prefer PASS over discarding it for premium-level polish. Set quality_route to pass, repaired_near_miss, or hard_reject and score the FINAL returned script.\n\nPHASE 2 - RETRIEVABLE VISUALS\nChoose creative_format from documentary_cinematic, comparison_reveal, minimal_proof, archival_history, macro_detail, kinetic_data. Set visual_grammar to that family. Set first_frame_type to hero_motion, macro_anomaly, face_reaction, scale_comparison, result_first, archive_proof, or kinetic_stat. Assign visual_role=hero/evidence/detail/comparison/breath/payoff.\n\nFor every NON-TEMPLATE scene create at least 3 concrete Pexels/Unsplash/Wikipedia search_queries: (1) literal query: visible subject/action, (2) broad fallback: high-inventory core visible noun, (3) a distinct visual variant. Scene 0 should have 4 when useful. Set stock_search_query to the strongest query. Queries must be short visible nouns/actions, not cinematic adjectives or abstract concepts. If stock would be generic or obscure, use a template instead.\n\nSet caption_mode=karaoke/key_phrases/minimal, transition_style=hard_cut, engagement_mode from the actual CTA fields, open_loop_count honestly, and visual_plan_quality 0-100. A usable coherent plan should clear {VISUAL_PLAN_MINIMUM}; reserve lower scores for genuinely unrenderable plans.\n\nFINAL INTEGRITY PASS: return ONLY the COMPLETE script JSON. Every scene needs sequential scene_index and non-empty point. Every non-template scene needs visual_role, stock_search_query, and >=3 search_queries. first_frame_type is required. Preserve/rebuild hook_candidates, caption_style, trigger, payoff, quality, full_script, title, tags, seo_description and all other required fields. No prose, markdown, or thinking text." }}] }}) }}'''
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
    node["parameters"]["jsonBody"] = body


def patch_reliability(workflow: dict) -> None:
    # Hidden adaptive reasoning consumes the same response budget needed for the
    # JSON payload. All model stages here are structured-output stages, so favor
    # complete JSON and let the explicit editor/critic prompts do the reasoning.
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
    patch_extractor(workflow)
    patch_writer(workflow)
    patch_editor(workflow)
    patch_visual_director(workflow)
    patch_reliability(workflow)
    return workflow


def assert_alignment(workflow: dict) -> None:
    commission_node = node_by_name(workflow, "Claude: Commission Topic Shortlist")
    commission = commission_node["parameters"]["jsonBody"]
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

    for name in [
        "Claude: Generate Topic",
        "Claude: Commission Topic Shortlist",
        "Claude: Draft Script (Stage 1)",
        "Claude: Editorial Rewrite (Stage 2)",
        "Claude: Visual Director",
    ]:
        body = node_by_name(workflow, name)["parameters"]["jsonBody"]
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
