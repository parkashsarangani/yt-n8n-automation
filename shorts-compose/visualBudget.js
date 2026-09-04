// API_BUDGET / PREPROD_BROLL_HARDENING — durable paid-vision budget for V4.
//
// The original implementation kept run budgets and score-cache entries in
// process-local Maps. That made the "run-wide" ceiling disappear on restart and
// allowed multiple service processes to each spend the full budget. This module
// keeps the same synchronous API but persists state behind an atomic filesystem
// lock on the shared /app/data volume. It therefore survives restarts and is
// coordinated across processes/containers that mount the same state file.
const fs = require("fs");
const path = require("path");
const os = require("os");
const crypto = require("crypto");

const RUN_MAX_VISION_CALLS = Math.max(1, Number(process.env.BROLL_RUN_MAX_VISION_CALLS || 28));
const FIRST_FRAME_MAX_VISION_CALLS = Math.max(1, Number(process.env.BROLL_FIRST_FRAME_MAX_VISION_CALLS || 7));
const SUPPORT_BASE_VISION_CALLS = Math.max(1, Number(process.env.BROLL_SUPPORT_BASE_VISION_CALLS || process.env.BROLL_SUPPORT_MAX_VISION_CALLS || 3));
const SUPPORT_BORROW_MAX_VISION_CALLS = Math.max(SUPPORT_BASE_VISION_CALLS, Number(process.env.BROLL_SUPPORT_BORROW_MAX_VISION_CALLS || 7));
const RUN_BUDGET_TTL_MS = Math.max(60000, Number(process.env.BROLL_RUN_BUDGET_TTL_MS || 7200000));
const RESULT_CACHE_TTL_MS = Math.max(60000, Number(process.env.BROLL_SCORE_CACHE_TTL_MS || 21600000));
const RESULT_CACHE_MAX = Math.max(100, Number(process.env.BROLL_SCORE_CACHE_MAX || 800));
const STATE_PATH = process.env.BROLL_BUDGET_STATE_PATH || path.join(os.tmpdir(), "yt-shorts-visual-budget-state.json");
const LOCK_PATH = `${STATE_PATH}.lock`;
const LOCK_WAIT_MS = Math.max(250, Number(process.env.BROLL_BUDGET_LOCK_WAIT_MS || 3000));
const LOCK_STALE_MS = Math.max(5000, Number(process.env.BROLL_BUDGET_LOCK_STALE_MS || 30000));
const sleepArray = new Int32Array(new SharedArrayBuffer(4));

function emptyState() {
  return { version: 1, runs: {}, cache: {} };
}

function sleepSync(ms) {
  Atomics.wait(sleepArray, 0, 0, Math.max(1, ms));
}

function ensureStateDir() {
  fs.mkdirSync(path.dirname(STATE_PATH), { recursive: true });
}

function acquireLock() {
  ensureStateDir();
  const deadline = Date.now() + LOCK_WAIT_MS;
  while (true) {
    try {
      const fd = fs.openSync(LOCK_PATH, "wx", 0o600);
      fs.writeFileSync(fd, `${process.pid}\n${Date.now()}\n`);
      return fd;
    } catch (err) {
      if (err?.code !== "EEXIST") throw err;
      try {
        const st = fs.statSync(LOCK_PATH);
        if (Date.now() - st.mtimeMs > LOCK_STALE_MS) {
          fs.unlinkSync(LOCK_PATH);
          continue;
        }
      } catch (stErr) {
        if (stErr?.code === "ENOENT") continue;
      }
      if (Date.now() >= deadline) throw new Error("visual_budget_state_lock_timeout");
      sleepSync(15);
    }
  }
}

function releaseLock(fd) {
  try { if (fd != null) fs.closeSync(fd); } catch {}
  try { fs.unlinkSync(LOCK_PATH); } catch {}
}

function readState() {
  try {
    const parsed = JSON.parse(fs.readFileSync(STATE_PATH, "utf8"));
    if (!parsed || typeof parsed !== "object") return emptyState();
    if (!parsed.runs || typeof parsed.runs !== "object") parsed.runs = {};
    if (!parsed.cache || typeof parsed.cache !== "object") parsed.cache = {};
    return parsed;
  } catch (err) {
    if (err?.code === "ENOENT") return emptyState();
    // A corrupt state file must not disable the budget forever. Preserve it for
    // diagnosis, then restart from an empty state under the lock.
    try { fs.renameSync(STATE_PATH, `${STATE_PATH}.corrupt-${Date.now()}`); } catch {}
    return emptyState();
  }
}

function cleanupState(state, now = Date.now()) {
  for (const [id, run] of Object.entries(state.runs || {})) {
    if (!run || now - Number(run.updated_at || 0) > RUN_BUDGET_TTL_MS) delete state.runs[id];
  }
  for (const [key, entry] of Object.entries(state.cache || {})) {
    if (!entry || now - Number(entry.at || 0) > RESULT_CACHE_TTL_MS) delete state.cache[key];
  }
  const cacheEntries = Object.entries(state.cache || {});
  if (cacheEntries.length > RESULT_CACHE_MAX) {
    cacheEntries
      .sort((a, b) => Number(a[1]?.last_access || a[1]?.at || 0) - Number(b[1]?.last_access || b[1]?.at || 0))
      .slice(0, cacheEntries.length - RESULT_CACHE_MAX)
      .forEach(([key]) => delete state.cache[key]);
  }
  return state;
}

function writeState(state) {
  ensureStateDir();
  const tmp = `${STATE_PATH}.tmp-${process.pid}-${Date.now()}-${Math.random().toString(16).slice(2)}`;
  fs.writeFileSync(tmp, JSON.stringify(state), { mode: 0o600 });
  fs.renameSync(tmp, STATE_PATH);
}

function withLockedState(mutator) {
  const fd = acquireLock();
  try {
    const state = cleanupState(readState());
    const result = mutator(state);
    cleanupState(state);
    writeState(state);
    return result;
  } finally {
    releaseLock(fd);
  }
}

function getRunSnapshot(state, runId) {
  const id = String(runId || "").trim();
  const run = id ? state.runs[id] : null;
  const used = Math.max(0, Number(run?.used || 0));
  return { id, used, remaining: Math.max(0, RUN_MAX_VISION_CALLS - used) };
}

function getRunState(runId) {
  return withLockedState((state) => getRunSnapshot(state, runId));
}

function getSceneLimit(firstFrame, context = {}) {
  if (firstFrame) return Math.min(FIRST_FRAME_MAX_VISION_CALLS, RUN_MAX_VISION_CALLS);

  const base = Math.min(SUPPORT_BASE_VISION_CALLS, RUN_MAX_VISION_CALLS);
  const hardMax = Math.min(SUPPORT_BORROW_MAX_VISION_CALLS, RUN_MAX_VISION_CALLS);
  const total = Number(context.retrievalSceneCount ?? context.retrieval_scene_count);
  const position = Number(context.retrievalScenePosition ?? context.retrieval_scene_position);
  const run = getRunState(context.runId ?? context.run_id);

  if (!run.id || !Number.isInteger(total) || total < 1 || !Number.isInteger(position) || position < 0 || position >= total) {
    return base;
  }

  const futureScenes = Math.max(0, total - position - 1);
  const reserveForFuture = futureScenes * base;
  const allocatableNow = Math.max(base, run.remaining - reserveForFuture);
  return Math.max(1, Math.min(hardMax, allocatableNow));
}

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

  return withLockedState((state) => {
    const run = state.runs[id] || { used: 0, template_fallbacks: [], updated_at: Date.now() };
    run.template_fallbacks = Array.isArray(run.template_fallbacks) ? run.template_fallbacks : [];
    if (run.template_fallbacks.length >= 1) {
      run.updated_at = Date.now();
      state.runs[id] = run;
      return { allowed: false, reason: "template_fallback_cap_exhausted", used: run.template_fallbacks.length };
    }
    run.template_fallbacks.push(scene);
    run.updated_at = Date.now();
    state.runs[id] = run;
    return { allowed: true, used: run.template_fallbacks.length, scene_index: scene };
  });
}

function reserveVisionCall(runId, sceneState = null) {
  const id = String(runId || "").trim();
  if (sceneState && sceneState.used >= sceneState.limit) {
    return { allowed: false, reason: "scene_vision_budget_exhausted" };
  }

  return withLockedState((state) => {
    let run = null;
    if (id) {
      run = state.runs[id] || { used: 0, template_fallbacks: [], updated_at: Date.now() };
      if (Number(run.used || 0) >= RUN_MAX_VISION_CALLS) {
        run.updated_at = Date.now();
        state.runs[id] = run;
        return { allowed: false, reason: "run_vision_budget_exhausted", used: Number(run.used || 0), remaining: 0 };
      }
      run.used = Number(run.used || 0) + 1;
      run.updated_at = Date.now();
      state.runs[id] = run;
    }
    if (sceneState) sceneState.used += 1;
    return {
      allowed: true,
      used: run ? run.used : null,
      remaining: run ? Math.max(0, RUN_MAX_VISION_CALLS - run.used) : null,
    };
  });
}

function getBudgetState(runId, sceneState = null) {
  const run = getRunState(runId);
  return {
    run_used: run.id ? run.used : null,
    run_remaining: run.id ? run.remaining : null,
    scene_used: sceneState?.used ?? null,
    scene_limit: sceneState?.limit ?? null,
    scene_remaining: sceneState ? Math.max(0, sceneState.limit - sceneState.used) : null,
    durable_state: true,
  };
}

function cacheKey(parts) {
  const payload = (parts || []).map((p) => String(p ?? "")).join("|");
  return crypto.createHash("sha256").update(payload).digest("hex");
}

function getCachedResult(key, now = Date.now()) {
  if (!key) return null;
  return withLockedState((state) => {
    const hit = state.cache[key];
    if (!hit || now - Number(hit.at || 0) > RESULT_CACHE_TTL_MS) {
      if (hit) delete state.cache[key];
      return null;
    }
    hit.last_access = now;
    return hit.value;
  });
}

function putCachedResult(key, value, now = Date.now()) {
  if (!key || value == null) return;
  withLockedState((state) => {
    state.cache[key] = { value, at: now, last_access: now };
    return null;
  });
}

module.exports = {
  RUN_MAX_VISION_CALLS,
  FIRST_FRAME_MAX_VISION_CALLS,
  SUPPORT_BASE_VISION_CALLS,
  SUPPORT_BORROW_MAX_VISION_CALLS,
  STATE_PATH,
  getSceneLimit,
  reserveVisionCall,
  reserveTemplateFallback,
  getBudgetState,
  cacheKey,
  getCachedResult,
  putCachedResult,
};
