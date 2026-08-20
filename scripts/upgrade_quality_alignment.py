#!/usr/bin/env python3
"""Align Shorts prompts to downstream quality and b-roll gates."""
from __future__ import annotations

MARKER = "QUALITY_ALIGNMENT"


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
    node["parameters"]["jsonBody"] = r'''={{ JSON.stringify({ model: "claude-sonnet-5", max_tokens: 6000, thinking: { type: "adaptive" }, output_config: { effort: "high" }, messages: [{ role: "user", content: "You are commissioning ONE production-worthy YouTube Short from an already harsh shortlist. QUALITY_ALIGNMENT. Judge the underlying viewing experience, not clever wording and not the candidate's own scores.\n\nSHORTLIST: " + JSON.stringify($json.shortlist) + "\n\nFor each candidate, first answer these concrete tests before scoring:\n1) SHARE TRIGGER: choose exactly one of disbelief, identity, argument, useful_warning, awe, humor, status. State the specific social reason a viewer would send this.\n2) SEND-TO PERSON: name a concrete recipient type in 2-8 words (for example: 'friend who owns a dog'). If no natural recipient exists, the candidate is weak.\n3) NOVELTY DELTA: one sentence in the form 'viewer assumes X -> learns Y'. If Y is just extra trivia rather than a changed mental model, score distinctiveness low.\n4) PROOF VISUAL: identify one visible image/clip/comparison that makes the claim feel real with audio muted.\n5) STOCK FEASIBILITY: score 0-100 for whether that proof and the supporting beats can realistically be found using Pexels, Unsplash, or Wikipedia. Favor familiar visible nouns/actions and archival/reference material. Penalize ideas whose only good visual would require bespoke AI imagery, readable screenshots, obscure footage, or an abstract concept.\n6) STOCK QUERY SEEDS: give 3 short high-inventory search roots (2-5 words) using visible nouns/actions, not cinematic adjectives.\n\nThen deep-score 0-100 on concept_strength, evidence_strength, first_frame_strength, payoff_strength, shareability, distinctiveness, novelty, production_feasibility, naturalness. Overall may not exceed the weakest of concept/evidence/first-frame/payoff/shareability/distinctiveness by more than 5. 80 is merely good; 90 is rare. Reject interchangeable trivia even if factually surprising. Prefer a candidate with a repeatable payoff, a clear novelty delta, an obvious share trigger, and a proof visual that is actually retrievable.\n\nReturn ONLY JSON with a candidates array sorted best-first. Preserve topic, archetype, research_query, first_frame_concept, share_reason. Add evidence_score, visual_score, share_score, concept_score, payoff_score, novelty_score, execution_score, distinctiveness_score, share_trigger, send_to_person, novelty_delta, proof_visual, stock_feasibility, stock_query_seed, reason, score." }] }) }}'''
    node["parameters"].setdefault("options", {})["timeout"] = 90000


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
            f"{MARKER} WRITER - WRITE TO THE ACTUAL PUBLISH GATES, NOT TO VAGUE 'VIRAL' LANGUAGE:\\n"
            "- REPEATABLE PAYOFF: by the end, the viewer must have one plain sentence they could repeat to another person without needing extra context. If you cannot identify that sentence, the script is not ready.\\n"
            "- NOVELTY DELTA: the Short must change a mental model: what a normal viewer probably assumes before watching must be meaningfully different from what they know after. Extra trivia is not enough.\\n"
            "- DISTINCTIVENESS TEST: silently identify the most generic version of this Short, then make the actual version contain at least one specific mechanism, consequence, comparison, proof, or framing choice that the generic version would not contain. Do not manufacture facts to achieve this.\\n"
            "- SHARE TRIGGER: the content itself needs a social reason to send it to one specific kind of person. A spoken 'share this' CTA does not count as shareability.\\n"
            "- B-ROLL REALITY: write scenes around things that can actually be shown with real stock/reference footage or a simple template. visual_prompt should describe visible subjects/actions, not abstract concepts or impossible cinematic scenes. Scene 0 must have a realistically retrievable proof visual.\\n"
            "- QUALITY MARGIN: do not aim to barely pass. A merely adequate 74-77 script is likely to be rejected downstream; strengthen the idea, payoff, specificity, and social reason before output.\\n\\n"
            + anchor
        )
        body = replace_once(body, anchor, rules, "writer quality alignment")
    node["parameters"]["jsonBody"] = body


def patch_editor(workflow: dict) -> None:
    node = node_by_name(workflow, "Claude: Editorial Rewrite (Stage 2)")
    body = node["parameters"]["jsonBody"]
    if f"{MARKER} EDITOR" not in body:
        anchor = "External research leads:"
        rules = (
            f"23. {MARKER} EDITOR - PRE-PUBLISH REPAIR, NOT SCORE GAMING:\\n"
            "- Before assigning quality scores, identify the weakest real dimension of the script and improve the script itself. Never raise a number merely to clear a threshold.\\n"
            "- SHAREABILITY: there must be a concrete social reason to send the Short to a specific recipient. The payoff itself must create that reason; a CTA cannot substitute for it.\\n"
            "- DISTINCTIVENESS: remove any interchangeable explainer/trivia beat. At least one beat must contain a specific mechanism, consequence, comparison, proof, or point of view that a generic script on the same topic would not contain.\\n"
            "- PAYOFF: make the final takeaway compact and repeatable. The viewer should be able to retell the surprising truth in one sentence.\\n"
            "- NOVELTY DELTA: make the before-belief -> after-belief change obvious without literally announcing it.\\n"
            "- B-ROLL FEASIBILITY: do not make the script depend on an obscure or impossible shot. Prefer beats with visible nouns/actions, famous reference material, scale comparisons, or template-friendly numbers.\\n"
            "- CALIBRATION: the validator expects concept>=76, hook>=78, evidence>=74, payoff>=76, information_density>=74, first_frame>=78, visual_progression>=74, shareability>=76, naturalness>=74, distinctiveness>=74, voice_specificity>=72, overall>=77. Aim for a real margin above these, not exact threshold values. If the material cannot honestly reach them, score it low so the next independent critic can reject it.\\n\\n"
            + anchor
        )
        body = replace_once(body, anchor, rules, "editor quality alignment")
    node["parameters"]["jsonBody"] = body


def patch_visual_director(workflow: dict) -> None:
    node = node_by_name(workflow, "Claude: Visual Director")
    node["parameters"]["jsonBody"] = r'''={{ JSON.stringify({ model: "claude-sonnet-5", max_tokens: 8192, thinking: { type: "adaptive" }, output_config: { effort: "high" }, messages: [{ role: "user", content: "You are the INDEPENDENT COMMISSIONING CRITIC and VISUAL DIRECTOR for a high-end YouTube Shorts channel. QUALITY_ALIGNMENT. The editor has already rewritten and self-scored the script. Do not trust those scores automatically. Your first job is to independently judge the actual words; your second job is to perform at most ONE bounded repair when the script is close; your third job is to design retrievable real-media visuals.\n\nSCRIPT: " + JSON.stringify($json.script) + "\n\nCOMMISSIONING INTENT: " + JSON.stringify({ share_trigger: $('Extract Generated Topic').item.json.share_trigger || '', send_to_person: $('Extract Generated Topic').item.json.send_to_person || '', novelty_delta: $('Extract Generated Topic').item.json.novelty_delta || '', proof_visual: $('Extract Generated Topic').item.json.proof_visual || '', stock_feasibility: $('Extract Generated Topic').item.json.stock_feasibility || 0, stock_query_seed: $('Extract Generated Topic').item.json.stock_query_seed || [] }) + "\n\nPHASE 1 - INDEPENDENT QUALITY CRITIC\nIgnore the existing quality numbers at first. Judge the actual script against these publish minimums: concept_strength 76; hook_strength 78; evidence_strength 74; payoff_strength 76; information_density 74; first_frame_strength 78; visual_progression 74; shareability 76; naturalness 74; distinctiveness 74; voice_specificity 72; overall 77. Overall may not exceed the weakest of concept/evidence/first-frame/payoff/shareability by more than 5.\n\nUse concrete tests, not vibes:\n- shareability: identify the specific recipient and social trigger. A generic 'send this to someone' line is not evidence of shareability.\n- distinctiveness: identify what this script contains that an interchangeable explainer on the same topic would not.\n- payoff: identify the one sentence a viewer can repeat later.\n- novelty: identify the before-belief -> after-belief shift.\n- evidence: never strengthen or preserve a hook by inventing facts, causal claims, dates, quotes, or precision.\n\nClassify internally as PASS, REPAIRABLE_NEAR_MISS, or HARD_REJECT.\nHARD_REJECT if evidence is below its gate, the factual premise itself must change, the hook/concept is fundamentally weak, or any failed quality dimension is more than 4 points below its gate. On HARD_REJECT, do NOT inflate scores or cosmetically rewrite the script to sneak through. Preserve the substantive script, set quality scores honestly below the failing gates, set quality_route='hard_reject', and continue to visual planning so the deterministic validator can reject it and spend the retry on a fresh concept.\n\nREPAIRABLE_NEAR_MISS only when evidence is sound and every failing writing/packaging dimension is within 4 points of its gate. Perform exactly one focused repair pass. You may rewrite hook, title, narration wording, payoff wording, comment_hook/outro_line, and scene point/visual_prompt to fix the diagnosed weaknesses. Preserve the core factual claim, evidence boundaries, scene count, scene order, and every scene_index. Do not add unsupported specificity. Rebuild full_script so it matches the final narration. Then independently rescore the revised script and set quality_route='repaired_near_miss'. If it still does not honestly clear the gates, leave the scores below threshold; do not keep iterating.\n\nIf the script already passes on substance, avoid gratuitous rewriting, independently rescore it, and set quality_route='pass'. Preserve all required schema fields.\n\nPHASE 2 - VISUAL DIRECTION FOR REAL RETRIEVAL\nChoose one creative_format: documentary_cinematic, comparison_reveal, minimal_proof, archival_history, macro_detail, kinetic_data. Set visual_grammar to that family. Scene 0 must work muted and must show the proof/result/subject immediately; set first_frame_type to hero_motion, macro_anomaly, face_reaction, scale_comparison, result_first, archive_proof, or kinetic_stat. Assign each content scene visual_role=hero/evidence/detail/comparison/breath/payoff.\n\nFor every NON-TEMPLATE scene, create search_queries specifically for Pexels/Unsplash/Wikipedia retrieval, not as prose image prompts. Use this ordered query taxonomy:\n1) literal query: visible subject + visible action/state, 2-5 words;\n2) broad fallback: high-inventory version with the core visible noun, 2-4 words;\n3) visual variant: another real composition/state/detail, 2-5 words;\n4) scene 0 only: a separate proof/close-up/result query when useful.\nSet stock_search_query to the strongest high-inventory query. Every stock scene needs at least 3 distinct search_queries; scene 0 should have 4 when the material supports it.\n\nSEARCH QUERY RULES: use concrete nouns and visible actions. Prefer common stock-library language. Do NOT use abstract concepts ('hidden truth', 'mind blown', 'economic pressure'), cinematic adjectives ('epic', 'dramatic', 'stunning'), story instructions, narration fragments, camera jargon, or long phrases. Do not make three synonyms of one query. Preserve named_subject for exact real entities; when an exact historical/person/place reference is essential, favor an archival/reference-friendly query. If a beat is fundamentally a number/comparison/punchline and real stock would be generic, use a template instead of forcing weak stock.\n\nSet caption_mode=karaoke/key_phrases/minimal and transition_style=hard_cut. Derive engagement_mode from the final comment_hook/outro_line; do not invent a CTA. Set open_loop_count honestly. Set visual_plan_quality 0-100; generic scene 0, repetitive roles, or unrealistic retrieval must score below 78.\n\nFINAL INTEGRITY PASS: return ONLY the COMPLETE script JSON. Every scene must have sequential scene_index and a non-empty point. Every non-template scene must have visual_role, stock_search_query, and at least 3 concrete search_queries. first_frame_type is required. Preserve or correctly rebuild hook_candidates, caption_style, trigger, payoff, quality, full_script, title, tags, seo_description, and all other required fields. quality scores must describe the final returned script, not the pre-repair version." }] }) }}'''
    node["parameters"].setdefault("options", {})["timeout"] = 120000


def upgrade(workflow: dict) -> dict:
    patch_commissioning(workflow)
    patch_extractor(workflow)
    patch_writer(workflow)
    patch_editor(workflow)
    patch_visual_director(workflow)
    return workflow


def assert_alignment(workflow: dict) -> None:
    commission = node_by_name(workflow, "Claude: Commission Topic Shortlist")["parameters"]["jsonBody"]
    writer = node_by_name(workflow, "Claude: Draft Script (Stage 1)")["parameters"]["jsonBody"]
    editor = node_by_name(workflow, "Claude: Editorial Rewrite (Stage 2)")["parameters"]["jsonBody"]
    visual = node_by_name(workflow, "Claude: Visual Director")["parameters"]["jsonBody"]
    extractor = node_by_name(workflow, "Extract Generated Topic")["parameters"]["jsCode"]
    required = [
        (commission, "STOCK FEASIBILITY", "commissioning stock feasibility"),
        (commission, "SEND-TO PERSON", "commissioning share recipient"),
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
    if "concept_strength 76" not in visual or "overall 77" not in visual:
        raise RuntimeError("independent critic thresholds drifted from validator calibration")
    if "at most ONE bounded repair" not in visual:
        raise RuntimeError("quality repair is no longer explicitly bounded")
