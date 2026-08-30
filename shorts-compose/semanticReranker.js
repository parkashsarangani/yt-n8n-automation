// LOCAL_CLIP_RERANK_V4 / RETRIEVAL_RECALL_PHASE2 / MULTIFRAME_VIDEO_RERANK_V1
// Cheap local semantic retrieval before paid multimodal verification.
const LOCAL_RERANK_ENABLED = String(process.env.BROLL_LOCAL_RERANK_ENABLED || "true").toLowerCase() !== "false";
const LOCAL_RERANK_MODEL = process.env.BROLL_LOCAL_RERANK_MODEL || "Xenova/clip-vit-base-patch32";
const LOCAL_RERANK_CANDIDATES = Math.max(4, Number(process.env.BROLL_LOCAL_RERANK_CANDIDATES || 16));
const LOCAL_RERANK_TIMEOUT_MS = Math.max(1000, Number(process.env.BROLL_LOCAL_RERANK_TIMEOUT_MS || 18000));
let classifierPromise = null;

async function withTimeout(promise, ms) {
  let timer;
  try {
    return await Promise.race([
      promise,
      new Promise((resolve) => { timer = setTimeout(() => resolve(null), Math.max(1, ms)); }),
    ]);
  } finally {
    if (timer) clearTimeout(timer);
  }
}

async function getClassifier() {
  if (!LOCAL_RERANK_ENABLED) return null;
  if (!classifierPromise) {
    classifierPromise = (async () => {
      try {
        const mod = await import("@huggingface/transformers");
        if (mod.env) {
          mod.env.cacheDir = process.env.HF_CACHE_DIR || "/app/data/hf-cache";
          mod.env.allowRemoteModels = true;
        }
        return await mod.pipeline("zero-shot-image-classification", LOCAL_RERANK_MODEL);
      } catch (err) {
        console.warn("[broll] local CLIP unavailable; metadata-only coarse rank:", err?.message || err);
        return null;
      }
    })();
  }
  return classifierPromise;
}

function lexicalScore(candidate, target) {
  const words = String(target || "").toLowerCase().match(/[a-z0-9][a-z0-9'-]{2,}/g) || [];
  const hay = `${candidate?.alt || ""} ${candidate?.query || ""}`.toLowerCase();
  return words.reduce((n, w) => n + (hay.includes(w) ? 1 : 0), 0);
}

async function localSemanticRerank(candidates, target, acceptable = []) {
  const base = [...(candidates || [])].sort((a, b) => lexicalScore(b, target) - lexicalScore(a, target));
  if (!base.length) return base;
  const deadline = Date.now() + LOCAL_RERANK_TIMEOUT_MS;
  const classifier = await withTimeout(getClassifier(), Math.max(250, deadline - Date.now()));
  if (!classifier) return base;
  const positives = [...new Set([target, ...(acceptable || [])].map((x) => String(x || "").trim()).filter(Boolean))].slice(0, 4);
  const labels = [...positives, "generic unrelated stock footage", "generic background scenery"];
  for (const c of base.slice(0, LOCAL_RERANK_CANDIDATES)) {
    const remaining = deadline - Date.now();
    if (remaining < 300) break;
    const image = c?.thumb || (c?.type === "image" ? c?.url : null);
    if (!image) continue;
    try {
      const output = await withTimeout(classifier(image, labels), remaining);
      const matches = Array.isArray(output) ? output.filter((x) => positives.includes(x?.label)) : [];
      const best = matches.reduce((m, x) => Math.max(m, Number(x?.score) || 0), 0);
      if (best > 0) c.local_similarity = Math.round(best * 100);
    } catch { /* keep metadata rank */ }
  }
  return base.sort((a, b) => {
    const ca = Number.isFinite(Number(a.local_similarity)) ? Number(a.local_similarity) : -1;
    const cb = Number.isFinite(Number(b.local_similarity)) ? Number(b.local_similarity) : -1;
    if (ca !== cb) return cb - ca;
    return lexicalScore(b, target) - lexicalScore(a, target);
  });
}

// MMR-like selection without requiring raw embedding vectors. It combines the
// local CLIP relevance score with a deterministic metadata similarity penalty;
// exact/recent assets are excluded entirely by the caller.
function diversifyCandidates(candidates, limit = 12, lambda = 0.78) {
  const pool = [...(candidates || [])];
  const kept = [];
  const tokens = (c) => new Set(`${c?.alt || ""} ${c?.query || ""}`.toLowerCase().match(/[a-z0-9][a-z0-9'-]{2,}/g) || []);
  const sim = (a, b) => {
    const A = tokens(a), B = tokens(b);
    if (!A.size || !B.size) return 0;
    let common = 0;
    for (const x of A) if (B.has(x)) common += 1;
    return common / Math.max(A.size, B.size);
  };
  while (pool.length && kept.length < limit) {
    let bestIdx = 0;
    let bestScore = -Infinity;
    for (let i = 0; i < pool.length; i++) {
      const c = pool[i];
      const relevance = Number.isFinite(Number(c.local_similarity)) ? Number(c.local_similarity) / 100 : Math.min(1, lexicalScore(c, c.query) / 4);
      const redundancy = kept.length ? Math.max(...kept.map((k) => sim(c, k))) : 0;
      const score = lambda * relevance - (1 - lambda) * redundancy;
      if (score > bestScore) { bestScore = score; bestIdx = i; }
    }
    kept.push(pool.splice(bestIdx, 1)[0]);
  }
  return kept;
}

module.exports = { localSemanticRerank, diversifyCandidates, lexicalScore, withTimeout };
