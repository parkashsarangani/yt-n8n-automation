// ---------------------------------------------------------------------------
// Feedback loop: learn from what published Shorts actually did.
//
// Adapted from the VidGen (long-form) engine's measure -> strategize design,
// but fitted to this n8n + compose pipeline (JSON files in the shorts_data
// volume instead of a Postgres artifact store).
//
// Two deliberately separate steps:
//   1. LOG + MEASURE (observation, no opinions): after a video is published we
//      record the metadata that produced it; a daily n8n job pulls YouTube
//      Analytics and joins the numbers onto that record.
//   2. STRATEGIZE (opinion, traceable to the numbers): a Claude call reads the
//      measured history and produces channel_insights - evidence-backed
//      guidance - which the topic generator then reads.
//
// Discipline carried over from VidGen: small samples support small claims; with
// 0 measured videos we produce NO guidance rather than generic advice.
// ---------------------------------------------------------------------------
const fs = require("fs");
const fsp = require("fs/promises");
const path = require("path");
const axios = require("axios");

const DATA_DIR = path.dirname(process.env.TOPIC_HISTORY_PATH || "/app/data/topic_history.json");
const PERF_PATH = path.join(DATA_DIR, "performance_history.json");
const INSIGHTS_PATH = path.join(DATA_DIR, "channel_insights.json");
const PERF_MAX = Number(process.env.PERF_HISTORY_MAX || 300);

const ANTHROPIC_KEY = process.env.ANTHROPIC_KEY || "";
const STRATEGIST_MODEL = process.env.STRATEGIST_MODEL || "claude-sonnet-5";

async function readJson(p, fallback) {
  try {
    if (!fs.existsSync(p)) return fallback;
    return JSON.parse(await fsp.readFile(p, "utf8"));
  } catch {
    return fallback;
  }
}
async function writeJson(p, data) {
  await fsp.mkdir(path.dirname(p), { recursive: true });
  await fsp.writeFile(p, JSON.stringify(data, null, 2));
}

// --- 1a. LOG: record a published video + the metadata that produced it -------
async function logPublished(entry) {
  const vid = entry && entry.video_id;
  if (!vid) throw new Error("logPublished: video_id is required");
  let hist = await readJson(PERF_PATH, []);
  // idempotent: one record per video_id
  if (hist.some((h) => h.video_id === vid)) return { logged: false, reason: "already_logged", count: hist.length };
  hist.push({
    video_id: vid,
    published_at: entry.published_at || new Date().toISOString(),
    topic: entry.topic || null,
    hook: entry.hook || null,
    title: entry.title || null,
    comment_hook: entry.comment_hook || null,
    caption_style: entry.caption_style || null,
    // The psychological trigger the hook leads with (curiosity_gap, disbelief,
    // fear_stakes, scale_shock, taboo_secret). Lets the strategist compare which
    // lever actually earns views instead of us assuming curiosity is always best.
    trigger: entry.trigger || null,
    duration: entry.duration != null ? Number(entry.duration) : null,
    metrics: null, // filled in later by the measure step
  });
  if (hist.length > PERF_MAX) hist = hist.slice(hist.length - PERF_MAX);
  await writeJson(PERF_PATH, hist);
  return { logged: true, count: hist.length };
}

// --- 1b. MEASURE: parse a YouTube Analytics (dimensions=video) response and
//         join the numbers onto the logged records --------------------------
function parseAnalytics(body) {
  // body is the raw YouTube Analytics reports response:
  //   { columnHeaders:[{name:"video"},{name:"views"},...], rows:[["id",123,...]] }
  const headers = (body && body.columnHeaders ? body.columnHeaders : []).map((h) => h.name);
  const rows = (body && body.rows) || [];
  const vi = headers.indexOf("video");
  if (vi < 0) return {};
  const out = {};
  for (const row of rows) {
    const id = row[vi];
    if (!id) continue;
    const m = {};
    headers.forEach((name, i) => { if (name !== "video") m[name] = row[i]; });
    const pct = (v) => (v == null ? null : (v > 1 ? v / 100 : v));
    out[id] = {
      views: Math.round(m.views || 0),
      average_view_percentage: m.averageViewPercentage != null ? m.averageViewPercentage : null,
      average_view_duration_sec: m.averageViewDuration != null ? m.averageViewDuration : null,
      subscribers_gained: Math.round(m.subscribersGained || 0),
      likes: Math.round(m.likes || 0),
      comments: Math.round(m.comments || 0),
      shares: Math.round(m.shares || 0),
      impressions: m.videoThumbnailImpressions != null ? Math.round(m.videoThumbnailImpressions) : null,
      click_through_rate: pct(m.videoThumbnailImpressionsClickRate),
    };
  }
  return out;
}

// --- 2. STRATEGIZE: turn the measured history into evidence-backed guidance ---
const STRATEGIST_PROMPT = (perfJson) =>
`You read what this YouTube Shorts channel's published videos actually did and say what that implies for the next one. You are the ONLY part of the system that learns from outcomes, so being wrong here is expensive and being vague is useless.

MEASURED VIDEOS (each has the metadata that produced it plus its metrics):
${perfJson}

THE DISCIPLINE:
- Small samples support small claims. With fewer than ~8 measured videos you cannot separate a real pattern from noise. Say so plainly in confidence_note and keep guidance short or empty.
- If there are 0 measured videos, produce NO guidance: sample_size 0, confidence_note saying nothing is measured yet, empty guidance array. Do NOT substitute generic YouTube advice - the system already has opinions baked into its prompts.
- Retention (average_view_percentage) is the metric you can usually trust; it reflects whether the video delivered what its hook/title promised. A high-view, low-retention video is a hook that oversold - a real finding even in small samples.
- Each video carries a "trigger" - the psychological lever its hook leads with (curiosity_gap, disbelief, fear_stakes, scale_shock, taboo_secret). When one trigger clearly out- or under-performs the others on views AND you have at least ~2 videos per trigger, say so as trigger guidance with the numbers; otherwise treat trigger differences as noise and stay silent on them. Never recommend collapsing to a single trigger on thin data - variety is protective.
- comments and shares are the escalation signals; near-zero across the board is itself a finding.
- Only claim things about click_through_rate/impressions if those numbers are actually present (they are often null).
- Evidence means naming the videos and the numbers. "shorter is better" is a hunch; "the 3 videos under 25s averaged 71% retention vs 48% for the rest" is a finding.

OUTPUT - respond with ONLY a JSON object, no prose, no markdown fences:
{
  "sample_size": <integer, how many MEASURED videos the guidance rests on>,
  "confidence_note": "<what this sample can and cannot support - be specific about the limit>",
  "guidance": [ { "area": "topic"|"hook"|"title"|"structure"|"length"|"trigger", "advice": "<what to do next time>", "evidence": "<the specific videos and numbers>" } ],
  "avoid": [ "<pattern that measurably underperformed, from evidence only>" ]
}
Prefer three well-grounded items to eight padded ones. Every item is read by another agent and acted on.`;

async function runStrategist(history) {
  const measured = history.filter((h) => h.metrics && typeof h.metrics.views === "number");
  // Feed the strategist a compact, relevant view of each measured video.
  const payload = measured.map((h) => ({
    topic: h.topic,
    hook: h.hook,
    title: h.title,
    trigger: h.trigger,
    duration_sec: h.duration,
    metrics: h.metrics,
  }));

  if (!ANTHROPIC_KEY) throw new Error("runStrategist: ANTHROPIC_KEY is not set");

  const res = await axios.post(
    "https://api.anthropic.com/v1/messages",
    {
      model: STRATEGIST_MODEL,
      max_tokens: 1500,
      messages: [{ role: "user", content: STRATEGIST_PROMPT(JSON.stringify(payload, null, 2)) }],
    },
    {
      timeout: 60000,
      headers: { "x-api-key": ANTHROPIC_KEY, "anthropic-version": "2023-06-01", "content-type": "application/json" },
    }
  );
  const text = (res.data.content || []).map((b) => (b && b.text) || "").join("");
  const start = text.indexOf("{");
  const end = text.lastIndexOf("}");
  if (start < 0 || end < 0) throw new Error("strategist returned no JSON: " + text.slice(0, 200));
  const insights = JSON.parse(text.slice(start, end + 1));
  insights.generated_at = new Date().toISOString();
  insights.measured_count = measured.length;
  await writeJson(INSIGHTS_PATH, insights);
  return insights;
}

// --- orchestration: ingest analytics, join, re-strategize --------------------
async function ingestAnalytics(analyticsBody) {
  const metricsById = parseAnalytics(analyticsBody);
  const hist = await readJson(PERF_PATH, []);
  let updated = 0;
  const measured_at = new Date().toISOString();
  for (const h of hist) {
    const m = metricsById[h.video_id];
    if (m) { h.metrics = { ...m, measured_at }; updated++; }
  }
  await writeJson(PERF_PATH, hist);
  let insights = null;
  try { insights = await runStrategist(hist); } catch (e) { insights = { error: String(e.message || e) }; }
  return { updated, total: hist.length, insights };
}

async function getInsights() {
  return await readJson(INSIGHTS_PATH, { sample_size: 0, confidence_note: "No videos measured yet.", guidance: [], avoid: [] });
}

// SHORTS-ONLY: the only video IDs the loop ever touches are the ones THIS
// pipeline logged here. Long-form videos on the same YouTube channel are never
// logged, so they can never be measured or reach the strategist. This returns
// the shorts to measure, and the analytics query is filtered to exactly these
// IDs - so channel-wide numbers never leak long videos into the feedback.
async function getMeasureIds({ maxDays = 60, limit = 200 } = {}) {
  const hist = await readJson(PERF_PATH, []);
  const cutoff = Date.now() - maxDays * 24 * 60 * 60 * 1000;
  return hist
    .filter((h) => h.video_id && (!h.published_at || new Date(h.published_at).getTime() >= cutoff))
    .map((h) => h.video_id)
    .slice(-limit); // most recent
}

module.exports = { logPublished, ingestAnalytics, getInsights, getMeasureIds, runStrategist, parseAnalytics, PERF_PATH, INSIGHTS_PATH };
