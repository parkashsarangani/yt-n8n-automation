// ---------------------------------------------------------------------------
// Multi-source real b-roll resolver.
//
// Collects candidate assets from several FREE real-media sources for a scene,
// ranks them by AI-vision relevance to the scene's description, and returns the
// single best real asset. AI image generation (fal) is the CALLER's fallback,
// used only when nothing here scores above the threshold - so real footage is
// the default and AI is the last resort.
//
// Sources (all free): Pexels photos, Pexels videos, Unsplash photos (photos
// only - Unsplash has no video), Wikipedia lead image (best for famous named
// people/places/things). Keys live in the compose service env (PEXELS_KEY,
// UNSPLASH_KEY, ANTHROPIC_KEY). There is no AI image generation.
// ---------------------------------------------------------------------------
const axios = require("axios");

const PEXELS_KEY = process.env.PEXELS_KEY || "";
const UNSPLASH_KEY = process.env.UNSPLASH_KEY || "";
const ANTHROPIC_KEY = process.env.ANTHROPIC_KEY || "";
const SCORE_THRESHOLD = Number(process.env.BROLL_SCORE_THRESHOLD || 75);
const VISION_MODEL = process.env.BROLL_VISION_MODEL || "claude-haiku-4-5-20251001";
const VISION_TOP_N = Number(process.env.BROLL_VISION_TOP_N || 3);

async function safeGet(url, config = {}, timeout = 15000) {
  try {
    const r = await axios.get(url, { timeout, ...config });
    return r.data;
  } catch {
    return null;
  }
}

// --- source adapters: each returns [{ type, url, thumb, alt, source, attribution }] ---

async function fromPexelsPhotos(query) {
  if (!PEXELS_KEY || !query) return [];
  const d = await safeGet(
    `https://api.pexels.com/v1/search?query=${encodeURIComponent(query)}&per_page=5&orientation=portrait&size=large`,
    { headers: { Authorization: PEXELS_KEY } }
  );
  return (d?.photos || [])
    .map((p) => ({
      type: "image",
      url: p.src?.original || p.src?.large2x || p.src?.large,
      thumb: p.src?.medium || p.src?.small,
      alt: p.alt || query,
      source: "pexels",
      attribution: "",
    }))
    .filter((c) => c.url);
}

async function fromPexelsVideos(query) {
  if (!PEXELS_KEY || !query) return [];
  const d = await safeGet(
    `https://api.pexels.com/videos/search?query=${encodeURIComponent(query)}&per_page=5&orientation=portrait&size=medium`,
    { headers: { Authorization: PEXELS_KEY } }
  );
  return (d?.videos || [])
    .map((v) => {
      const files = (v.video_files || []).filter((f) => f.link && f.height && f.width);
      // prefer portrait, then highest resolution
      const portrait = files.filter((f) => f.height >= f.width);
      const pool = portrait.length ? portrait : files;
      const best = pool.sort((a, b) => (b.height || 0) - (a.height || 0))[0];
      return best
        ? { type: "video", url: best.link, thumb: v.image, alt: query, source: "pexels_video", attribution: "" }
        : null;
    })
    .filter(Boolean);
}

async function fromUnsplash(query) {
  if (!UNSPLASH_KEY || !query) return [];
  const d = await safeGet(
    `https://api.unsplash.com/search/photos?query=${encodeURIComponent(query)}&per_page=5&orientation=portrait`,
    { headers: { Authorization: `Client-ID ${UNSPLASH_KEY}`, "Accept-Version": "v1" } }
  );
  return (d?.results || [])
    .map((p) => ({
      type: "image",
      url: p.urls?.full || p.urls?.regular,
      thumb: p.urls?.small || p.urls?.thumb,
      alt: p.alt_description || p.description || query,
      source: "unsplash",
      // Unsplash API guidelines require crediting the photographer + Unsplash
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
  return url ? { url, thumb: d?.thumbnail?.source || url, title: d?.title || title } : null;
}

async function fromWikipedia(subject) {
  if (!subject) return [];
  // 1) direct page summary (handles exact names + redirects, e.g. "Walt Disney")
  let hit = await wikiSummaryImage(subject);
  // 2) fallback: full-text search for the best-matching page, then its lead image
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
      alt: hit.title,
      source: "wikipedia",
      attribution: `Image via Wikipedia: ${hit.title}`,
    },
  ];
}

// --- AI-vision relevance score (0-100) for one candidate ---
async function scoreRelevance(imageUrl, description) {
  if (!ANTHROPIC_KEY || !imageUrl) return 0;
  const body = {
    model: VISION_MODEL,
    max_tokens: 16,
    messages: [
      {
        role: "user",
        content: [
          { type: "image", source: { type: "url", url: imageUrl } },
          {
            type: "text",
            text:
              `This image should clearly depict or directly relate to: "${description}". ` +
              `On a scale of 0 to 100, how well does it? A generic or unrelated stock photo scores low; ` +
              `an image of the actual named subject scores high. Reply with ONLY the number.`,
          },
        ],
      },
    ],
  };
  try {
    const r = await axios.post("https://api.anthropic.com/v1/messages", body, {
      timeout: 20000,
      headers: { "x-api-key": ANTHROPIC_KEY, "anthropic-version": "2023-06-01", "content-type": "application/json" },
    });
    const txt = (r.data?.content || []).map((b) => (b && b.text) || "").join(" ");
    const m = txt.match(/\d{1,3}/);
    const s = m ? parseInt(m[0], 10) : 0;
    return Math.max(0, Math.min(100, isNaN(s) ? 0 : s));
  } catch {
    return 0;
  }
}

// --- main resolver ---
async function resolveBroll({ query, subject, description }) {
  const q = String(query || subject || description || "").trim(); // stock search terms
  const desc = String(description || query || "").trim(); // scene description
  const subj = String(subject || "").trim(); // the EXACT named entity (e.g. "Walt Disney"), or ""
  // Score against the named subject when we have one, so a real Wikipedia photo
  // of Walt Disney beats a generic pencil that only matched the stock query.
  const target = subj || desc;

  const groups = await Promise.all([
    fromPexelsPhotos(q),
    fromPexelsVideos(q),
    fromUnsplash(q),
    fromWikipedia(subj),
  ]);
  let candidates = groups.flat().filter((c) => c && c.url);
  if (!candidates.length) {
    // No AI fallback anymore, so never leave a scene without a real image:
    // last-resort broad Pexels photo search on the first keyword.
    const kw = q.split(/\s+/)[0] || "abstract background";
    candidates = (await fromPexelsPhotos(kw)).filter((c) => c && c.url);
    if (!candidates.length) return { ok: false, reason: "no_candidates" };
  }

  // Pre-rank the stock pool by metadata overlap with the target, but ALWAYS keep
  // the Wikipedia (named-subject) hit in the scored set - it IS the subject, and
  // must get a chance to win over a loosely-matching stock photo.
  const tWords = target.toLowerCase().split(/\W+/).filter((w) => w.length > 2);
  const overlap = (alt) => {
    const a = String(alt || "").toLowerCase();
    return tWords.reduce((n, w) => n + (a.includes(w) ? 1 : 0), 0);
  };
  const wiki = candidates.filter((c) => c.source === "wikipedia");
  const rest = candidates.filter((c) => c.source !== "wikipedia").sort((a, b) => overlap(b.alt) - overlap(a.alt));

  // vision-score the Wikipedia hit + the best stock candidates, then pick the best
  const top = [...wiki, ...rest].slice(0, Math.max(1, VISION_TOP_N));
  const scored = [];
  for (const c of top) {
    const score = await scoreRelevance(c.thumb || c.url, target);
    scored.push({ ...c, score });
  }
  scored.sort((a, b) => b.score - a.score);
  const best = scored[0];

  // fal/AI generation has been removed: real footage is the ONLY source, so
  // always return the best real asset we found. We prefer >= threshold, but
  // rather than an AI fallback we use the top-scored real candidate even below
  // it - a slightly loose real photo beats an empty scene.
  return {
    ok: true,
    type: best.type,
    url: best.url,
    source: best.source,
    score: best.score,
    below_threshold: best.score < SCORE_THRESHOLD,
    attribution: best.attribution || "",
  };
}

module.exports = { resolveBroll };
