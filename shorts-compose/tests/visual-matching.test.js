const { describe, it } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const {
  buildVisualContract,
  buildScoringTarget,
  classifyProofMode,
  shouldPreferTemplate,
  passesSemanticGate,
} = require("../visualContract");
const {
  cheapSemanticRank,
  normalizeRange,
  normalizeScore,
  normalizeVerifiedFrameIndices,
  verifiedRangeFromFrameIndices,
  compileQueries,
} = require("../brollResolver");
const {
  RUN_MAX_VISION_CALLS,
  FIRST_FRAME_MAX_VISION_CALLS,
  SUPPORT_BASE_VISION_CALLS,
  SUPPORT_BORROW_MAX_VISION_CALLS,
  getSceneLimit,
  reserveVisionCall,
  getBudgetState,
} = require("../visualBudget");
const { parseJsonObject: parseFinalQaJson } = require("../finalVisualQa");

describe("visual contract", () => {
  it("keeps the exact scene claim instead of collapsing to the named subject", () => {
    const c = buildVisualContract({
      subject: "octopus",
      narration: "An octopus can squeeze through a gap barely larger than its beak.",
      description: "octopus squeezing its body through a very narrow opening",
    });
    const target = buildScoringTarget(c);
    assert.match(target, /squeeze through a gap|squeezing its body/i);
    assert.match(target, /octopus/i);
    assert.notEqual(target.trim().toLowerCase(), "octopus");
  });

  it("infers visible actions and relationships only when explicit contracts are absent", () => {
    const c = buildVisualContract({
      subject: "octopus",
      narration: "An octopus is squeezing through a narrow opening.",
      description: "octopus squeezing through narrow opening",
    });
    assert.ok(c.required_actions.some((x) => /squeez/i.test(x)));
    assert.ok(c.required_relationships.length > 0);
    assert.equal(c.visual_proof_mode, "literal_video");
  });

  it("treats explicitly empty contract arrays as authoritative", () => {
    const c = buildVisualContract({
      subject: "octopus",
      visual_claim: "An octopus is squeezing through a narrow opening.",
      required_entities: ["octopus"],
      required_actions: [],
      required_relationships: [],
      visual_proof_mode: "literal_image",
    });
    assert.deepEqual(c.required_entities, ["octopus"]);
    assert.deepEqual(c.required_actions, []);
    assert.deepEqual(c.required_relationships, []);
    assert.equal(c.visual_proof_mode, "literal_image");
  });

  it("never augments explicit required entities with heuristic inventions", () => {
    const c = buildVisualContract({
      subject: "blue whale",
      visual_claim: "Show a blue whale beside a small boat while narration explains scale.",
      required_entities: ["blue whale", "small boat"],
      required_actions: [],
      required_relationships: ["blue whale and small boat visible together for scale"],
    });
    assert.deepEqual(c.required_entities, ["blue whale", "small boat"]);
  });

  it("uses the V4 literal_image enum for static literal proof", () => {
    const c = buildVisualContract({
      subject: "Eiffel Tower",
      visual_claim: "A clear real photograph of the Eiffel Tower",
      required_entities: ["Eiffel Tower"],
      required_actions: [],
      required_relationships: [],
    });
    assert.equal(c.visual_proof_mode, "literal_image");
  });

  it("routes pure scale/comparison facts toward designed proof modes", () => {
    const c = buildVisualContract({
      narration: "A blue whale heart can weigh as much as a small car.",
      description: "blue whale heart compared to small car",
    });
    assert.ok(["comparison", "annotated_real"].includes(classifyProofMode(c)));
    if (c.visual_proof_mode === "comparison") assert.equal(shouldPreferTemplate(c), true);
  });

  it("prefers every proof mode that has a deterministic renderer except verified-real", () => {
    for (const mode of ["number_visualization", "comparison", "kinetic_text", "map", "timeline", "diagram"]) {
      assert.equal(shouldPreferTemplate(buildVisualContract({ visual_claim: `show ${mode}`, visual_proof_mode: mode, required_entities: [], required_actions: [], required_relationships: [] })), true, mode);
    }
    assert.equal(shouldPreferTemplate(buildVisualContract({ visual_claim: "verify this real image", visual_proof_mode: "annotated_real", required_entities: [], required_actions: [], required_relationships: [] })), false);
  });

  it("treats semantic correctness as a hard gate", () => {
    const c = buildVisualContract({ subject: "octopus", description: "octopus squeezing through a narrow opening" });
    const flashyButWrong = { semantic_match: 68, entity_match: 96, action_match: 42, relationship_match: 30, overall: 97 };
    assert.equal(passesSemanticGate(flashyButWrong, c), false);
  });

  it("accepts a candidate that satisfies entities, action and relationship", () => {
    const c = buildVisualContract({ subject: "octopus", description: "octopus squeezing through a narrow opening" });
    const correct = { semantic_match: 94, entity_match: 95, action_match: 92, relationship_match: 90, overall: 88 };
    assert.equal(passesSemanticGate(correct, c), true);
  });
});

describe("query compilation", () => {
  it("searches the exact visual claim instead of relying only on upstream keywords", () => {
    const c = buildVisualContract({
      subject: "octopus",
      visual_claim: "octopus squeezing through a narrow rock opening",
      required_entities: ["octopus", "rock opening"],
      required_actions: ["squeezing"],
      required_relationships: ["octopus passing through rock opening"],
      visual_proof_mode: "literal_video",
    });
    const q = compileQueries({ query: "octopus", queries: ["octopus underwater"] }, c);
    assert.ok(q.includes(c.visual_claim));
    assert.ok(q.some((x) => /octopus squeezing/i.test(x)));
  });
});

describe("candidate ranking", () => {
  it("ranks a scene-specific candidate above generic broad-topic filler", () => {
    const contract = buildVisualContract({ subject: "octopus", description: "octopus squeezing through narrow rock opening" });
    const exact = { type: "video", alt: "octopus squeezing through narrow rock opening", query: "octopus narrow opening", width: 1080, height: 1920 };
    const generic = { type: "video", alt: "octopus swimming underwater", query: "octopus", width: 1080, height: 1920 };
    assert.ok(cheapSemanticRank(exact, contract) > cheapSemanticRank(generic, contract));
  });

  it("caps overall score when semantic/entity match is weak", () => {
    const score = normalizeScore({ semantic_match: 45, entity_match: 52, action_match: 99, relationship_match: 99, overall: 99, scroll_stop: 99, mobile_clarity: 99 }, { type: "image" });
    assert.ok(score.overall <= 53);
  });
});

describe("adaptive paid-vision budget", () => {
  it("keeps the production hard ceiling while aligning defaults with the deployment policy", () => {
    assert.equal(RUN_MAX_VISION_CALLS, 28);
    assert.equal(FIRST_FRAME_MAX_VISION_CALLS, 7);
    assert.equal(SUPPORT_BASE_VISION_CALLS, 3);
    assert.equal(SUPPORT_BORROW_MAX_VISION_CALLS, 7);
  });

  it("lets a support scene borrow spare budget on a normal four-retrieval-scene Short", () => {
    const runId = `budget-four-${Date.now()}-${Math.random()}`;
    const first = { used: 0, limit: FIRST_FRAME_MAX_VISION_CALLS };
    for (let i = 0; i < FIRST_FRAME_MAX_VISION_CALLS; i++) assert.equal(reserveVisionCall(runId, first).allowed, true);
    assert.equal(getSceneLimit(false, { runId, retrievalSceneCount: 4, retrievalScenePosition: 1 }), 7);
  });

  it("preserves the three-call reserve when all eight retrieval scenes need vision", () => {
    const runId = `budget-eight-${Date.now()}-${Math.random()}`;
    const first = { used: 0, limit: FIRST_FRAME_MAX_VISION_CALLS };
    for (let i = 0; i < FIRST_FRAME_MAX_VISION_CALLS; i++) assert.equal(reserveVisionCall(runId, first).allowed, true);
    assert.equal(getSceneLimit(false, { runId, retrievalSceneCount: 8, retrievalScenePosition: 1 }), 3);
  });

  it("reclaims unused first-frame budget for a later hard scene without exceeding 28 calls", () => {
    const runId = `budget-reclaim-${Date.now()}-${Math.random()}`;
    const first = { used: 0, limit: FIRST_FRAME_MAX_VISION_CALLS };
    for (let i = 0; i < 2; i++) assert.equal(reserveVisionCall(runId, first).allowed, true);
    assert.equal(getSceneLimit(false, { runId, retrievalSceneCount: 8, retrievalScenePosition: 1 }), 7);
    const state = getBudgetState(runId, first);
    assert.equal(state.run_used, 2);
    assert.equal(state.run_remaining, 26);
  });

  it("falls back to the conservative support reserve when topology is unavailable", () => {
    assert.equal(getSceneLimit(false, {}), SUPPORT_BASE_VISION_CALLS);
  });
});

describe("verified-real proof", () => {
  it("does not generate or normalize audience-facing annotation geometry", () => {
    const resolverSource = fs.readFileSync(path.join(__dirname, "..", "brollResolver.js"), "utf8");
    assert.doesNotMatch(resolverSource, /normalizeAnnotationPlan/);
    assert.doesNotMatch(resolverSource, /annotation_plan/);
    assert.doesNotMatch(resolverSource, /annotations as an array/i);
    assert.match(resolverSource, /verified_image_/);
  });
});

describe("verified trim ranges", () => {
  it("normalizes malformed or out-of-bounds legacy ranges", () => {
    assert.deepEqual(normalizeRange(-2, 200, 10), { start: 0, end: 10 });
  });

  it("rejects non-contiguous frame selections", () => {
    assert.deepEqual(normalizeVerifiedFrameIndices([2, 4], 6), []);
    assert.deepEqual(normalizeVerifiedFrameIndices([4, 3, 3, 2], 6), [2, 3, 4]);
  });

  it("derives trim boundaries only from selected sampled-frame bins", () => {
    const timestamps = [0.5, 1.5, 2.5, 3.5, 4.5];
    const r = verifiedRangeFromFrameIndices([1, 2], timestamps, 5);
    assert.deepEqual(r, { start: 1, end: 3, indices: [1, 2] });
  });

  it("fails closed when no sampled frames are explicitly verified", () => {
    assert.equal(verifiedRangeFromFrameIndices([], [0.5, 1.5], 2), null);
  });
});

describe("final rendered QA response parsing", () => {
  it("rejects malformed non-JSON model output instead of inventing a score", () => {
    assert.equal(parseFinalQaJson("not json at all"), null);
  });

  it("parses a bounded JSON object from model output", () => {
    const parsed = parseFinalQaJson('{"semantic_match":91,"overall":88}');
    assert.equal(parsed.semantic_match, 91);
    assert.equal(parsed.overall, 88);
  });
});
