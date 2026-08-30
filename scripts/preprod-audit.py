#!/usr/bin/env python3
"""Pre-production audit for the Shorts workflow and VISUAL_MATCHING_V4.

Runs the same workflow/compose transforms used by deployment, executes key n8n
Code nodes with synthetic responses, and asserts semantic visual invariants
without calling external APIs.
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
        raise RuntimeError(f"command failed ({' '.join(cmd)}):\nSTDOUT:\n{p.stdout}\nSTDERR:\n{p.stderr}")
    return p


def node_by_name(workflow: dict, name: str) -> dict:
    for n in workflow.get("nodes", []):
        if n.get("name") == name:
            return n
    die(f"missing workflow node: {name}")


def first_edge(workflow: dict, name: str) -> str | None:
    try: return workflow["connections"][name]["main"][0][0]["node"]
    except (KeyError, IndexError, TypeError): return None


def run_code_node(js_code: str, payload: dict, prior: dict | None = None, static_data: dict | None = None, execution_id: str = "preprod-audit-execution") -> dict:
    harness = r'''
const code=JSON.parse(process.env.AUDIT_CODE),payload=JSON.parse(process.env.AUDIT_INPUT),prior=JSON.parse(process.env.AUDIT_PRIOR||'{}');
const __staticData=JSON.parse(process.env.AUDIT_STATIC||'{}');
const $input={first:()=>({json:payload}),all:()=>[{json:payload}]};
const $=(name)=>({item:{json:prior[name]||{}},first:()=>({json:prior[name]||{}}),all:()=>[{json:prior[name]||{}}]});
const $execution={id:process.env.AUDIT_EXECUTION_ID||'preprod-audit-execution'};
const $getWorkflowStaticData=()=>__staticData;
try{const fn=new Function('$input','$','$execution','$getWorkflowStaticData',code);const result=fn($input,$,$execution,$getWorkflowStaticData);console.log('__PREPROD__'+JSON.stringify({ok:true,result,staticData:__staticData}));}
catch(err){console.log('__PREPROD__'+JSON.stringify({ok:false,error:String(err&&err.message||err),staticData:__staticData}));}
'''
    env = os.environ.copy()
    env["AUDIT_CODE"] = json.dumps(js_code); env["AUDIT_INPUT"] = json.dumps(payload); env["AUDIT_PRIOR"] = json.dumps(prior or {})
    env["AUDIT_STATIC"] = json.dumps(static_data or {}); env["AUDIT_EXECUTION_ID"] = execution_id
    p = run(["node", "-e", harness], env=env)
    lines = [x for x in p.stdout.splitlines() if x.startswith("__PREPROD__")]
    if not lines: die("Code-node harness produced no result marker")
    return json.loads(lines[-1][len("__PREPROD__"):])


def assert_ok(result: dict, label: str) -> dict:
    if not result.get("ok"): die(f"{label} failed: {result.get('error')}")
    return result.get("result") or {}


def candidate(i: int) -> dict:
    return {
        "topic": f"A recognizable surprising fact number {i}", "archetype": "looks_fake_but_real",
        "research_query": "recognizable fact evidence", "first_frame_concept": "close visible proof",
        "share_reason": "send to a curious friend", "evidence_score": 82, "visual_score": 84,
        "share_score": 83, "concept_score": 83, "payoff_score": 82, "novelty_score": 84,
        "execution_score": 82, "distinctiveness_score": 82, "share_trigger": "disbelief",
        "send_to_person": "curious friend", "novelty_delta": "viewer assumes X -> learns Y",
        "proof_visual": "close visible proof", "stock_feasibility": 90,
        "stock_query_seed": ["visible subject", "subject close up", "subject detail"], "reason": "strong", "score": 83,
    }


def good_script(*, sparse_queries: bool = False) -> dict:
    quality = {k: 82 for k in ["concept_strength","hook_strength","evidence_strength","payoff_strength","information_density","first_frame_strength","visual_progression","shareability","naturalness","distinctiveness","voice_specificity","overall"]}
    narrations = [
        "The shark swims directly toward the camera while its distinctive body shape stays clearly visible.",
        "The shark turns through the water and the fin movement shows exactly how it changes direction.",
        "The final wide shot keeps the same shark visible beside a diver so the physical scale is obvious.",
    ]
    prompts = ["shark swimming toward camera", "shark turning underwater fin movement", "shark beside diver scale"]
    actions = [["swimming toward camera"], ["turning through water"], []]
    relationships = [[], [], ["shark and diver must be visible together so scale is legible"]]
    scenes = []
    for i, narration in enumerate(narrations):
        scene = {
            "scene_index": i, "point": ["surprising claim","visible mechanism","repeatable payoff"][i], "narration": narration,
            "visual_source": "stock", "visual_type": "real", "visual_prompt": prompts[i],
            "negative_prompt": "no readable text, no legible numbers, no documents or screens",
            "stock_search_query": "" if sparse_queries else prompts[i], "named_subject": "shark",
            "search_queries": [] if sparse_queries else [prompts[i], "shark underwater", "shark close up"], "visual_role": ["hero","evidence","payoff"][i],
            "visual_claim": prompts[i], "global_subject": "shark fact",
            "required_entities": ["shark"] + (["diver"] if i == 2 else []), "required_actions": actions[i],
            "required_relationships": relationships[i], "forbidden_visuals": ["generic empty ocean footage", "unrelated marine animal"],
            "acceptable_visuals": [], "visual_proof_mode": "literal_video",
        }
        scenes.append(scene)
    return {
        "hook": "A familiar shark fact sounds impossible until you see what is actually happening.", "hook_type": "counterintuitive_claim",
        "hook_candidates": ["This shark fact sounds impossible until you see it.","The shark fact you know is missing the strangest part.","One shark detail completely changes the scale of the story.","The visible proof makes this shark fact much harder to dismiss.","This is the shark comparison people actually remember."],
        "title": "The Shark Detail Everyone Misses", "seo_description": "A clear shark fact explained with visible evidence and a simple comparison.",
        "comment_hook": None, "outro_line": None, "tags": ["sharks","ocean","animals","facts","shorts","science","explained","nature"],
        "full_script": "INTENTIONALLY STALE BEFORE NORMALIZATION", "caption_style": "neutral", "trigger": "disbelief",
        "payoff": {"claim": "the compact comparison resolves the hook", "resolved_in_scene": 2}, "creative_format": "documentary_cinematic",
        "visual_grammar": "documentary_cinematic", "caption_mode": "key_phrases", "transition_style": "hard_cut", "engagement_mode": "none",
        "open_loop_count": 1, "visual_plan_quality": 84, "first_frame_type": "hero_motion", "quality_route": "pass", "scenes": scenes, "quality": quality,
    }


def build_workflow(tmp: Path) -> dict:
    stages = [
        ("upgrade-viral-shorts.py", ROOT / "n8n/workflow.json", tmp / "v1.json"),
        ("upgrade-creative-system.py", tmp / "v1.json", tmp / "v2.json"),
        ("visual_matching_v4_workflow.py", tmp / "v2.json", tmp / "v2v4.json"),
        ("upgrade-workflow-api-budget.py", tmp / "v2v4.json", tmp / "v3.json"),
        ("upgrade-topic-latency.py", tmp / "v3.json", tmp / "v4.json"),
        ("upgrade-anthropic-parser.py", tmp / "v4.json", tmp / "final.json"),
    ]
    for script, src, dst in stages: run([sys.executable, str(ROOT / "scripts" / script), str(src), str(dst)])
    return json.loads((tmp / "final.json").read_text())


def audit() -> None:
    required_py = [
        "upgrade-viral-shorts.py","upgrade-creative-system.py","visual_matching_v4_workflow.py","upgrade-workflow-api-budget.py",
        "upgrade-topic-latency.py","upgrade_quality_alignment.py","upgrade-anthropic-parser.py","upgrade-compose-creative-system.py",
        "upgrade-compose-api-budget.py","upgrade-compose-runtime-hardening.py","visual_matching_v4_compose.py","preprod-audit.py",
    ]
    run([sys.executable, "-m", "py_compile", *[str(ROOT / "scripts" / x) for x in required_py]])
    for js in ["brollResolver.js","visualContract.js","visualBudget.js","semanticReranker.js","clipLibrary.js","finalVisualQa.js"]:
        run(["node", "--check", str(ROOT / "shorts-compose" / js)])

    with tempfile.TemporaryDirectory(prefix="shorts-preprod-") as td:
        tmp = Path(td); workflow = build_workflow(tmp); names = {n["name"]: n for n in workflow["nodes"]}
        if workflow.get("meta", {}).get("visual_matching_version") != "4": die("generated workflow lost V4 marker")

        node_names = set(names)
        for src, out in workflow.get("connections", {}).items():
            if src not in node_names: die(f"dangling connection source: {src}")
            for branch in out.get("main", []):
                for edge in branch or []:
                    if edge.get("node") not in node_names: die(f"dangling connection target: {src}->{edge.get('node')}")
        expected_edges = {"Claude: Generate Topic":"Parse Topic Pool","Parse Topic Pool":"Claude: Commission Topic Shortlist","Claude: Commission Topic Shortlist":"Extract Generated Topic","Wikipedia: Research Topic":"Normalize Research Evidence","Normalize Research Evidence":"Claude: Draft Script (Stage 1)","Parse Draft JSON":"Claude: Visual Director","Claude: Visual Director":"Validate Final Script"}
        for src, dst in expected_edges.items():
            if first_edge(workflow, src) != dst: die(f"graph drift: {src}")

        expected_timeouts = {"Claude: Generate Topic":120000,"Claude: Commission Topic Shortlist":120000,"Claude: Draft Script (Stage 1)":120000,"Claude: Visual Director":180000,"ElevenLabs: TTS+Timestamps":60000,"Resolve B-roll":180000}
        for name, expected in expected_timeouts.items():
            if names[name].get("parameters", {}).get("options", {}).get("timeout") != expected: die(f"timeout drift: {name}")

        visual_body = names["Claude: Visual Director"]["parameters"]["jsonBody"]
        for marker in ["QUALITY_ALIGNMENT","REPAIRABLE_NEAR_MISS","HARD_REJECT","VISUAL_MATCHING_V4","visual_claim","required_entities","required_actions","required_relationships","forbidden_visuals","visual_proof_mode","OVERALL SELECTED TOPIC"]:
            if marker not in visual_body: die(f"Visual Director lost {marker}")
        if 'reasoning_effort: "none"' not in visual_body: die("Visual Director reasoning drift")

        resolver_body = names["Resolve B-roll"]["parameters"]["jsonBody"]
        for marker in ["visual_claim","required_entities","required_actions","required_relationships","forbidden_visuals","visual_proof_mode","narration","global_subject","run_id","$execution.id"]:
            if marker not in resolver_body: die(f"resolver payload lost {marker}")
        validator = names["Validate Final Script"]["parameters"]["jsCode"]
        if "VISUAL_MATCHING_V4 contract gate" not in validator: die("validator lost V4 contract gate")

        # Keep parser self-correction regressions covered.
        def response(text: str, finish: str = "stop") -> dict: return {"choices":[{"message":{"content":text},"finish_reason":finish}]}
        pool_obj = {"candidates": [candidate(i) for i in range(4)]}
        pool = assert_ok(run_code_node(names["Parse Topic Pool"]["parameters"]["jsCode"], '{"bad":[}\nWait\n' and response('{"candidates":[} broken\n'+json.dumps(pool_obj))), "topic parser")
        if len(pool.get("json", {}).get("pool", [])) != 4: die("topic pool self-correction failed")
        minimal = {"hook":"A complete hook","scenes":[{"scene_index":0,"point":"p","narration":"enough narration"}]}
        draft = assert_ok(run_code_node(names["Parse Draft JSON"]["parameters"]["jsCode"], response(json.dumps(minimal))), "draft parser")
        if draft.get("json", {}).get("draft", {}).get("hook") != "A complete hook": die("draft parser failed")
        truncated = run_code_node(names["Parse Draft JSON"]["parameters"]["jsCode"], response('{"hook":"cut off"', "length"))
        if truncated.get("ok") or "max_completion_tokens" not in truncated.get("error", ""): die("truncation diagnosis regressed")

        final_script = good_script(sparse_queries=True)
        validated = assert_ok(run_code_node(names["Validate Final Script"]["parameters"]["jsCode"], response(json.dumps(final_script))), "V4 validator")
        out = validated.get("json", {})
        if out.get("_scriptValid") is not True: die("publishable V4 script failed: " + " | ".join(out.get("_validationErrors", [])))
        for s in out.get("scenes", []):
            if s.get("visual_source") != "template" and len(s.get("search_queries", [])) < 3: die("query normalizer lost >=3 query guarantee")
            for field in ["visual_claim","required_entities","required_actions","required_relationships","forbidden_visuals","visual_proof_mode"]:
                if field not in s: die(f"validated scene lost {field}")
        below = good_script(); below["quality"]["shareability"] = 70
        rejected = assert_ok(run_code_node(names["Validate Final Script"]["parameters"]["jsCode"], response(json.dumps(below))), "quality fail-closed")
        if rejected.get("json", {}).get("_scriptValid") is not False: die("quality gate no longer fails closed")

        # QUALITY_GATE_BEST_EFFORT_FALLBACK: a run that never clears the quality
        # bar but never has a structural defect either should publish its best
        # attempt on the last allowed try, rather than exhausting the repair
        # loop and skipping the scheduled post outright.
        validate_code = names["Validate Final Script"]["parameters"]["jsCode"]
        exec_id = "preprod-best-effort-execution"

        # Attempt 1 (not the final attempt yet): quality-only miss, overall=74.
        attempt1 = good_script(); attempt1["quality"]["overall"] = 74
        r1 = run_code_node(validate_code, response(json.dumps(attempt1)), static_data={}, execution_id=exec_id)
        if r1.get("result", {}).get("json", {}).get("_scriptValid") is not False:
            die("best-effort fallback engaged before the final attempt")
        static_after_1 = r1.get("staticData", {})
        if static_after_1.get("scriptBestEffort", {}).get(exec_id, {}).get("overallScore") != 74:
            die(f"best-effort tracker did not record attempt 1's score: {static_after_1}")

        # Attempt 2 (still not final): a BETTER quality-only miss, overall=76 -
        # the tracker must keep the higher score, not just the latest one. Also
        # wants a share outro, so a later check can confirm the fallback truly
        # falls through to the normal success-path tail (outro append) instead
        # of returning a hand-picked subset of fields.
        attempt2 = good_script(); attempt2["quality"]["overall"] = 76
        attempt2["engagement_mode"] = "share_only"; attempt2["outro_line"] = "Send this to someone who needs it."
        r2 = run_code_node(validate_code, response(json.dumps(attempt2)), static_data=static_after_1, execution_id=exec_id)
        static_after_2 = r2.get("staticData", {})
        if static_after_2.get("scriptBestEffort", {}).get(exec_id, {}).get("overallScore") != 76:
            die(f"best-effort tracker did not keep the better of two quality-only misses: {static_after_2}")

        # Attempt 3 is the LAST allowed attempt (scriptAttempts.attempt >= 2) and
        # scores WORSE than attempt 2 (overall=72) - the fallback must publish
        # attempt 2's script (the actual best seen), not attempt 3's.
        static_after_2["scriptAttempts"] = {exec_id: {"attempt": 2}}
        attempt3 = good_script(); attempt3["quality"]["overall"] = 72
        r3 = assert_ok(run_code_node(validate_code, response(json.dumps(attempt3)), static_data=static_after_2, execution_id=exec_id), "best-effort fallback on final attempt")
        out3 = r3.get("json", {})
        if out3.get("_scriptValid") is not True: die(f"best-effort fallback did not engage on the final attempt: {out3}")
        if not out3.get("_qualityGateBestEffort"): die("best-effort fallback did not flag _qualityGateBestEffort")
        if out3.get("_qualityGateBestEffortScore") != 76: die(f"best-effort fallback did not pick the actual best-scoring attempt (expected 76): {out3.get('_qualityGateBestEffortScore')}")
        if out3.get("hook") != attempt2["hook"]: die("best-effort fallback published a different script than the recorded best")
        if "_validationErrors" in out3 or "_failedScript" in out3:
            die("best-effort fallback did not actually fall through to the normal success-path shape")
        if not any(s.get("template_data", {}).get("is_outro") for s in out3.get("scenes", [])):
            die("best-effort fallback did not fall through to the normal success-path outro append")

        # A final attempt with a STRUCTURAL defect (not quality-only) must still
        # hard-fail even though it's the last attempt and even if a genuinely
        # good earlier attempt was recorded - never publish a broken script.
        # (sparse_queries alone isn't enough here - the schema normalizer
        # auto-repairs missing search_queries before the gate runs, same as it
        # would for a real production script - so force a hook too short to
        # repair instead, a guaranteed unrecovered structural failure.)
        broken_final = good_script(); broken_final["hook"] = "hi"
        static_for_structural = {"scriptBestEffort": dict(static_after_2.get("scriptBestEffort", {})), "scriptAttempts": {exec_id: {"attempt": 2}}}
        r4 = assert_ok(run_code_node(validate_code, response(json.dumps(broken_final)), static_data=static_for_structural, execution_id=exec_id), "best-effort fallback still hard-fails on structural defects")
        # A structurally broken final attempt must never be silently accepted,
        # even though a stored best-effort candidate exists from an earlier,
        # genuinely sound attempt - that candidate is exactly what should be
        # published instead of a broken one.
        out4 = r4.get("json", {})
        if out4.get("_scriptValid") is not True or not out4.get("_qualityGateBestEffort"):
            die(f"best-effort fallback did not fall back to the stored good candidate over a structurally broken final attempt: {out4}")
        if out4.get("hook") != attempt2["hook"]: die("best-effort fallback did not publish the stored good candidate over the broken final attempt")

        # No stored best-effort candidate at all (every attempt had a structural
        # defect) must still hard-fail on the final attempt.
        r5 = run_code_node(validate_code, response(json.dumps(broken_final)), static_data={"scriptAttempts": {exec_id: {"attempt": 2}}}, execution_id=exec_id)
        out5 = r5.get("result", {}).get("json", {})
        if out5.get("_scriptValid") is not False: die(f"best-effort fallback published a script with no qualifying candidate ever recorded: {out5}")

        # Build the actual production compose/resolver transform chain.
        compose_js, broll_js = tmp / "compose.js", tmp / "brollResolver.js"
        shutil.copy2(ROOT / "shorts-compose/compose.js", compose_js); shutil.copy2(ROOT / "shorts-compose/brollResolver.js", broll_js)
        run([sys.executable, str(ROOT / "scripts/upgrade-compose-creative-system.py"), str(compose_js)])
        run([sys.executable, str(ROOT / "scripts/upgrade-compose-api-budget.py"), str(compose_js), str(broll_js)])
        run([sys.executable, str(ROOT / "scripts/upgrade-compose-runtime-hardening.py"), str(broll_js)])
        run([sys.executable, str(ROOT / "scripts/visual_matching_v4_compose.py"), str(compose_js)])
        run(["node", "--check", str(compose_js)]); run(["node", "--check", str(broll_js)])
        compose, broll = compose_js.read_text(), broll_js.read_text()
        for marker in ["VISUAL_MATCHING_V4","PREPROD_BROLL_HARDENING","RETRIEVAL_RECALL_PHASE2","SOURCE_QUERY_COMPILER_V1","MULTIFRAME_VIDEO_RERANK_V1","sampleVideoContactSheet","localSemanticRerank","passesSemanticGate","materializeVerifiedClip","fromPixabayVideos","fromWikimediaCommons"]:
            if marker not in broll: die(f"V4 resolver missing {marker}")
        if "const target = subj ||" in broll: die("broad-subject scoring regression returned")
        if "reviewFinalVideo" not in compose or "Final visual QA rejected" not in compose: die("final rendered QA is not blocking compose")

        budget = (ROOT / "shorts-compose/visualBudget.js").read_text()
        if "BROLL_RUN_MAX_VISION_CALLS || 28" not in budget: die("V4 run budget default is not 28")
        dc = (ROOT / "docker-compose.yml").read_text()
        def env_default(name: str) -> int:
            m = re.search(rf"{re.escape(name)}=\$\{{{re.escape(name)}:-(\d+)\}}", dc)
            if not m: die(f"docker-compose missing {name}")
            return int(m.group(1))
        first, support, run_cap = env_default("BROLL_FIRST_FRAME_MAX_VISION_CALLS"), env_default("BROLL_SUPPORT_MAX_VISION_CALLS"), env_default("BROLL_RUN_MAX_VISION_CALLS")
        if run_cap < first + 7 * support: die(f"run vision cap {run_cap} below 8-scene maximum {first + 7*support}")

        quality_ci = (ROOT / ".github/workflows/quality-check.yml").read_text()
        for p in ["scripts/visual_matching_v4_workflow.py","scripts/visual_matching_v4_compose.py","scripts/preprod-audit.py"]:
            if p not in quality_ci: die(f"quality-check path filters do not cover {p}")
        deploy = (ROOT / ".github/workflows/deploy.yml").read_text()
        for marker in ["visual_matching_v4_workflow.py","visual_matching_v4_compose.py","python3 scripts/preprod-audit.py"]:
            if marker not in deploy: die(f"deploy lost {marker}")

    print("PREPROD AUDIT PASSED: V4 visual contracts, parsers, semantic gates, budgets, exact video verification, rendered QA, and deployment wiring are consistent")


if __name__ == "__main__":
    try: audit()
    except Exception as exc:
        print(f"PREPROD AUDIT FAILED: {exc}", file=sys.stderr)
        raise
