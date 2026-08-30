// API_BUDGET / PREPROD_BROLL_HARDENING — shared paid-vision budget for V4.
const RUN_MAX_VISION_CALLS = Math.max(1, Number(process.env.BROLL_RUN_MAX_VISION_CALLS || 28));
const FIRST_FRAME_MAX_VISION_CALLS = Math.max(1, Number(process.env.BROLL_FIRST_FRAME_MAX_VISION_CALLS || 6));
const SUPPORT_MAX_VISION_CALLS = Math.max(1, Number(process.env.BROLL_SUPPORT_MAX_VISION_CALLS || 4));
const RUN_BUDGET_TTL_MS = Math.max(60000, Number(process.env.BROLL_RUN_BUDGET_TTL_MS || 7200000));
const RESULT_CACHE_TTL_MS = Math.max(60000, Number(process.env.BROLL_SCORE_CACHE_TTL_MS || 21600000));
const RESULT_CACHE_MAX = Math.max(100, Number(process.env.BROLL_SCORE_CACHE_MAX || 800));

const runBudgets = new Map();
const resultCache = new Map();

function cleanupRuns(now = Date.now()) {
  for (const [id, state] of runBudgets) {
    if (now - state.updated_at > RUN_BUDGET_TTL_MS) runBudgets.delete(id);
  }
}

function getSceneLimit(firstFrame) {
  return firstFrame ? FIRST_FRAME_MAX_VISION_CALLS : SUPPORT_MAX_VISION_CALLS;
}

function reserveVisionCall(runId, sceneState = null) {
  const id = String(runId || "").trim();
  if (sceneState && sceneState.used >= sceneState.limit) {
    return { allowed: false, reason: "scene_vision_budget_exhausted" };
  }
  cleanupRuns();
  if (id) {
    const state = runBudgets.get(id) || { used: 0, updated_at: Date.now() };
    if (state.used >= RUN_MAX_VISION_CALLS) {
      state.updated_at = Date.now();
      runBudgets.set(id, state);
      return { allowed: false, reason: "run_vision_budget_exhausted", used: state.used, remaining: 0 };
    }
    state.used += 1;
    state.updated_at = Date.now();
    runBudgets.set(id, state);
  }
  if (sceneState) sceneState.used += 1;
  const run = id ? runBudgets.get(id) : null;
  return {
    allowed: true,
    used: run?.used ?? null,
    remaining: run ? Math.max(0, RUN_MAX_VISION_CALLS - run.used) : null,
  };
}

function getBudgetState(runId, sceneState = null) {
  cleanupRuns();
  const id = String(runId || "").trim();
  const run = id ? runBudgets.get(id) : null;
  return {
    run_used: run?.used ?? null,
    run_remaining: run ? Math.max(0, RUN_MAX_VISION_CALLS - run.used) : null,
    scene_used: sceneState?.used ?? null,
    scene_remaining: sceneState ? Math.max(0, sceneState.limit - sceneState.used) : null,
  };
}

function cacheKey(parts) {
  return (parts || []).map((p) => String(p ?? "")).join("|");
}

function getCachedResult(key, now = Date.now()) {
  const hit = resultCache.get(key);
  if (!hit) return null;
  if (now - hit.at > RESULT_CACHE_TTL_MS) {
    resultCache.delete(key);
    return null;
  }
  resultCache.delete(key);
  resultCache.set(key, hit);
  return hit.value;
}

function putCachedResult(key, value, now = Date.now()) {
  if (!key || value == null) return;
  resultCache.delete(key);
  resultCache.set(key, { value, at: now });
  while (resultCache.size > RESULT_CACHE_MAX) {
    const oldest = resultCache.keys().next().value;
    if (oldest == null) break;
    resultCache.delete(oldest);
  }
}

module.exports = {
  RUN_MAX_VISION_CALLS,
  getSceneLimit,
  reserveVisionCall,
  getBudgetState,
  cacheKey,
  getCachedResult,
  putCachedResult,
};
