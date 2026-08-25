// ---------------------------------------------------------------------------
// Multi-source real b-roll resolver.
//
// V3 creative commissioning behavior:
// - oversample real-media candidates instead of settling for the first match
// - score visual arrest + phone-size clarity, not semantic relevance alone
// - use a stricter threshold for the first frame
// - try alternate search queries supplied by the visual director
// - FAIL CLOSED when the best asset is weak; weak stock is not publishable
// ---------------------------------------------------------------------------
const axios = require("axios");

const PEXELS_KEY = process.env.PEXELS_KEY || "";
const UNSPLASH_KEY = process.env.UNSPLASH_KEY || "";
const OPENAI_KEY = process.env.OPENAI_KEY || "";
const SCORE_THRESHOLD = Number(process.env.BROLL_SCORE_THRESHOLD || 82);
const FIRST_FRAME_THRESHOLD = Number(process.env.BROLL_FIRST_FRAME_THRESHOLD || 88);
const VISION_MODEL = process.env.BROLL_VISION_MODEL || "gpt-5.6-luna";
const VISION_TOP_N = Number(process.env.BROLL_VISION_TOP_N || 8);
const SOURCE_PER_QUERY = Number(process.env.BROLL_SOURCE_PER_QUERY || 12);
const MAX_SEARCH_QUERIES = Number(process.env.BROLL_MAX_SEARCH_QUERIES || 4);

async function safeGet(url, config = {}, timeout = 15000) {
  try {
    const r = await axios.get(url, { timeout, ...config });
    return r.data;
  } catch {
    return null;
  }
}

function uniqStrings(values) {
  const seen = new Set();
  const out = [];
  for (const raw of values || []) {
    const v = String(raw || "").trim();
    const key = v.toLowerCase();
    if (!v || seen.has(key)) continue;
    seen.add(key);
    out.push(v);
  }
  return out;
}

function dedupeCandidates(candidates) {
  const seen = new Set();
  return (candidates || []).filter((c) => {
    if (!c || !c.url || seen.has(c.url)) return false;
    seen.add(c.url);
    return true;
  });
}

async function fromPexelsPhotos(query) {
  if (!PEXELS_KEY || !query) return [];
  const d = await safeGet(
    `https://api.pexels.com/v1/search?query=${encodeURIComponent(query)}&per_page=${SOURCE_PER_QUERY}&orientation=portrait&size=large`,
    { headers: { Authorization: PEXELS_KEY } }
  );
  return (d?.photos || [])
    .map((p) => ({
      type: "image",
      url: p.src?.original || p.src?.large2x || p.src?.large,
      thumb: p.src?.medium || p.src?.small,
      width: p.width || null,
      height: p.height || null,
      alt: p.alt || query,
      query,
      source: "pexels",
      attribution: "",
    }))
    .filter((c) => c.url);
}

async function fromPexelsVideos(query) {
  if (!PEXELS_KEY || !query) return [];
  const d = await safeGet(
    `https://api.pexels.com/videos/search?query=${encodeURIComponent(query)}&per_page=${SOURCE_PER_QUERY}&orientation=portrait&size=medium`,
    { headers: { Authorization: PEXELS_KEY } }
  );
  return (d?.videos || [])
    .map((v) => {
      const files = (v.video_files || []).filter((f) => f.link && f.height && f.width);
      const portrait = files.filter((f) => f.height >= f.width);
      const pool = portrait.length ? portrait : files;
      const best = [...pool].sort((a, b) => (b.height || 0) - (a.height || 0))[0];
      return best
        ? {
            type: "video",
            url: best.link,
            thumb: v.image,
            width: best.width || null,
            height: best.height || null,
            alt: query,
            query,
            source: "pexels_video",
            attribution: "",
          }
        : null;
    })
    .filter(Boolean);
}

async function fromUnsplash(query) {
  if (!UNSPLASH_KEY || !query) return [];
  const d = await safeGet(
    `https://api.unsplash.com/search/photos?query=${encodeURIComponent(query)}&per_page=${SOURCE_PER_QUERY}&orientation=portrait`,
    { headers: { Authorization: `Client-ID ${UNSPLASH_KEY}`, "Accept-Version": "v1" } }
  );
  return (d?.results || [])
    .map((p) => ({
      type: "image",
      url: p.urls?.full || p.urls?.regular,
      thumb: p.urls?.small || p.urls?.thumb,
      width: p.width || null,
      height: p.height || null,
      alt: p.alt_description || p.description || query,
      query,
      source: "unsplash",
      attribution: `Photo by ${p.user?.name || "an artist"} on Unsplash`,
    }))
    .filter((c) => c.url);
}

async function wikiSummaryImage(title) {
  const d = await safeGet(
    `https://en.wikipedia.org/api/rest_v1/page/summary/${encodeURIComponent(title)}`,
    { headers: { "User-Agent": "yt-shorts-broll/1.0 (contact: channel owner)" } }
  );
  const url = d?.originalimage?.source;
  return url
    ? {
        url,
        thumb: d?.thumbnail?.source || url,
        title: d?.title || title,
        width: d?.originalimage?.width || null,
        height: d?.originalimage?.height || null,
      }
    : null;
}

async function fromWikipedia(subject) {
  if (!subject) return [];
  let hit = await wikiSummaryImage(subject);
  if (!hit) {
    const s = await safeGet(
      `https://en.wikipedia.org/w/api.php?action=query&list=search&srsearch=${encodeURIComponent(subject)}&srlimit=1&format=json&origin=*`,
      { headers: { "User-Agent": "yt-shorts-broll/1.0" } }
    );
    const title = s?.query?.search?.[0]?.title;
    if (title) hit = await wikiSummaryImage(title);
  }
  if (!hit) return [];
  return [
    {
      type: "image",
      url: hit.url,
      thumb: hit.thumb,
      width: hit.width,
      height: hit.height,
      alt: hit.title,
      query: subject,
      source: "wikipedia",
      attribution: `Image via Wikipedia: ${hit.title}`,
    },
  ];
}

async function fetchImageAsBase64(url) {
  try {
    const r = await axios.get(url, {
      timeout: 15000,
      responseType: "arraybuffer",
      headers: { "User-Agent": "yt-shorts-broll/1.0 (contact: channel owner)" },
    });
    const buf = Buffer.from(r.data);
    if (!buf.length || buf.length > 4.5 * 1024 * 1024) return null;
    const mime = String(r.headers?.["content-type"] || "image/jpeg").split(";")[0].trim();
    if (!mime.startsWith("image/")) return null;
    return { mime, data: buf.toString("base64") };
  } catch {
    return null;
  }
}

function parseScoreJson(text) {
  const raw = String(text || "").trim().replace(/^```(?:json)?\s*/i, "").replace(/```\s*$/, "");
  const a = raw.indexOf("{");
  const b = raw.lastIndexOf("}");
  if (a >= 0 && b > a) {
    try { return JSON.parse(raw.slice(a, b + 1)); } catch { /* fall through */ }
  }
  const n = raw.match(/\d{1,3}/);
  const v = n ? Math.max(0, Math.min(100, Number(n[0]))) : 0;
  return {
    relevance: v,
    scroll_stop: v,
    mobile_clarity: v,
    composition: v,
    motion_energy: v,
    uniqueness: v,
    overall: v,
  };
}

function clampScore(v) {
  const n = Number(v);
  return Number.isFinite(n) ? Math.max(0, Math.min(100, Math.round(n))) : 0;
}

async function scoreVisualCandidate(candidate, target, { firstFrame = false, creativeFormat = "" } = {}) {
  if (!OPENAI_KEY || !candidate?.thumb && !candidate?.url) {
    return {
      relevance: 0,
      scroll_stop: 0,
      mobile_clarity: 0,
      composition: 0,
      motion_energy: candidate?.type === "video" ? 55 : 35,
      uniqueness: 0,
      overall: 0,
    };
  }

  const encoded = await fetchImageAsBase64(candidate.thumb || candidate.url);
  const imageUrl = encoded
    ? `data:${encoded.mime};base64,${encoded.data}`
    : candidate.thumb || candidate.url;

  const body = {
    model: VISION_MODEL,
    max_completion_tokens: 180,
    reasoning_effort: "none",
    response_format: { type: "json_object" },
    messages: [
      {
        role: "user",
        content: [
          { type: "image_url", image_url: { url: imageUrl } },
          {
            type: "text",
            text:
              `Commission this ${candidate.type} for a vertical YouTube Short. It must depict: "${target}". ` +
              `Creative format: "${creativeFormat || "unspecified"}". ${firstFrame ? "This is the FIRST FRAME and must stop a swipe before audio is understood." : "This is a supporting scene and must add visual meaning, not generic filler."} ` +
              `Score 0-100 for relevance, scroll_stop, mobile_clarity, composition, motion_energy, uniqueness, and overall. ` +
              `For a video candidate, infer motion potential from the thumbnail/type but do not pretend to have watched the clip. ` +
              `A semantically correct but ordinary stock image should score below 75 overall. ` +
              `Return ONLY JSON: {"relevance":0,"scroll_stop":0,"mobile_clarity":0,"composition":0,"motion_energy":0,"uniqueness":0,"overall":0}`,
          },
        ],
      },
    ],
  };

  try {
    const r = await axios.post("https://api.openai.com/v1/chat/completions", body, {
      timeout: 25000,
      headers: { Authorization: `Bearer ${OPENAI_KEY}`, "content-type": "application/json" },
    });
    const txt = r.data?.choices?.[0]?.message?.content || "";
    const parsed = parseScoreJson(txt);
    const result = {
      relevance: clampScore(parsed.relevance),
      scroll_stop: clampScore(parsed.scroll_stop),
      mobile_clarity: clampScore(parsed.mobile_clarity),
      composition: clampScore(parsed.composition),
      motion_energy: clampScore(parsed.motion_energy),
      uniqueness: clampScore(parsed.uniqueness),
      overall: clampScore(parsed.overall),
    };
    // Prevent a flashy-but-irrelevant or illegible asset from winning on a high
    // self-reported overall score.
    const hardCeiling = Math.min(result.relevance, result.mobile_clarity) + 10;
    result.overall = Math.min(result.overall, hardCeiling, 100);
    return result;
  } catch {
    return {
      relevance: 0,
      scroll_stop: 0,
      mobile_clarity: 0,
      composition: 0,
      motion_energy: candidate?.type === "video" ? 55 : 35,
      uniqueness: 0,
      overall: 0,
    };
  }
}

function metadataOverlap(candidate, target) {
  const targetWords = String(target || "").toLowerCase().split(/\W+/).filter((w) => w.length > 2);
  const hay = `${candidate?.alt || ""} ${candidate?.query || ""}`.toLowerCase();
  return targetWords.reduce((n, w) => n + (hay.includes(w) ? 1 : 0), 0);
}

async function collectCandidates(queries, subject) {
  const jobs = [];
  for (const q of queries) {
    jobs.push(fromPexelsPhotos(q), fromPexelsVideos(q), fromUnsplash(q));
  }
  jobs.push(fromWikipedia(subject));
  const groups = await Promise.all(jobs);
  return dedupeCandidates(groups.flat());
}

async function resolveBroll({
  query,
  queries,
  alternate_queries,
  subject,
  description,
  scene_index,
  first_frame,
  creative_format,
} = {}) {
  const desc = String(description || query || subject || "").trim();
  const subj = String(subject || "").trim();
  const target = subj || desc;
  const queryList = uniqStrings([
    query,
    ...(Array.isArray(queries) ? queries : []),
    ...(Array.isArray(alternate_queries) ? alternate_queries : []),
    subj,
  ]).slice(0, MAX_SEARCH_QUERIES);

  if (!queryList.length || !target) {
    return { ok: false, reason: "missing_search_target" };
  }

  const isFirstFrame = first_frame === true || Number(scene_index) === 0;
  const threshold = isFirstFrame ? FIRST_FRAME_THRESHOLD : SCORE_THRESHOLD;
  const candidates = await collectCandidates(queryList, subj);
  if (!candidates.length) {
    return { ok: false, reason: "no_candidates", threshold, queries_tried: queryList };
  }

  const wiki = candidates.filter((c) => c.source === "wikipedia");
  const videos = candidates.filter((c) => c.type === "video").sort((a, b) => metadataOverlap(b, target) - metadataOverlap(a, target));
  const photos = candidates.filter((c) => c.type !== "video" && c.source !== "wikipedia").sort((a, b) => metadataOverlap(b, target) - metadataOverlap(a, target));

  // Keep the exact named-subject candidate, then deliberately mix motion and
  // stills in the scored set instead of allowing one source to monopolize it.
  const mixed = [];
  const add = (c) => { if (c && !mixed.some((x) => x.url === c.url)) mixed.push(c); };
  wiki.forEach(add);
  for (let i = 0; mixed.length < VISION_TOP_N && (i < videos.length || i < photos.length); i++) {
    add(videos[i]);
    if (mixed.length < VISION_TOP_N) add(photos[i]);
  }
  for (const c of candidates) {
    if (mixed.length >= VISION_TOP_N) break;
    add(c);
  }

  const scored = [];
  for (const c of mixed.slice(0, VISION_TOP_N)) {
    const dimensions = await scoreVisualCandidate(c, target, {
      firstFrame: isFirstFrame,
      creativeFormat: creative_format,
    });
    scored.push({ ...c, ...dimensions, score: dimensions.overall });
  }
  scored.sort((a, b) => b.score - a.score);
  const best = scored[0];

  if (!best || best.score < threshold) {
    return {
      ok: false,
      reason: "below_quality_threshold",
      threshold,
      first_frame: isFirstFrame,
      queries_tried: queryList,
      candidate_count: candidates.length,
      scored_count: scored.length,
      best_score: best?.score || 0,
      best_candidate: best
        ? {
            type: best.type,
            source: best.source,
            score: best.score,
            relevance: best.relevance,
            scroll_stop: best.scroll_stop,
            mobile_clarity: best.mobile_clarity,
          }
        : null,
    };
  }

  return {
    ok: true,
    type: best.type,
    url: best.url,
    source: best.source,
    score: best.score,
    relevance: best.relevance,
    scroll_stop: best.scroll_stop,
    mobile_clarity: best.mobile_clarity,
    composition: best.composition,
    motion_energy: best.motion_energy,
    uniqueness: best.uniqueness,
    threshold,
    first_frame: isFirstFrame,
    selected_query: best.query || queryList[0],
    candidate_count: candidates.length,
    attribution: best.attribution || "",
  };
}

module.exports = {
  resolveBroll,
  parseScoreJson,
  uniqStrings,
  dedupeCandidates,
  metadataOverlap,
};
