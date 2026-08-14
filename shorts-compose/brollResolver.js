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
// people/places/things). Keys live in the compose service env alongside FAL_KEY.
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

async function fromWikipedia(subject) {
  if (!subject) return [];
  const d = await safeGet(
    `https://en.wikipedia.org/api/rest_v1/page/summary/${encodeURIComponent(subject)}`,
    { headers: { "User-Agent": "yt-shorts-broll/1.0 (contact: channel owner)" } }
  );
  const url = d?.originalimage?.source;
  if (!url) return [];
  return [
    {
      type: "image",
      url,
      thumb: d?.thumbnail?.source || url,
      alt: d?.title || subject,
      source: "wikipedia",
      attribution: `Image via Wikipedia: ${d?.title || subject}`,
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
              `This asset is meant to illustrate this scene: "${description}". ` +
              `On a scale of 0 to 100, how well does it actually match that scene? Reply with ONLY the number.`,
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
  const q = String(query || subject || description || "").trim();
  const desc = String(description || query || subject || "").trim();
  const subj = String(subject || query || "").trim();

  const groups = await Promise.all([
    fromPexelsPhotos(q),
    fromPexelsVideos(q),
    fromUnsplash(q),
    fromWikipedia(subj),
  ]);
  let candidates = groups.flat().filter((c) => c && c.url);
  if (!candidates.length) return { ok: false, reason: "no_candidates" };

  // cheap metadata pre-rank: keyword overlap of alt/title with the query, so the
  // vision model only has to score the most promising few (cost control).
  const qWords = q.toLowerCase().split(/\W+/).filter((w) => w.length > 2);
  const overlap = (alt) => {
    const a = String(alt || "").toLowerCase();
    return qWords.reduce((n, w) => n + (a.includes(w) ? 1 : 0), 0);
  };
  candidates.sort((a, b) => overlap(b.alt) - overlap(a.alt));

  // vision-score the top few and pick the best
  const top = candidates.slice(0, Math.max(1, VISION_TOP_N));
  const scored = [];
  for (const c of top) {
    const score = await scoreRelevance(c.thumb || c.url, desc);
    scored.push({ ...c, score });
  }
  scored.sort((a, b) => b.score - a.score);
  const best = scored[0];

  if (best && best.score >= SCORE_THRESHOLD) {
    return {
      ok: true,
      type: best.type,
      url: best.url,
      source: best.source,
      score: best.score,
      attribution: best.attribution || "",
    };
  }
  return { ok: false, reason: "below_threshold", best_score: best ? best.score : 0, best_source: best ? best.source : null };
}

module.exports = { resolveBroll };
