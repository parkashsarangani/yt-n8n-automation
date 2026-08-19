// ---------------------------------------------------------------------------
// Feedback loop: learn from what published Shorts actually did.
//
// V3 records the creative DNA that produced each upload, not just its topic and
// hook. That lets the strategist learn whether visual grammar, first-frame type,
// scene count, payoff position, source mix, captions, and engagement mechanics
// correlate with retention/shares instead of guessing from prose alone.
// ---------------------------------------------------------------------------
const fs = require("fs");
const fsp = require("fs/promises");
const path = require("path");
const axios = require("axios");

const DATA_DIR = path.dirname(process.env.TOPIC_HISTORY_PATH || "/app/data/topic_history.json");
const PERF_PATH = path.join(DATA_DIR, "performance_history.json");
const INSIGHTS_PATH = path.join(DATA_DIR, "channel_insights.json");
const PERF_MAX = Number(process.env.PERF_HISTORY_MAX || 500);

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

function numOrNull(v) {
  if (v === null || v === undefined || v === "") return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}

function boolOrNull(v) {
  if (v === null || v === undefined) return null;
  return Boolean(v);
}

function normalizeCreativeDna(entry = {}) {
  const dna = entry.creative_dna && typeof entry.creative_dna === "object" ? entry.creative_dna : entry;
  return {
    concept_archetype: dna.concept_archetype || null,
    creative_format: dna.creative_format || null,
    visual_grammar: dna.visual_grammar || null,
    first_frame_type: dna.first_frame_type || null,
    first_frame_source: dna.first_frame_source || null,
    first_frame_score: numOrNull(dna.first_frame_score),
    scene_count: numOrNull(dna.scene_count),
    word_count: numOrNull(dna.word_count),
    duration_sec: numOrNull(dna.duration_sec ?? entry.duration),
    payoff_position_pct: numOrNull(dna.payoff_position_pct),
    open_loop_count: numOrNull(dna.open_loop_count),
    template_count: numOrNull(dna.template_count),
    real_video_count: numOrNull(dna.real_video_count),
    still_image_count: numOrNull(dna.still_image_count),
    caption_mode: dna.caption_mode || null,
    transition_style: dna.transition_style || null,
    engagement_mode: dna.engagement_mode || null,
    comment_hook_present: boolOrNull(dna.comment_hook_present),
    outro_present: boolOrNull(dna.outro_present),
    asset_quality_min: numOrNull(dna.asset_quality_min),
    asset_quality_avg: numOrNull(dna.asset_quality_avg),
  };
}

async function logPublished(entry) {
  const vid = entry && entry.video_id;
  if (!vid) throw new Error("logPublished: video_id is required");
  let hist = await readJson(PERF_PATH, []);
  if (hist.some((h) => h.video_id === vid)) {
    return { logged: false, reason: "already_logged", count: hist.length };
  }

  const creativeDna = normalizeCreativeDna(entry);
  hist.push({
    video_id: vid,
    published_at: entry.published_at || new Date().toISOString(),
    topic: entry.topic || null,
    hook: entry.hook || null,
    title: entry.title || null,
    comment_hook: entry.comment_hook || null,
    caption_style: entry.caption_style || null,
    trigger: entry.trigger || null,
    duration: creativeDna.duration_sec,
    creative_dna: creativeDna,
    metrics: null,
  });

  if (hist.length > PERF_MAX) hist = hist.slice(hist.length - PERF_MAX);
  await writeJson(PERF_PATH, hist);
  return { logged: true, count: hist.length };
}

function parseAnalytics(body) {
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

const STRATEGIST_PROMPT = (perfJson) =>
`You analyze what this YouTube Shorts channel actually published and what happened. Your job is to turn measured outcomes into narrow, testable guidance for the next Shorts.

MEASURED VIDEOS (metadata + creative DNA + outcomes):
${perfJson}

DISCIPLINE:
- Fewer than ~8 measured videos: make only very small claims. With zero, return no guidance.
- For any comparison between two creative choices, require at least 2 measured videos in EACH group. Prefer 3+ per group before calling a pattern meaningful.
- Retention (average_view_percentage) is the primary delivery signal. Views alone can reward a strong hook even when the content disappoints.
- Shares/comments are escalation signals. Subscriber gain is useful when present but noisy at small samples.
- Never infer a causal effect from one winner. Say "associated with" unless a repeated pattern is genuinely clear.
- Only discuss impressions/CTR when those metrics are non-null.
- Evidence must name the compared groups and numbers.

CREATIVE VARIABLES YOU MAY LEARN FROM:
- concept_archetype and trigger
- creative_format / visual_grammar
- first_frame_type and first_frame_source
- scene_count, word_count, duration_sec
- payoff_position_pct and open_loop_count
- template_count / real_video_count / still_image_count
- caption_mode and transition_style
- engagement_mode, comment_hook_present, outro_present
- asset_quality_min / asset_quality_avg

Do not recommend one house formula just because it won twice. Variety is protective. Prefer recommendations framed as experiments: "use more X for Y-type concepts" rather than "always use X".

OUTPUT ONLY JSON:
{
  "sample_size": <integer>,
  "confidence_note": "<specific limitation>",
  "guidance": [
    {
      "area": "topic"|"hook"|"structure"|"length"|"trigger"|"first_frame"|"visual_grammar"|"asset_quality"|"captions"|"engagement"|"payoff",
      "advice": "<specific next action or experiment>",
      "evidence": "<specific groups/videos and numbers>"
    }
  ],
  "avoid": ["<measurably weak pattern only>"]
}
Prefer 3 strong findings to 10 padded ones.`;

async function runStrategist(history) {
  const measured = history.filter((h) => h.metrics && typeof h.metrics.views === "number");
  const payload = measured.map((h) => ({
    topic: h.topic,
    hook: h.hook,
    title: h.title,
    trigger: h.trigger,
    creative_dna: h.creative_dna || {},
    metrics: h.metrics,
  }));

  if (!ANTHROPIC_KEY) throw new Error("runStrategist: ANTHROPIC_KEY is not set");

  const res = await axios.post(
    "https://api.anthropic.com/v1/messages",
    {
      model: STRATEGIST_MODEL,
      max_tokens: 2200,
      messages: [{ role: "user", content: STRATEGIST_PROMPT(JSON.stringify(payload, null, 2)) }],
    },
    {
      timeout: 60000,
      headers: {
        "x-api-key": ANTHROPIC_KEY,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
      },
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

async function ingestAnalytics(analyticsBody) {
  const metricsById = parseAnalytics(analyticsBody);
  const hist = await readJson(PERF_PATH, []);
  let updated = 0;
  const measured_at = new Date().toISOString();
  for (const h of hist) {
    const m = metricsById[h.video_id];
    if (m) {
      h.metrics = { ...m, measured_at };
      updated++;
    }
  }
  await writeJson(PERF_PATH, hist);

  let insights = null;
  try {
    insights = await runStrategist(hist);
  } catch (e) {
    insights = { error: String(e.message || e) };
  }
  return { updated, total: hist.length, insights };
}

async function getInsights() {
  return await readJson(INSIGHTS_PATH, {
    sample_size: 0,
    confidence_note: "No videos measured yet.",
    guidance: [],
    avoid: [],
  });
}

async function getMeasureIds({ maxDays = 60, limit = 200 } = {}) {
  const hist = await readJson(PERF_PATH, []);
  const cutoff = Date.now() - maxDays * 24 * 60 * 60 * 1000;
  return hist
    .filter((h) => h.video_id && (!h.published_at || new Date(h.published_at).getTime() >= cutoff))
    .map((h) => h.video_id)
    .slice(-limit);
}

module.exports = {
  logPublished,
  ingestAnalytics,
  getInsights,
  getMeasureIds,
  runStrategist,
  parseAnalytics,
  normalizeCreativeDna,
  PERF_PATH,
  INSIGHTS_PATH,
};
