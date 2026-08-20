const fs = require("fs");
const fsp = require("fs/promises");
const path = require("path");

const DATA_DIR = path.dirname(process.env.TOPIC_HISTORY_PATH || "/app/data/topic_history.json");
const RETRIEVAL_PATH = path.join(DATA_DIR, "retrieval_history.json");
const RETRIEVAL_MAX = Math.max(20, Number(process.env.RETRIEVAL_HISTORY_MAX || 500));

function numOrNull(v) {
  if (v === null || v === undefined || v === "") return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}

function boolOrNull(v) {
  if (v === null || v === undefined) return null;
  return Boolean(v);
}

function cleanString(v, max = 160) {
  if (v === null || v === undefined) return null;
  const s = String(v).replace(/\s+/g, " ").trim();
  return s ? s.slice(0, max) : null;
}

function cleanStrings(values, maxItems = 8, maxLen = 120) {
  return Array.isArray(values)
    ? values.map((v) => cleanString(v, maxLen)).filter(Boolean).slice(0, maxItems)
    : [];
}

function cleanCounts(value) {
  const out = {};
  if (!value || typeof value !== "object" || Array.isArray(value)) return out;
  for (const [key, raw] of Object.entries(value).slice(0, 12)) {
    const k = cleanString(key, 48);
    const n = Number(raw);
    if (k && Number.isFinite(n) && n >= 0) out[k] = Math.round(n);
  }
  return out;
}

function normalizeScene(row = {}) {
  return {
    scene_index: numOrNull(row.scene_index),
    visual_mode: cleanString(row.visual_mode, 40),
    must_show: cleanString(row.must_show, 180),
    requested_queries: cleanStrings(row.requested_queries, 6, 120),
    source_priority: cleanStrings(row.source_priority, 8, 48),
    queries_tried: cleanStrings(row.queries_tried, 8, 120),
    candidate_count: numOrNull(row.candidate_count),
    candidate_source_counts: cleanCounts(row.candidate_source_counts),
    candidate_type_counts: cleanCounts(row.candidate_type_counts),
    scored_count: numOrNull(row.scored_count),
    vision_calls: numOrNull(row.vision_calls),
    cache_hits: numOrNull(row.cache_hits),
    search_rounds: numOrNull(row.search_rounds),
    selected_query: cleanString(row.selected_query, 120),
    selected_source: cleanString(row.selected_source, 48),
    score: numOrNull(row.score),
    relevance: numOrNull(row.relevance),
    local_similarity: numOrNull(row.local_similarity),
    top_local_similarity: numOrNull(row.top_local_similarity),
    threshold: numOrNull(row.threshold),
    degraded: boolOrNull(row.degraded),
    quality_gate_passed: boolOrNull(row.quality_gate_passed),
    fallback_reason: cleanString(row.fallback_reason, 100),
    intentional_template: boolOrNull(row.intentional_template),
  };
}

function normalizeTelemetry(entry = {}) {
  const scenes = Array.isArray(entry.retrieval_telemetry) ? entry.retrieval_telemetry : [];
  return {
    video_id: cleanString(entry.video_id, 128),
    topic: cleanString(entry.topic, 300),
    logged_at: new Date().toISOString(),
    scenes: scenes.slice(0, 12).map(normalizeScene),
  };
}

async function readHistory() {
  try {
    if (!fs.existsSync(RETRIEVAL_PATH)) return [];
    const parsed = JSON.parse(await fsp.readFile(RETRIEVAL_PATH, "utf8"));
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

async function writeHistory(history) {
  await fsp.mkdir(path.dirname(RETRIEVAL_PATH), { recursive: true });
  await fsp.writeFile(RETRIEVAL_PATH, JSON.stringify(history, null, 2));
}

async function log(entry = {}) {
  const normalized = normalizeTelemetry(entry);
  if (!normalized.video_id || !normalized.scenes.length) {
    return { logged: false, reason: "no_retrieval_telemetry" };
  }
  let history = await readHistory();
  const existing = history.findIndex((item) => item.video_id === normalized.video_id);
  if (existing >= 0) history[existing] = normalized;
  else history.push(normalized);
  if (history.length > RETRIEVAL_MAX) history = history.slice(history.length - RETRIEVAL_MAX);
  await writeHistory(history);
  return { logged: true, scene_count: normalized.scenes.length, count: history.length };
}

async function getRecent({ limit = 20 } = {}) {
  const bounded = Math.max(1, Math.min(100, Number(limit) || 20));
  const history = await readHistory();
  return history.slice(-bounded).reverse();
}

module.exports = {
  RETRIEVAL_PATH,
  normalizeScene,
  normalizeTelemetry,
  log,
  getRecent,
};
