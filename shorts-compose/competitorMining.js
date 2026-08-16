// ---------------------------------------------------------------------------
// Competitor outlier mining.
//
// The feedback loop (feedbackLoop.js) learns only from THIS channel's own
// videos. This module adds the missing half: it watches a curated list of
// comparable fact/curiosity Shorts channels and surfaces what is BREAKING OUT
// for them right now, so the topic generator can lean toward proven subjects
// and angles instead of re-deriving everything from our own throttled numbers.
//
// Method, once a week:
//   1. Resolve each watchlist channel (competitors.json) to its uploads
//      playlist via the YouTube Data API (API key, public data only).
//   2. Pull recent uploads, keep only SHORTS (duration <= SHORT_MAX_SEC).
//   3. Per channel, compute the median view count of its recent shorts and
//      flag any short that beats that median by >= OUTLIER_MULTIPLE (and clears
//      a floor of real reach). "Outlier" is normalized PER CHANNEL, so a small
//      channel's breakout is judged against itself, not against a 20M-sub giant.
//   4. Distill the outliers' TITLES into transferable topic/angle signals with
//      Claude - never copying a title, only extracting what is working.
//   5. Persist competitor_signals.json for the topic generator to read.
//
// Discipline mirrors the strategist: signals are inspiration, not commands, and
// the distiller is told to drop anything off-format (lists, compilations, non
// mass-appeal, medical) so it never pulls the channel off its own strategy.
// ---------------------------------------------------------------------------
const fs = require("fs");
const fsp = require("fs/promises");
const path = require("path");
const axios = require("axios");

const DATA_DIR = path.dirname(process.env.TOPIC_HISTORY_PATH || "/app/data/topic_history.json");
const SIGNALS_PATH = path.join(DATA_DIR, "competitor_signals.json");
const WATCHLIST_PATH = path.join(__dirname, "competitors.json");

const YT_KEY = process.env.YOUTUBE_API_KEY || "";
const ANTHROPIC_KEY = process.env.ANTHROPIC_KEY || "";
const DISTILL_MODEL = process.env.COMPETITOR_DISTILL_MODEL || process.env.STRATEGIST_MODEL || "claude-sonnet-5";

const WINDOW_DAYS = Number(process.env.COMPETITOR_WINDOW_DAYS || 45);
// YouTube's own Shorts cutoff is 180s. Use the full 180 so we capture the many
// fact channels that post 90-180s (often multi-fact compilation) Shorts - a 90s
// cap left most of them at 0. Single-fact channels (like Zack D. Films, ~20-40s)
// still give the richest topic signal because their title IS the fact.
const SHORT_MAX_SEC = Number(process.env.COMPETITOR_SHORT_MAX_SEC || 180);
const OUTLIER_MULTIPLE = Number(process.env.COMPETITOR_OUTLIER_MULTIPLE || 3);
const OUTLIER_MIN_VIEWS = Number(process.env.COMPETITOR_OUTLIER_MIN_VIEWS || 50000);
const MIN_SHORTS_FOR_BASELINE = Number(process.env.COMPETITOR_MIN_SHORTS || 5);
const MAX_OUTLIERS = Number(process.env.COMPETITOR_MAX_OUTLIERS || 30);
const UPLOADS_TO_SCAN = Number(process.env.COMPETITOR_UPLOADS_SCAN || 100); // per channel

const YT_API = "https://www.googleapis.com/youtube/v3";

async function writeJson(p, data) {
  await fsp.mkdir(path.dirname(p), { recursive: true });
  await fsp.writeFile(p, JSON.stringify(data, null, 2));
}
async function readJson(p, fallback) {
  try { if (!fs.existsSync(p)) return fallback; return JSON.parse(await fsp.readFile(p, "utf8")); }
  catch { return fallback; }
}

// One comma-separated token -> a watchlist entry. A token is either a channel
// ID ("UC...." 24 chars) or a handle ("@name" or bare "name").
function parseChannelToken(tok) {
  const t = String(tok || "").trim();
  if (!t) return null;
  if (/^UC[A-Za-z0-9_-]{22}$/.test(t)) return { channel_id: t, name: t };
  return { handle: t, name: t }; // resolveChannel strips a leading @ if present
}

// Watchlist source, in priority order:
//   1. COMPETITOR_CHANNELS env - a comma-separated list of @handles and/or
//      UC... channel IDs, set via a GitHub secret so the list is configurable
//      without a code change. It is an env var, so a change to the secret takes
//      effect on the next deploy (container restart), not instantly.
//   2. competitors.json - the curated default baked into the image.
function loadWatchlist() {
  const env = (process.env.COMPETITOR_CHANNELS || "").trim();
  if (env) {
    const list = env.split(",").map(parseChannelToken).filter(Boolean);
    if (list.length) return list;
  }
  try {
    const raw = JSON.parse(fs.readFileSync(WATCHLIST_PATH, "utf8"));
    return Array.isArray(raw.channels) ? raw.channels : [];
  } catch { return []; }
}

// ISO-8601 duration (PT#H#M#S) -> seconds
function isoDurationToSec(iso) {
  if (!iso || typeof iso !== "string") return null;
  const m = iso.match(/^PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?$/);
  if (!m) return null;
  return (Number(m[1] || 0) * 3600) + (Number(m[2] || 0) * 60) + Number(m[3] || 0);
}

function median(nums) {
  if (!nums.length) return 0;
  const s = [...nums].sort((a, b) => a - b);
  const mid = Math.floor(s.length / 2);
  return s.length % 2 ? s[mid] : (s[mid - 1] + s[mid]) / 2;
}

async function ytGet(endpoint, params) {
  const r = await axios.get(`${YT_API}/${endpoint}`, {
    params: { key: YT_KEY, ...params },
    timeout: 20000,
  });
  return r.data;
}

// Resolve one watchlist entry to { id, uploads, title, subs } or null.
async function resolveChannel(entry) {
  try {
    let data;
    if (entry.channel_id) {
      data = await ytGet("channels", { part: "contentDetails,statistics,snippet", id: entry.channel_id });
    } else if (entry.handle) {
      const handle = String(entry.handle).replace(/^@/, "");
      data = await ytGet("channels", { part: "contentDetails,statistics,snippet", forHandle: handle });
    } else {
      return null;
    }
    const item = data.items && data.items[0];
    if (!item) return null;
    return {
      id: item.id,
      uploads: item.contentDetails.relatedPlaylists.uploads,
      title: item.snippet.title,
      subs: Number(item.statistics.subscriberCount || 0),
    };
  } catch { return null; }
}

// Recent uploads within the window -> list of videoIds.
async function recentUploadIds(uploadsPlaylist) {
  const cutoff = Date.now() - WINDOW_DAYS * 24 * 60 * 60 * 1000;
  const ids = [];
  let pageToken;
  // one or two pages is plenty for a month of a shorts channel
  for (let page = 0; page < Math.ceil(UPLOADS_TO_SCAN / 50); page++) {
    const data = await ytGet("playlistItems", {
      part: "contentDetails", playlistId: uploadsPlaylist, maxResults: 50, pageToken,
    });
    for (const it of data.items || []) {
      const pub = new Date(it.contentDetails.videoPublishedAt || 0).getTime();
      if (pub >= cutoff) ids.push(it.contentDetails.videoId);
    }
    pageToken = data.nextPageToken;
    if (!pageToken) break;
    // stop early if the last page already fell entirely outside the window
    const last = data.items && data.items[data.items.length - 1];
    if (last && new Date(last.contentDetails.videoPublishedAt || 0).getTime() < cutoff) break;
  }
  return ids;
}

// videos.list in batches of 50 -> [{ id, title, views, sec, published }]
async function videoStats(ids) {
  const out = [];
  for (let i = 0; i < ids.length; i += 50) {
    const batch = ids.slice(i, i + 50);
    const data = await ytGet("videos", { part: "statistics,contentDetails,snippet", id: batch.join(",") });
    for (const v of data.items || []) {
      out.push({
        id: v.id,
        title: v.snippet.title,
        views: Number(v.statistics.viewCount || 0),
        sec: isoDurationToSec(v.contentDetails.duration),
        published: v.snippet.publishedAt,
      });
    }
  }
  return out;
}

// Core: scan every channel, return { outliers, scanned, unresolved }.
async function scanCompetitors() {
  const watchlist = loadWatchlist();
  const scanned = [];
  const unresolved = [];
  const outliers = [];

  for (const entry of watchlist) {
    const ch = await resolveChannel(entry);
    if (!ch) { unresolved.push(entry.name || entry.handle || entry.channel_id || "unknown"); continue; }

    const ids = await recentUploadIds(ch.uploads);
    const vids = await videoStats(ids);
    const shorts = vids.filter((v) => v.sec != null && v.sec <= SHORT_MAX_SEC && v.views > 0);
    scanned.push({ name: ch.title, subs: ch.subs, recent_shorts: shorts.length });

    if (shorts.length < MIN_SHORTS_FOR_BASELINE) continue; // no reliable baseline
    const med = median(shorts.map((v) => v.views));
    if (med <= 0) continue;

    for (const v of shorts) {
      const multiple = v.views / med;
      if (multiple >= OUTLIER_MULTIPLE && v.views >= OUTLIER_MIN_VIEWS) {
        outliers.push({
          channel: ch.title,
          title: v.title,
          views: v.views,
          outlier_multiple: Number(multiple.toFixed(1)),
          duration_sec: v.sec,
          published_at: v.published,
          url: `https://www.youtube.com/shorts/${v.id}`,
        });
      }
    }
  }

  outliers.sort((a, b) => b.outlier_multiple - a.outlier_multiple);
  return { outliers: outliers.slice(0, MAX_OUTLIERS), scanned, unresolved };
}

const DISTILL_PROMPT = (outliersJson) =>
`These are the breakout Shorts (each beat its OWN channel's median views by the shown multiple) from a watchlist of fact/curiosity channels comparable to ours. Ours is a faceless channel that posts ONE surprising, mass-appeal fact per Short (20-30s), English, no medical topics, no biographies, subjects a general audience instantly recognizes.

BREAKOUT SHORTS (title, channel, views, outlier_multiple):
${outliersJson}

Your job: extract the transferable PATTERNS that made these break out, as inspiration for our own topic generator. This is signal-mining, not copying.

RULES:
- NEVER output a competitor's title to be reused. Extract the underlying subject + angle, restated generically.
- DROP anything off-format for us: listicles/top-10s, multi-fact compilations, medical/health, channel-specific series, anything not a single mass-appeal fact.
- A pattern is only worth reporting if it would plausibly work as a single surprising fact for a broad audience. If the outlier is popular for a reason we cannot reproduce (a specific creator's character, a trend we cannot ride), skip it.
- Prefer patterns that recur across multiple outliers - those are the strongest signal - and say so.
- Tie each signal to the outlier(s) that support it.

OUTPUT - respond with ONLY a JSON object, no prose, no markdown fences:
{
  "summary": "<2-3 sentences: what is breaking out for comparable channels right now>",
  "signals": [
    {
      "subject_category": "<e.g. human body, space, famous person, everyday object, money, history>",
      "angle": "<the transferable angle/shape, generically stated - what makes it hit>",
      "likely_trigger": "curiosity_gap|disbelief|fear_stakes|scale_shock|taboo_secret",
      "why_it_works": "<one line>",
      "supported_by": "<how many outliers / which channels, brief>"
    }
  ],
  "avoid": [ "<any pattern that looks tempting but is off-format or non-reproducible for us>" ]
}
Prefer 4-8 strong signals to a long padded list. Every signal is read by our topic generator and acted on.`;

// Robust JSON-object extraction from an LLM reply: strips code fences, then
// walks balanced braces from the first "{" so trailing prose does not break the
// parse and a truncated tail is reported as such rather than as a cryptic
// "Expected ',' or ']'" from a naive lastIndexOf('}') slice.
function extractJsonObject(text) {
  let s = String(text || "").trim();
  if (s.startsWith("```")) s = s.replace(/^```(?:json)?\s*/i, "").replace(/```\s*$/, "").trim();
  const at = s.indexOf("{");
  if (at < 0) throw new Error("no JSON object in reply: " + s.slice(0, 200));
  let depth = 0, inStr = false, esc = false;
  for (let i = at; i < s.length; i++) {
    const ch = s[i];
    if (inStr) {
      if (esc) esc = false;
      else if (ch === "\\") esc = true;
      else if (ch === '"') inStr = false;
    } else if (ch === '"') inStr = true;
    else if (ch === "{") depth++;
    else if (ch === "}") { depth--; if (depth === 0) return JSON.parse(s.slice(at, i + 1)); }
  }
  throw new Error("JSON object not closed - likely truncated by max_tokens: ..." + s.slice(Math.max(at, s.length - 160)));
}

async function distillSignals(outliers) {
  if (!outliers.length) {
    return { summary: "No breakout Shorts found in the window.", signals: [], avoid: [] };
  }
  if (!ANTHROPIC_KEY) throw new Error("distillSignals: ANTHROPIC_KEY is not set");
  const compact = outliers.map((o) => ({
    title: o.title, channel: o.channel, views: o.views, outlier_multiple: o.outlier_multiple,
  }));
  const res = await axios.post(
    "https://api.anthropic.com/v1/messages",
    {
      model: DISTILL_MODEL,
      max_tokens: Number(process.env.COMPETITOR_DISTILL_MAX_TOKENS || 4000),
      messages: [{ role: "user", content: DISTILL_PROMPT(JSON.stringify(compact, null, 2)) }],
    },
    {
      timeout: 90000,
      headers: { "x-api-key": ANTHROPIC_KEY, "anthropic-version": "2023-06-01", "content-type": "application/json" },
    }
  );
  if (res.data && res.data.stop_reason === "max_tokens") {
    throw new Error("distiller reply hit max_tokens - raise COMPETITOR_DISTILL_MAX_TOKENS");
  }
  const text = (res.data.content || []).map((b) => (b && b.text) || "").join("");
  return extractJsonObject(text);
}

// Full run: scan -> distill -> persist. Returns a summary for the caller.
async function mine() {
  if (!YT_KEY) throw new Error("mine: YOUTUBE_API_KEY is not set");
  const { outliers, scanned, unresolved } = await scanCompetitors();
  // Distillation is best-effort: a bad Claude reply must NOT throw away a good
  // scan. Persist the raw outliers regardless so we always keep the evidence.
  let distilled = { summary: "", signals: [], avoid: [] };
  let distill_error = null;
  try { distilled = await distillSignals(outliers); }
  catch (e) { distill_error = String((e && e.message) || e); }
  const signals = {
    generated_at: new Date().toISOString(),
    window_days: WINDOW_DAYS,
    channels_scanned: scanned.length,
    channels_unresolved: unresolved,
    outliers_found: outliers.length,
    summary: distilled.summary || "",
    signals: distilled.signals || [],
    avoid: distilled.avoid || [],
    distill_error, // null on success
    raw_outliers: outliers, // kept for transparency / manual review
  };
  await writeJson(SIGNALS_PATH, signals);
  return {
    channels_scanned: scanned.length,
    channels_unresolved: unresolved,
    outliers_found: outliers.length,
    signal_count: (distilled.signals || []).length,
    distill_error,
    scanned,
  };
}

async function getSignals() {
  return await readJson(SIGNALS_PATH, {
    generated_at: null, window_days: WINDOW_DAYS, channels_scanned: 0,
    outliers_found: 0, summary: "No competitor scan has run yet.", signals: [], avoid: [], raw_outliers: [],
  });
}

module.exports = {
  mine, getSignals, scanCompetitors, distillSignals, extractJsonObject,
  isoDurationToSec, median, loadWatchlist, SIGNALS_PATH,
};
