// API_BUDGET / PREPROD_BROLL_HARDENING — shared paid-vision budget for V4.
const RUN_MAX_VISION_CALLS = Math.max(1, Number(process.env.BROLL_RUN_MAX_VISION_CALLS || 28));
const FIRST_FRAME_MAX_VISION_CALLS = Math.max(1, Number(process.env.BROLL_FIRST_FRAME_MAX_VISION_CALLS || 7));
// Backward compatibility: the old SUPPORT_MAX variable is now the guaranteed
// per-support-scene reserve. Hard support scenes may borrow unused run budget
// up to SUPPORT_BORROW_MAX while future retrieval scenes keep their reserve.
const SUPPORT_BASE_VISION_CALLS = Math.max(1, Number(process.env.BROLL_SUPPORT_BASE_VISION_CALLS || process.env.BROLL_SUPPORT_MAX_VISION_CALLS || 3));
const SUPPORT_BORROW_MAX_VISION_CALLS = Math.max(SUPPORT_BASE_VISION_CALLS, Number(process.env.BROLL_SUPPORT_BORROW_MAX_VISION_CALLS || 7));
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

function getRunState(runId) {
  cleanupRuns();
  const id = String(runId || "").trim();
  const state = id ? runBudgets.get(id) : null;
  return { id, used: state?.used || 0, remaining: Math.max(0, RUN_MAX_VISION_CALLS - (state?.used || 0)) };
}

function getSceneLimit(firstFrame, context = {}) {
  if (firstFrame) return Math.min(FIRST_FRAME_MAX_VISION_CALLS, RUN_MAX_VISION_CALLS);

  const base = Math.min(SUPPORT_BASE_VISION_CALLS, RUN_MAX_VISION_CALLS);
  const hardMax = Math.min(SUPPORT_BORROW_MAX_VISION_CALLS, RUN_MAX_VISION_CALLS);
  const total = Number(context.retrievalSceneCount ?? context.retrieval_scene_count);
  const position = Number(context.retrievalScenePosition ?? context.retrieval_scene_position);
  const run = getRunState(context.runId ?? context.run_id);

  // Without exact run topology, retain the conservative guaranteed reserve.
  if (!run.id || !Number.isInteger(total) || total < 1 || !Number.isInteger(position) || position < 0 || position >= total) {
    return base;
  }

  // Preserve a guaranteed reserve for each future retrieval scene, then let
  // the current support scene borrow whatever is genuinely spare. This keeps
  // the global 28-call ceiling intact while avoiding a fixed 3-call failure on
  // a 3-4 scene Short where most of the run budget would otherwise sit unused.
  const futureScenes = Math.max(0, total - position - 1);
  const reserveForFuture = futureScenes * base;
  const allocatableNow = Math.max(base, run.remaining - reserveForFuture);
  return Math.max(1, Math.min(hardMax, allocatableNow));
}

// A designed Remotion template (comparison/stat_reveal/kinetic_text/etc) is
// the resolver's last resort when no real footage clears the quality bar.
// Nothing coordinates how many scenes reach for it independently, so a Short
// where 3 different scenes each fail real-media search on their own can end
// up with 3+ template scenes - well past the 1-template-per-Short ceiling
// enforced later (Validate Final Script, and again at the merge stage).
// That ceiling counts BOTH the Visual Director's own intentional template
// plan and any resolver fallback together, so reserveTemplateFallback also
// takes plannedTemplateCount (how many scenes elsewhere in this exact
// script are already visual_source='template') into account: if the plan
// already has one, no fallback budget remains for this run at all.
function reserveTemplateFallback(runId, sceneIndex, context = {}) {
  const scene = Number(sceneIndex);
  if (scene === 0 || context.firstFrame === true || context.first_frame === true) {
    return { allowed: false, reason: "template_fallback_first_frame_forbidden" };
  }

  const planned = Number(context.plannedTemplateCount ?? context.planned_template_count ?? 0);
  if (Number.isFinite(planned) && planned > 0) {
    return { allowed: false, reason: "template_fallback_planned_template_already_present" };
  }

  const id = String(runId || "").trim();
  if (!id) return { allowed: false, reason: "template_fallback_missing_run_id" };
  cleanupRuns();

  const state = runBudgets.get(id) || { used: 0, template_fallbacks: [], updated_at: Date.now() };
  state.template_fallbacks = Array.isArray(state.template_fallbacks) ? state.template_fallbacks : [];
  if (state.template_fallbacks.length >= 1) {
    state.updated_at = Date.now();
    runBudgets.set(id, state);
    return { allowed: false, reason: "template_fallback_cap_exhausted", used: state.template_fallbacks.length };
  }

  state.template_fallbacks.push(scene);
  state.updated_at = Date.now();
  runBudgets.set(id, state);
  return { allowed: true, used: state.template_fallbacks.length, scene_index: scene };
}

function reserveVisionCall(runId, sceneState = null) {
  const id = String(runId || "").trim();
  cleanupRuns();

  // Report the global ceiling first when both limits are exhausted. This makes
  // diagnostics truthful: the run cannot spend another call regardless of the
  // current scene's nominal allowance.
  if (id) {
    const state = runBudgets.get(id) || { used: 0, updated_at: Date.now() };
    if (state.used >= RUN_MAX_VISION_CALLS) {
      state.updated_at = Date.now();
      runBudgets.set(id, state);
      return { allowed: false, reason: "run_vision_budget_exhausted", used: state.used, remaining: 0 };
    }
  }
  if (sceneState && sceneState.used >= sceneState.limit) {
    return { allowed: false, reason: "scene_vision_budget_exhausted" };
  }

  if (id) {
    const state = runBudgets.get(id) || { used: 0, updated_at: Date.now() };
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
  const run = getRunState(runId);
  return {
    run_used: run.id ? run.used : null,
    run_remaining: run.id ? run.remaining : null,
    scene_used: sceneState?.used ?? null,
    scene_limit: sceneState?.limit ?? null,
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
  FIRST_FRAME_MAX_VISION_CALLS,
  SUPPORT_BASE_VISION_CALLS,
  SUPPORT_BORROW_MAX_VISION_CALLS,
  getSceneLimit,
  reserveVisionCall,
  reserveTemplateFallback,
  getBudgetState,
  cacheKey,
  getCachedResult,
  putCachedResult,
};
