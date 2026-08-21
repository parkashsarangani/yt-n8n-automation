#!/usr/bin/env python3
"""Pre-production audit for the Shorts workflow.

Runs the exact deploy-time transform chain against the canonical workflow,
executes synthetic n8n Code-node responses for known production failure modes,
and validates compose/b-roll runtime invariants without calling external APIs.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def die(message: str) -> None:
    raise RuntimeError(message)


def run(cmd: list[str], *, cwd: Path = ROOT, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    p = subprocess.run(cmd, cwd=cwd, env=env, text=True, capture_output=True)
    if p.returncode != 0:
        raise RuntimeError(
            f"command failed ({' '.join(cmd)}):\nSTDOUT:\n{p.stdout}\nSTDERR:\n{p.stderr}"
        )
    return p


def node_by_name(workflow: dict, name: str) -> dict:
    for node in workflow.get("nodes", []):
        if node.get("name") == name:
            return node
    die(f"missing workflow node: {name}")


def first_edge(workflow: dict, name: str) -> str | None:
    try:
        return workflow["connections"][name]["main"][0][0]["node"]
    except (KeyError, IndexError, TypeError):
        return None


def run_code_node(js_code: str, payload: dict, prior: dict | None = None) -> dict:
    prior = prior or {}
    harness = r'''
const code = JSON.parse(process.env.AUDIT_CODE);
const payload = JSON.parse(process.env.AUDIT_INPUT);
const prior = JSON.parse(process.env.AUDIT_PRIOR || '{}');
const $input = { first: () => ({ json: payload }), all: () => [{ json: payload }] };
const $ = (name) => ({ item: { json: prior[name] || {} }, first: () => ({ json: prior[name] || {} }), all: () => [{ json: prior[name] || {} }] });
const $execution = { id: 'preprod-audit-execution' };
try {
  const fn = new Function('$input', '$', '$execution', code);
  const result = fn($input, $, $execution);
  console.log('__PREPROD__' + JSON.stringify({ ok: true, result }));
} catch (err) {
  console.log('__PREPROD__' + JSON.stringify({ ok: false, error: String(err && err.message || err) }));
}
'''
    env = os.environ.copy()
    env["AUDIT_CODE"] = json.dumps(js_code)
    env["AUDIT_INPUT"] = json.dumps(payload)
    env["AUDIT_PRIOR"] = json.dumps(prior)
    p = run(["node", "-e", harness], env=env)
    lines = [line for line in p.stdout.splitlines() if line.startswith("__PREPROD__")]
    if not lines:
        die("Code-node harness produced no result marker: " + p.stdout)
    return json.loads(lines[-1][len("__PREPROD__"):])


def assert_ok(result: dict, label: str) -> dict:
    if not result.get("ok"):
        die(f"{label} failed: {result.get('error')}")
    return result.get("result") or {}


def candidate(i: int) -> dict:
    return {
        "topic": f"A recognizable surprising fact number {i}",
        "archetype": "looks_fake_but_real",
        "research_query": "recognizable fact evidence",
        "first_frame_concept": "close visible proof",
        "share_reason": "send to a curious friend",
        "evidence_score": 82,
        "visual_score": 84,
        "share_score": 83,
        "concept_score": 83,
        "payoff_score": 82,
        "novelty_score": 84,
        "execution_score": 82,
        "distinctiveness_score": 82,
        "share_trigger": "disbelief",
        "send_to_person": "curious friend",
        "novelty_delta": "viewer assumes X -> learns Y",
        "proof_visual": "close visible proof",
        "stock_feasibility": 90,
        "stock_query_seed": ["visible subject", "subject close up", "subject detail"],
        "reason": "strong",
        "score": 83,
    }


def good_script(*, sparse_queries: bool = False) -> dict:
    quality = {
        "concept_strength": 82,
        "hook_strength": 82,
        "evidence_strength": 82,
        "payoff_strength": 82,
        "information_density": 82,
        "first_frame_strength": 82,
        "visual_progression": 82,
        "shareability": 82,
        "naturalness": 82,
        "distinctiveness": 82,
        "voice_specificity": 82,
        "overall": 82,
    }
    narrations = [
        "The first beat shows the familiar subject clearly and states one concrete surprising claim without wasting any words.",
        "The second beat gives the specific mechanism and a visible piece of evidence that changes what the viewer assumed.",
        "The final beat resolves the promise with a compact comparison that is easy to repeat to another person later.",
    ]
    scenes = []
    roles = ["hero", "evidence", "payoff"]
    for i, narration in enumerate(narrations):
        scene = {
            "scene_index": i,
            "point": ["surprising claim", "visible evidence", "repeatable payoff"][i],
            "narration": narration,
            "visual_source": "stock",
            "visual_type": "real",
            "visual_prompt": ["shark swimming underwater close", "shark ocean swimming detail", "shark size comparison ocean"][i],
            "negative_prompt": "no readable text, no legible numbers, no documents or screens",
            "stock_search_query": "" if sparse_queries else ["shark underwater", "shark ocean", "shark comparison"][i],
            "named_subject": "",
            "search_queries": [] if sparse_queries else [
                ["shark underwater", "shark ocean", "shark close up"],
                ["shark swimming", "shark ocean", "shark detail"],
                ["shark comparison", "shark ocean", "shark wide shot"],
            ][i],
            "visual_role": roles[i],
        }
        scenes.append(scene)
    return {
        "hook": "A familiar shark fact sounds impossible until you see what is actually happening.",
        "hook_type": "counterintuitive_claim",
        "hook_candidates": [
            "This shark fact sounds impossible until you see it.",
            "The shark fact you know is missing the strangest part.",
            "One shark detail completely changes the scale of the story.",
            "The visible proof makes this shark fact much harder to dismiss.",
            "This is the shark comparison people actually remember.",
        ],
        "title": "The Shark Detail Everyone Misses",
        "seo_description": "A clear shark fact explained with visible evidence and a simple comparison. Which part surprised you most?",
        "comment_hook": None,
        "outro_line": None,
        "tags": ["sharks", "ocean", "animals", "facts", "shorts", "science", "explained", "nature"],
        "full_script": "INTENTIONALLY STALE BEFORE NORMALIZATION",
        "caption_style": "neutral",
        "trigger": "disbelief",
        "payoff": {"claim": "the compact comparison resolves the hook", "resolved_in_scene": 2},
        "creative_format": "documentary_cinematic",
        "visual_grammar": "documentary_cinematic",
        "caption_mode": "key_phrases",
        "transition_style": "hard_cut",
        "engagement_mode": "none",
        "open_loop_count": 1,
        "visual_plan_quality": 84,
        "first_frame_type": "hero_motion",
        "quality_route": "pass",
        "scenes": scenes,
        "quality": quality,
    }


def build_workflow(tmp: Path) -> dict:
    stages = [
        ("upgrade-viral-shorts.py", ROOT / "n8n/workflow.json", tmp / "v1.json"),
        ("upgrade-creative-system.py", tmp / "v1.json", tmp / "v2.json"),
        ("upgrade-workflow-api-budget.py", tmp / "v2.json", tmp / "v3.json"),
        ("upgrade-topic-latency.py", tmp / "v3.json", tmp / "v4.json"),
        ("upgrade-anthropic-parser.py", tmp / "v4.json", tmp / "final.json"),
    ]
    for script, src, dst in stages:
        run([sys.executable, str(ROOT / "scripts" / script), str(src), str(dst)])
    return json.loads((tmp / "final.json").read_text())


def audit() -> None:
    required_py = [
        "upgrade-viral-shorts.py", "upgrade-creative-system.py", "upgrade-workflow-api-budget.py",
        "upgrade-topic-latency.py", "upgrade_quality_alignment.py", "upgrade-anthropic-parser.py",
        "upgrade-compose-creative-system.py", "upgrade-compose-api-budget.py", "upgrade-compose-runtime-hardening.py",
        "preprod-audit.py",
    ]
    run([sys.executable, "-m", "py_compile", *[str(ROOT / "scripts" / x) for x in required_py]])

    with tempfile.TemporaryDirectory(prefix="shorts-preprod-") as td:
        tmp = Path(td)
        workflow = build_workflow(tmp)
        names = {n["name"]: n for n in workflow["nodes"]}

        # n8n's deploy API rejects the whole workflow (400
        # unknown_connection_source) if the connections dict has a key or a
        # target naming a node that isn't in the nodes array - e.g. a node
        # deletion that cleaned up the node itself but left a dangling
        # connections entry inherited from an earlier patch stage. Neither
        # this script's other checks nor the local JS test suite talk to a
        # real n8n instance, so this is the only local check that catches it
        # before a deploy actually fails against the live API.
        node_names = set(names.keys())
        for src in workflow.get("connections", {}):
            if src not in node_names:
                die(f"dangling connection source: {src!r} does not reference an existing node")
        for src, out in workflow.get("connections", {}).items():
            for branch in out.get("main", []):
                for edge in branch or []:
                    if edge.get("node") not in node_names:
                        die(f"dangling connection target: {src!r} -> {edge.get('node')!r} does not reference an existing node")

        expected_edges = {
            "Claude: Generate Topic": "Parse Topic Pool",
            "Parse Topic Pool": "Claude: Commission Topic Shortlist",
            "Claude: Commission Topic Shortlist": "Extract Generated Topic",
            "Wikipedia: Research Topic": "Normalize Research Evidence",
            "Normalize Research Evidence": "Claude: Draft Script (Stage 1)",
            "Parse Draft JSON": "Claude: Visual Director",
            "Claude: Visual Director": "Validate Final Script",
        }
        for src, dst in expected_edges.items():
            if first_edge(workflow, src) != dst:
                die(f"graph drift: {src} -> {first_edge(workflow, src)!r}, expected {dst}")

        expected_timeouts = {
            "Claude: Generate Topic": 120000,
            "Claude: Commission Topic Shortlist": 120000,
            "Claude: Draft Script (Stage 1)": 120000,
            "Claude: Visual Director": 180000,
            "ElevenLabs: TTS+Timestamps": 60000,
            "Resolve B-roll": 180000,
        }
        for name, expected in expected_timeouts.items():
            got = names[name].get("parameters", {}).get("options", {}).get("timeout")
            if got != expected:
                die(f"timeout drift: {name}={got}, expected {expected}")

        for name in ["Claude: Generate Topic", "Claude: Commission Topic Shortlist", "Claude: Visual Director"]:
            node = names[name]
            if node.get("retryOnFail") is not False or node.get("maxTries") != 1:
                die(f"duplicate-call risk: {name} automatic retry is not bounded to one call")

        visual_body = names["Claude: Visual Director"]["parameters"]["jsonBody"]
        for marker in ["QUALITY_ALIGNMENT", "REPAIRABLE_NEAR_MISS", "HARD_REJECT", "literal query", "broad fallback"]:
            if marker not in visual_body:
                die(f"Visual Director lost prompt contract: {marker}")
        if 'thinking: { type: "disabled" }' not in visual_body:
            die("Visual Director adaptive thinking still competes with complete JSON output")

        parser_names = ["Parse Topic Pool", "Extract Generated Topic", "Parse Draft JSON", "Validate Final Script"]
        for name in parser_names:
            code = names[name]["parameters"]["jsCode"]
            for marker in ["ANTHROPIC_TEXT_BLOCK_GUARD", "LAST_VALID_JSON_OBJECT"]:
                if marker not in code:
                    die(f"{name} missing {marker}")
            if "content?.[0]?.text" in code:
                die(f"{name} still assumes content[0].text")

        pool_obj = {"candidates": [candidate(i) for i in range(4)]}
        pool_text = '{"candidates":[} this false start never closes\nWait\n' + json.dumps(pool_obj)
        pool = assert_ok(run_code_node(names["Parse Topic Pool"]["parameters"]["jsCode"], {
            "content": [{"type": "thinking", "thinking": "x"}, {"type": "text", "text": pool_text[:40]}, {"type": "text", "text": pool_text[40:]}],
            "stop_reason": "end_turn",
        }), "topic pool self-correction")
        if len(pool.get("json", {}).get("pool", [])) != 4:
            die("topic pool did not recover all four candidates")

        commissioned_obj = {"candidates": [candidate(i) for i in range(4)]}
        commissioned_text = '{"candidates":[[]][0] || null}\nCorrecting.\n' + json.dumps(commissioned_obj)
        picked = assert_ok(run_code_node(
            names["Extract Generated Topic"]["parameters"]["jsCode"],
            {"content": [{"type": "text", "text": commissioned_text}], "stop_reason": "end_turn"},
            {"Ensure Topics Array": {"topics": []}, "Parse Topic Pool": pool.get("json", {})},
        ), "commissioner self-correction")
        if not picked.get("json", {}).get("stock_query_seed"):
            die("commissioner parser dropped stock_query_seed")

        minimal_script = {"hook": "A complete hook", "scenes": [{"scene_index": 0, "point": "p", "narration": "enough narration"}]}
        split_json = json.dumps(minimal_script)
        draft = assert_ok(run_code_node(names["Parse Draft JSON"]["parameters"]["jsCode"], {
            "content": [{"type": "text", "text": split_json[:17]}, {"type": "thinking", "thinking": "x"}, {"type": "text", "text": split_json[17:]}],
            "stop_reason": "end_turn",
        }), "draft split text blocks")
        if draft.get("json", {}).get("draft", {}).get("hook") != "A complete hook":
            die("draft parser did not reassemble split text blocks")

        draft_good = {"hook": "Corrected draft hook", "scenes": [{"scene_index": 0, "point": "p", "narration": "enough narration"}]}
        draft_text = '{"hook":"broken",]\nWait, corrected JSON follows.\n' + json.dumps(draft_good)
        draft_corrected = assert_ok(run_code_node(names["Parse Draft JSON"]["parameters"]["jsCode"], {
            "content": [{"type": "text", "text": draft_text}], "stop_reason": "end_turn"
        }), "draft self-correction")
        if draft_corrected.get("json", {}).get("draft", {}).get("hook") != "Corrected draft hook":
            die("draft parser did not choose the corrected JSON object")

        truncated = run_code_node(names["Parse Draft JSON"]["parameters"]["jsCode"], {
            "content": [{"type": "text", "text": '{"hook":"cut off"'}], "stop_reason": "max_tokens"
        })
        if truncated.get("ok") or "max_tokens" not in truncated.get("error", ""):
            die("draft max_tokens truncation is not diagnosed explicitly")

        final_script = good_script(sparse_queries=True)
        final_text = '{"hook":"bad",]\nSelf-correcting.\n' + json.dumps(final_script)
        validated = assert_ok(run_code_node(names["Validate Final Script"]["parameters"]["jsCode"], {
            "content": [{"type": "text", "text": final_text}], "stop_reason": "end_turn"
        }), "final validator self-correction")
        out = validated.get("json", {})
        if out.get("_scriptValid") is not True:
            die("publishable synthetic script failed validation: " + " | ".join(out.get("_validationErrors", [])))
        if any(len(s.get("search_queries", [])) < 3 for s in out.get("scenes", []) if s.get("visual_source") != "template"):
            die("visual schema normalizer failed to produce >=3 search queries")
        expected_full = " ".join(s["narration"] for s in final_script["scenes"])
        if out.get("full_script") != expected_full:
            die("full_script is not synchronized to final scene narration")

        below = good_script()
        below["quality"]["shareability"] = 70
        rejected = assert_ok(run_code_node(names["Validate Final Script"]["parameters"]["jsCode"], {
            "content": [{"type": "text", "text": json.dumps(below)}], "stop_reason": "end_turn"
        }), "quality gate fail-closed")
        if rejected.get("json", {}).get("_scriptValid") is not False:
            die("quality gate no longer fails closed for a real below-threshold score")

        compose_js = tmp / "compose.js"
        broll_js = tmp / "brollResolver.js"
        shutil.copy2(ROOT / "shorts-compose/compose.js", compose_js)
        shutil.copy2(ROOT / "shorts-compose/brollResolver.js", broll_js)
        run([sys.executable, str(ROOT / "scripts/upgrade-compose-creative-system.py"), str(compose_js)])
        run([sys.executable, str(ROOT / "scripts/upgrade-compose-api-budget.py"), str(compose_js), str(broll_js)])
        run([sys.executable, str(ROOT / "scripts/upgrade-compose-runtime-hardening.py"), str(broll_js)])
        run(["node", "--check", str(compose_js)])
        run(["node", "--check", str(broll_js)])
        broll = broll_js.read_text()
        for marker in ["PREPROD_BROLL_HARDENING", "RUN_MAX_VISION_CALLS", "scene_vision_budget_exhausted", "run_vision_budget_exhausted"]:
            if marker not in broll:
                die(f"transformed b-roll resolver missing {marker}")
        if "BROLL_RUN_MAX_VISION_CALLS || 18" in broll or "BROLL_RUN_MAX_VISION_CALLS || 28" not in broll:
            die("transformed b-roll resolver has inconsistent run budget default")

        start = broll.index("// PREPROD_BROLL_HARDENING: choose the last complete score object")
        end = broll.index("function clampScore", start)
        score_code = broll[start:end]
        score_harness = score_code + r'''
const p=parseScoreJson('{"overall":11,]\nWait\n{"relevance":91,"scroll_stop":90,"mobile_clarity":89,"composition":88,"motion_energy":87,"uniqueness":86,"overall":90}');
if(p.overall!==90)throw new Error('last valid score object did not win');
console.log('score recovery OK');
'''
        run(["node", "-e", score_harness])

        dc = (ROOT / "docker-compose.yml").read_text()
        def env_default(name: str) -> int:
            m = re.search(rf"{re.escape(name)}=\$\{{{re.escape(name)}:-(\d+)\}}", dc)
            if not m:
                die(f"docker-compose missing numeric default for {name}")
            return int(m.group(1))
        first = env_default("BROLL_FIRST_FRAME_MAX_VISION_CALLS")
        support = env_default("BROLL_SUPPORT_MAX_VISION_CALLS")
        run_cap = env_default("BROLL_RUN_MAX_VISION_CALLS")
        if run_cap < first + 7 * support:
            die(f"run vision cap {run_cap} is below valid 8-scene maximum {first + 7 * support}")

        quality_ci = (ROOT / ".github/workflows/quality-check.yml").read_text()
        for path in ["scripts/upgrade_quality_alignment.py", "scripts/upgrade-compose-runtime-hardening.py", "scripts/preprod-audit.py"]:
            if path not in quality_ci:
                die(f"quality-check path filters do not cover {path}")
        if "python3 scripts/preprod-audit.py" not in quality_ci:
            die("quality-check workflow does not execute the preprod audit")

        deploy = (ROOT / ".github/workflows/deploy.yml").read_text()
        if "python3 scripts/preprod-audit.py" not in deploy:
            die("production deploy does not rerun preprod audit before changing services/workflow")
        if "upgrade-compose-runtime-hardening.py" not in deploy:
            die("production deploy does not apply b-roll runtime hardening")

    print("PREPROD AUDIT PASSED: transform chain, parsers, validator, prompts, timeouts, retries, b-roll budgets, and CI/deploy wiring are consistent")


if __name__ == "__main__":
    try:
        audit()
    except Exception as exc:
        print(f"PREPROD AUDIT FAILED: {exc}", file=sys.stderr)
        raise
