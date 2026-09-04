#!/usr/bin/env python3
"""Finalize the V5 resolver runtime without reapplying legacy V4 rewrites.

The checked-in resolver owns semantic policy. This transform adds only runtime
mechanics that are awkward to keep duplicated in that readable source:
- literal-video media filtering,
- adaptive use of the scene's vision budget,
- local staging of remote video before FFmpeg decoding/materialization,
- early acceptance only after the complete semantic gate passes,
- bounded diagnostic telemetry.

It is intentionally idempotent and is invoked only by build_production_artifacts.py.
"""
from __future__ import annotations

import sys
from pathlib import Path

MARKER = "RESOLVER_V5_RUNTIME"
MEDIA_MARKER = "V5_PROOF_MEDIA_TYPE_FILTER"
VIDEO_BUDGET_MARKER = "V5_VIDEO_VERIFY_USES_SCENE_BUDGET"
STAGING_MARKER = "V5_VIDEO_SAMPLE_STAGING"
EARLY_MARKER = "V5_FULL_GATE_EARLY_ACCEPT"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        return text
    if old not in text:
        raise RuntimeError(f"{label} anchor missing")
    return text.replace(old, new, 1)


def replace_function_block(text: str, start_marker: str, end_marker: str, replacement: str, label: str) -> str:
    start = text.find(start_marker)
    if start < 0:
        raise RuntimeError(f"{label} start missing")
    end = text.find(end_marker, start)
    if end < 0:
        raise RuntimeError(f"{label} end missing")
    return text[:start] + replacement + text[end:]


STAGING_BLOCK = r'''// V5_VIDEO_SAMPLE_STAGING: localize third-party CDN video before FFmpeg.
// This removes redirect/TLS/User-Agent variability from both verification and
// final clip materialization and keeps failure classification deterministic.
const VIDEO_SAMPLE_MAX_BYTES = Math.max(8 * 1024 * 1024, Number(process.env.BROLL_VIDEO_SAMPLE_MAX_BYTES || 96 * 1024 * 1024));
function compactSamplingError(err) { return String(err?.message || err || "unknown").replace(/\s+/g, " ").trim().slice(-500); }
function classifySamplingFfmpegError(err) {
  const text = compactSamplingError(err);
  if (/timed out|ETIMEDOUT/i.test(text)) return "video_contact_sheet_timeout";
  if (/invalid data found|moov atom not found|could not find codec parameters/i.test(text)) return "video_contact_sheet_invalid_media";
  if (/no such filter|error initializing filter|failed to configure output pad/i.test(text)) return "video_contact_sheet_filter_failed";
  if (/unknown decoder|decoder .* not found/i.test(text)) return "video_contact_sheet_decoder_unavailable";
  return "video_contact_sheet_ffmpeg_failed";
}
async function downloadVideoInput(candidate, purpose = "sample", state = null) {
  const local = String(candidate?.local_path || "").trim();
  if (local && fs.existsSync(local)) return { ok: true, input: local, cleanup: false, sample_source: "local" };
  const rawUrls = purpose === "materialize" ? [candidate?.url] : [candidate?.sample_url, candidate?.url];
  const urls = [...new Set(rawUrls.map((v) => String(v || "").trim()).filter((v) => /^https?:\/\//i.test(v)))];
  const prefix = purpose === "materialize" ? "video_asset_download" : "video_sample_download";
  if (!urls.length) return { ok: false, reason: `${prefix}_url_invalid`, detail: "no http(s) video URL" };
  let last = null;
  for (const sourceUrl of urls) {
    const remaining = state ? remainingDeadlineMs(state) : 20000;
    if (state && remaining < 1500) return { ok: false, reason: "resolver_deadline_exhausted", detail: "deadline reached before video staging" };
    const tmp = path.join(os.tmpdir(), `broll-source-${crypto.randomUUID()}.mp4`);
    try {
      const r = await axios.get(sourceUrl, {
        timeout: Math.max(1000, Math.min(20000, remaining - 500)), responseType: "arraybuffer", maxRedirects: 5,
        maxContentLength: VIDEO_SAMPLE_MAX_BYTES, maxBodyLength: VIDEO_SAMPLE_MAX_BYTES,
        headers: { "User-Agent": "Mozilla/5.0 (compatible; FavouriteFactsBot/1.0; +https://youtube.com)", Accept: "video/*,application/octet-stream;q=0.9,*/*;q=0.1" },
      });
      const buf = Buffer.from(r.data || []);
      if (buf.length < 1024) throw new Error(`${prefix}_empty`);
      if (buf.length > VIDEO_SAMPLE_MAX_BYTES) throw new Error(`${prefix}_too_large`);
      await fsp.writeFile(tmp, buf);
      return { ok: true, input: tmp, cleanup: true, sample_source: "download", sample_bytes: buf.length };
    } catch (err) {
      await fsp.unlink(tmp).catch(() => {});
      const status = Number(err?.response?.status || 0), detail = compactSamplingError(err);
      const reason = status ? `${prefix}_http_${status}` : /maxContentLength|maxBodyLength|too_large/i.test(detail) ? `${prefix}_too_large` : /timeout|ETIMEDOUT|ECONNABORTED/i.test(detail) ? `${prefix}_timeout` : `${prefix}_failed`;
      last = { ok: false, reason, detail };
    }
  }
  return last || { ok: false, reason: `${prefix}_failed`, detail: "all video URLs failed" };
}
async function downloadVideoSample(candidate, state = null) { return downloadVideoInput(candidate, "sample", state); }
async function sampleVideoContactSheet(candidate, state = null) {
  const duration = Number(candidate?.duration || 0);
  if (!duration || duration < 0.5) return { ok: false, reason: "video_duration_invalid", detail: `duration=${candidate?.duration ?? "missing"}` };
  const staged = await downloadVideoSample(candidate, state);
  if (!staged.ok) return staged;
  const cols = 4, rows = Math.ceil(VIDEO_SAMPLE_FRAMES / cols), fps = Math.max(0.05, VIDEO_SAMPLE_FRAMES / duration);
  const tmp = path.join(os.tmpdir(), `broll-sheet-${crypto.randomUUID()}.png`);
  try {
    const ffmpegTimeout = state ? Math.max(1000, Math.min(90000, remainingDeadlineMs(state) - 500)) : 90000;
    await runFfmpeg(["-hide_banner", "-loglevel", "error", "-y", "-i", staged.input, "-vf", `fps=${fps.toFixed(6)},scale=320:240:force_original_aspect_ratio=decrease,pad=320:240:(ow-iw)/2:(oh-ih)/2:color=black,tile=${cols}x${rows}:nb_frames=${VIDEO_SAMPLE_FRAMES}:padding=3:margin=3`, "-frames:v", "1", tmp], ffmpegTimeout);
    const buf = await fsp.readFile(tmp);
    if (buf.length < 1024) return { ok: false, reason: "video_contact_sheet_empty", detail: `bytes=${buf.length}`, sample_source: staged.sample_source };
    return { ok: true, imageUrl: `data:image/png;base64,${buf.toString("base64")}`, timestamps: Array.from({ length: VIDEO_SAMPLE_FRAMES }, (_, i) => Number(Math.min(duration, (i + 0.5) * duration / VIDEO_SAMPLE_FRAMES).toFixed(3))), sample_source: staged.sample_source, sample_bytes: staged.sample_bytes || null };
  } catch (err) {
    return { ok: false, reason: classifySamplingFfmpegError(err), detail: compactSamplingError(err), sample_source: staged.sample_source };
  } finally {
    await fsp.unlink(tmp).catch(() => {});
    if (staged.cleanup) await fsp.unlink(staged.input).catch(() => {});
  }
}
const buildVideoContactSheet = sampleVideoContactSheet;

'''

MATERIALIZE_BLOCK = r'''async function materializeVerifiedClip(candidate, verification, state = null) {
  await cleanupVerifiedCache(); await fsp.mkdir(VERIFIED_CACHE_DIR, { recursive: true });
  const start = Number(verification.verified_start_sec || 0), end = Number(verification.verified_end_sec || 0), duration = Math.max(0.05, end - start), key = crypto.createHash("sha256").update(`${candidate.url}|${start}|${end}`).digest("hex").slice(0, 24), filename = `verified_${key}.mp4`, dest = path.join(VERIFIED_CACHE_DIR, filename);
  if (!fs.existsSync(dest) || fs.statSync(dest).size < 4096) {
    const staged = await downloadVideoInput(candidate, "materialize", state);
    if (!staged.ok) throw new Error(`${staged.reason}: ${staged.detail || "video staging failed"}`);
    const tmp = `${dest}.tmp-${process.pid}-${Date.now()}.mp4`;
    try {
      const timeout = state ? Math.max(1000, Math.min(120000, remainingDeadlineMs(state) - 500)) : 120000;
      await runFfmpeg(["-hide_banner", "-loglevel", "error", "-y", "-ss", String(start), "-i", staged.input, "-t", String(duration), "-an", "-vf", "scale='min(1080,iw)':-2", "-c:v", "libx264", "-preset", "veryfast", "-crf", "19", "-pix_fmt", "yuv420p", "-movflags", "+faststart", tmp], timeout);
      await fsp.rename(tmp, dest);
    } finally {
      await fsp.unlink(tmp).catch(() => {});
      if (staged.cleanup) await fsp.unlink(staged.input).catch(() => {});
    }
  }
  return { url: `${VERIFIED_PUBLIC_BASE}/broll-cache/${filename}`, local_path: dest, source_url: candidate.url, in_point_sec: start, out_point_sec: end, verified_duration_sec: Number(duration.toFixed(3)) };
}

'''


def upgrade(text: str) -> str:
    if MARKER in text:
        return text

    type_anchor = '    if (contract.visual_proof_mode === "annotated_real") candidates = candidates.filter((c) => c.type === "image");'
    type_new = type_anchor + f'\n    // {MEDIA_MARKER}: an observable-action proof spends verifier budget only on actual motion.\n    if (contract.visual_proof_mode === "literal_video") candidates = candidates.filter((c) => c.type === "video");'
    text = replace_once(text, type_anchor, type_new, "proof media filter")

    text = replace_once(
        text,
        '        if (videoCalls++ >= VIDEO_VERIFY_TOP_N) continue;',
        f'        // {VIDEO_BUDGET_MARKER}: borrowed support-scene budget is usable for video verification too.\n        if (videoCalls++ >= Math.max(VIDEO_VERIFY_TOP_N, state.scene_budget.limit)) continue;',
        "video verifier cap",
    )

    text = replace_function_block(text, 'async function sampleVideoContactSheet(candidate) {', 'function normalizeRange(', STAGING_BLOCK, "video sampling")
    text = replace_once(text, '  const sheet = await sampleVideoContactSheet(candidate); if (!sheet) return { ok: false, reason: "video_contact_sheet_failed" };', '  const sheet = await sampleVideoContactSheet(candidate, state); if (!sheet?.ok) return { ok: false, reason: sheet?.reason || "video_contact_sheet_failed", failure_detail: sheet?.detail || null, sample_source: sheet?.sample_source || null };', "video verifier sampling")
    text = replace_function_block(text, 'async function materializeVerifiedClip(candidate, verification) {', 'function words(', MATERIALIZE_BLOCK, "verified clip materialization")
    text = replace_once(text, '        const materialized = await materializeVerifiedClip(c, verification).catch(() => null);', '        const materialized = await materializeVerifiedClip(c, verification, state).catch(() => null);', "materializer state forwarding")

    # Stop scoring once a candidate clears the complete gate, not merely its
    # aesthetic score. Each replacement leaves the accepted result in `scored`.
    text = replace_once(text,
        '        scored.push({ ...c, score: Number(c.score || c.semantic_match), rejected: false });\n        continue;',
        f'        const accepted = {{ ...c, score: Number(c.score || c.semantic_match), rejected: false }}; scored.push(accepted);\n        // {EARLY_MARKER}: stop only after the full semantic/entity/action/relationship gate passes.\n        if (candidatePassesGate(accepted, contract, threshold)) break;\n        continue;',
        "library full-gate early accept")
    text = replace_once(text,
        '        scored.push({ ...c, ...verification, ...materialized, original_url: c.url, score: verification.overall });\n        continue;',
        '        const accepted = { ...c, ...verification, ...materialized, original_url: c.url, score: verification.overall, rejected: false }; scored.push(accepted);\n        if (candidatePassesGate(accepted, contract, threshold)) break;\n        continue;',
        "video full-gate early accept")
    text = replace_once(text,
        '        scored.push({ ...c, ...dimensions, ...materialized, score: dimensions.overall, rejected: false });\n        continue;',
        '        const accepted = { ...c, ...dimensions, ...materialized, score: dimensions.overall, rejected: false }; scored.push(accepted);\n        if (candidatePassesGate(accepted, contract, threshold)) break;\n        continue;',
        "verified image full-gate early accept")
    text = replace_once(text,
        '      scored.push({ ...c, ...dimensions, score: dimensions.overall, rejected: false });',
        '      const accepted = { ...c, ...dimensions, score: dimensions.overall, rejected: false }; scored.push(accepted);\n      if (candidatePassesGate(accepted, contract, threshold)) break;',
        "image full-gate early accept")

    fail_anchor = '      best_candidate: summarizeCandidate(usableBest || scored[0]),\n      recommended_visual_proof_mode: contract.visual_proof_mode,'
    fail_new = '      best_candidate: summarizeCandidate(usableBest || scored[0]),\n      vision_call_limit: state.scene_budget.limit,\n      failure_reasons: [...new Set(scored.filter((x) => x.rejected).map((x) => String(x.reason || "semantic_gate_failed").slice(0, 120)))].slice(0, 6),\n      recommended_visual_proof_mode: contract.visual_proof_mode,'
    text = replace_once(text, fail_anchor, fail_new, "failure telemetry")

    success_anchor = '    actual_video_verified: best.type === "video", library_hit: best.library_hit === true, recommended_visual_proof_mode: contract.visual_proof_mode, visual_contract: contract, ...budget,'
    success_new = '    actual_video_verified: best.type === "video", library_hit: best.library_hit === true, vision_call_limit: state.scene_budget.limit, recommended_visual_proof_mode: contract.visual_proof_mode, visual_contract: contract, ...budget,'
    text = replace_once(text, success_anchor, success_new, "success telemetry")

    return text + f"\n// {MARKER} / {STAGING_MARKER}\n"


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: resolver_v5_runtime.py BROLL_RESOLVER_JS")
    path = Path(sys.argv[1])
    text = upgrade(path.read_text())
    required = [MARKER, MEDIA_MARKER, VIDEO_BUDGET_MARKER, STAGING_MARKER, EARLY_MARKER, "downloadVideoSample", "video_contact_sheet_ffmpeg_failed", "candidatePassesGate", "below_semantic_quality_gate"]
    missing = [x for x in required if x not in text]
    if missing:
        raise RuntimeError("V5 resolver runtime guarantees missing: " + ", ".join(missing))
    if "annotation_plan" in text or "normalizeAnnotationPlan" in text:
        raise RuntimeError("legacy annotation geometry reintroduced")
    path.write_text(text)
    print(f"{MARKER} written to {path}")


if __name__ == "__main__":
    main()
