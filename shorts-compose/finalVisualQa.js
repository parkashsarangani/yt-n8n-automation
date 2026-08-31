// Final multimodal QA: inspect representative pixels from the completed Short
// and verify scene-to-script correspondence before publication can proceed.
const fs = require("fs");
const fsp = fs.promises;
const path = require("path");
const os = require("os");
const crypto = require("crypto");
const axios = require("axios");
const { execFile } = require("child_process");
const ffmpegPath = require("ffmpeg-static");
const { buildVisualContract, buildScoringTarget, passesSemanticGate } = require("./visualContract");

const OPENAI_KEY = process.env.OPENAI_KEY || "";
const MODEL = process.env.BROLL_FINAL_QA_MODEL || process.env.BROLL_VISION_MODEL || "gpt-5.6-luna";
const ENABLED = String(process.env.BROLL_FINAL_QA_ENABLED || "true").toLowerCase() !== "false";
const REQUIRE_KEY = String(process.env.BROLL_FINAL_QA_REQUIRE_KEY || "true").toLowerCase() !== "false";
const MIN_SCORE = Math.max(0, Math.min(100, Number(process.env.BROLL_FINAL_QA_MIN_SCORE || 78)));
const SAMPLE_COUNT = Math.max(1, Math.min(5, Number(process.env.BROLL_FINAL_QA_SAMPLE_FRAMES || 3)));

function run(args) {
  return new Promise((resolve, reject) => {
    execFile(ffmpegPath, args, { timeout: 90000, maxBuffer: 4 * 1024 * 1024 }, (err) => err ? reject(err) : resolve());
  });
}

async function sampleSceneContactSheet(videoPath, sceneStartSec, sceneDurationSec) {
  const duration = Math.max(0.2, Number(sceneDurationSec || 0));
  const out = path.join(os.tmpdir(), `finalqa-${crypto.randomUUID()}.jpg`);
  const fractions = SAMPLE_COUNT === 1 ? [0.5] : Array.from({ length: SAMPLE_COUNT }, (_, i) => 0.2 + (0.6 * i / (SAMPLE_COUNT - 1)));
  const times = fractions.map((f) => Number((Math.max(0, sceneStartSec) + Math.max(0.05, duration * f)).toFixed(3)));
  const frames = [];
  try {
    for (let i = 0; i < times.length; i++) {
      const framePath = `${out}.${i}.jpg`;
      await run(["-hide_banner", "-loglevel", "error", "-y", "-ss", String(times[i]), "-i", videoPath, "-frames:v", "1", "-vf", "scale=420:360:force_original_aspect_ratio=decrease,pad=420:360:(ow-iw)/2:(oh-ih)/2:color=black", "-q:v", "3", framePath]);
      frames.push(framePath);
    }
    if (!frames.length) return null;
    if (frames.length === 1) {
      const buf = await fsp.readFile(frames[0]);
      return { imageUrl: `data:image/jpeg;base64,${buf.toString("base64")}`, timestamps: times };
    }
    await run(["-hide_banner", "-loglevel", "error", "-y", ...frames.flatMap((p) => ["-i", p]), "-filter_complex", `${frames.map((_, i) => `[${i}:v]`).join("")}hstack=inputs=${frames.length}`, "-frames:v", "1", "-q:v", "3", out]);
    const buf = await fsp.readFile(out);
    return { imageUrl: `data:image/jpeg;base64,${buf.toString("base64")}`, timestamps: times };
  } catch {
    return null;
  } finally {
    await Promise.all([...frames, out].map((p) => fsp.unlink(p).catch(() => {})));
  }
}

function parseJsonObject(text) {
  const raw = String(text || "").trim();
  const a = raw.indexOf("{"), b = raw.lastIndexOf("}");
  if (a < 0 || b <= a) return null;
  try { return JSON.parse(raw.slice(a, b + 1)); } catch { return null; }
}

async function judgeScene(imageUrl, contract, timestamps) {
  if (!OPENAI_KEY || !imageUrl) return null;
  const prompt = [
    "Judge whether these chronological RENDERED frames from ONE scene in a YouTube Short visibly support the exact narration beat.",
    `Visual contract: ${buildScoringTarget(contract)}`,
    `Frame timestamps: ${(timestamps || []).join(", ")} seconds.`,
    `Forbidden visuals: ${(contract.forbidden_visuals || []).join("; ")}`,
    "Judge the scene across the sampled frames; an action may occur in one frame while entities/relationship remain visible in another.",
    "Score each field 0-100 from your actual visual judgment of the image - never copy a placeholder or example value verbatim.",
    "Return ONLY JSON with these exact keys, each holding a real integer 0-100 you computed (or an empty string for problem if none): {\"semantic_match\":<int>,\"entity_match\":<int>,\"action_match\":<int>,\"relationship_match\":<int>,\"readability\":<int>,\"overall\":<int>,\"problem\":\"<string>\"}.",
    contract.is_deterministic_template
      ? "This scene is a designed text/graphic card, not a photo or video - it never contains a photographic entity, action, or relationship. Set entity_match, action_match, and relationship_match to null (they do not apply). Base overall ONLY on legibility and topical fit with the claim - do NOT lower overall because a photographic subject is absent, that is expected and correct for this scene type."
      : "Do not reward generic topic relevance. If a required entity, action, or relationship is absent from all sampled frames, score that dimension below 70.",
  ].join(" ");
  try {
    const r = await axios.post("https://api.openai.com/v1/chat/completions", {
      model: MODEL,
      max_completion_tokens: 280,
      reasoning_effort: "none",
      response_format: { type: "json_object" },
      messages: [{ role: "user", content: [
        { type: "image_url", image_url: { url: imageUrl } },
        { type: "text", text: prompt },
      ] }],
    }, { timeout: 45000, headers: { Authorization: `Bearer ${OPENAI_KEY}`, "content-type": "application/json" } });
    return parseJsonObject(r.data?.choices?.[0]?.message?.content || "");
  } catch {
    return null;
  }
}

async function reviewFinalVideo(videoPath, scenes, durations) {
  if (!ENABLED) return { enabled: false, passed: true, issues: [] };
  if (!OPENAI_KEY) {
    return REQUIRE_KEY
      ? { enabled: true, passed: false, checked: 0, issues: [{ problem: "final_visual_qa_missing_openai_key" }] }
      : { enabled: true, passed: true, checked: 0, skipped: "missing_openai_key", issues: [] };
  }
  if (!fs.existsSync(videoPath)) return { enabled: true, passed: false, checked: 0, issues: [{ problem: "final_video_missing" }] };

  let offset = 0;
  const issues = [];
  const results = [];
  for (let i = 0; i < scenes.length; i++) {
    const scene = scenes[i];
    const duration = Math.max(0, Number(durations[i] || 0));
    const sceneStart = offset;
    offset += duration;
    if (scene?.template_data?.is_outro) continue;
    const sceneIndex = scene?.scene_index ?? i;
    const contract = buildVisualContract({
      scene_index: sceneIndex,
      narration: scene?.narration || scene?.point || "",
      subject: scene?.named_subject || "",
      global_subject: scene?.global_subject || "",
      description: scene?.visual_claim || scene?.visual_prompt || scene?.selected_query || "",
      visual_claim: scene?.visual_claim,
      required_entities: scene?.required_entities,
      required_actions: scene?.required_actions,
      required_relationships: scene?.required_relationships,
      forbidden_visuals: scene?.forbidden_visuals,
      acceptable_visuals: scene?.acceptable_visuals,
      visual_proof_mode: scene?.visual_proof_mode,
      template_name: scene?.template_name,
      template_data: scene?.template_data,
    });

    const sheet = await sampleSceneContactSheet(videoPath, sceneStart, duration);
    if (!sheet) {
      issues.push({ scene_index: sceneIndex, problem: "final_visual_qa_frame_sampling_failed" });
      continue;
    }
    const score = await judgeScene(sheet.imageUrl, contract, sheet.timestamps);
    if (!score) {
      issues.push({ scene_index: sceneIndex, problem: "final_visual_qa_model_failed" });
      continue;
    }
    const normalized = {
      semantic_match: Number(score.semantic_match || 0),
      entity_match: Number(score.entity_match || 0),
      action_match: Number(score.action_match || 0),
      relationship_match: Number(score.relationship_match || 0),
      readability: Number(score.readability || 0),
      overall: Number(score.overall || 0),
      problem: String(score.problem || ""),
    };
    results.push({ scene_index: sceneIndex, timestamps: sheet.timestamps, ...normalized });
    const semanticOk = passesSemanticGate(normalized, contract, {
      semantic: MIN_SCORE,
      entity: Math.max(MIN_SCORE, 80),
      action: MIN_SCORE,
      relationship: MIN_SCORE,
    });
    // The model's own "overall" field is a holistic judgment that still
    // factors in the absence of a photographic entity/action/relationship,
    // even when told not to (a designed text/graphic card structurally
    // cannot show one - see visualContract.js). For a deterministic
    // template scene, judge on semantic_match (legibility + topical fit)
    // instead of trusting an "overall" the model penalizes for something
    // this scene type was never going to show.
    const effectiveScore = contract.is_deterministic_template ? normalized.semantic_match : normalized.overall;
    if (!semanticOk || effectiveScore < MIN_SCORE || normalized.readability < 65) {
      issues.push({
        scene_index: sceneIndex,
        problem: normalized.problem || "rendered visual does not satisfy the scene visual contract",
        score: effectiveScore,
        semantic_match: normalized.semantic_match,
        entity_match: normalized.entity_match,
        action_match: normalized.action_match,
        relationship_match: normalized.relationship_match,
      });
    }
  }

  const contentScenes = scenes.filter((s) => !s?.template_data?.is_outro).length;
  if (!contentScenes) issues.push({ problem: "final_visual_qa_no_content_scenes" });
  if (results.length + issues.filter((x) => String(x.problem || "").includes("frame_sampling_failed") || String(x.problem || "").includes("model_failed")).length < contentScenes) {
    issues.push({ problem: "final_visual_qa_incomplete_scene_coverage" });
  }
  return { enabled: true, passed: issues.length === 0, threshold: MIN_SCORE, checked: results.length, expected: contentScenes, issues, results };
}

module.exports = { reviewFinalVideo, sampleSceneContactSheet, judgeScene, parseJsonObject };
