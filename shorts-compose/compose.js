/**
 * compose.js
 * -----------------------------------------------------------------------
 * Express endpoint: POST /compose
 * Studio-grade short-form video compositor (TikTok/Reels/Shorts)
 * Hybrid architecture: Remotion for templates/captions + ffmpeg for
 * stock scenes, audio mixing, transitions, and final encoding.
 * -----------------------------------------------------------------------
 */

const express = require("express");
const fs = require("fs");
const fsp = fs.promises;
const path = require("path");
const os = require("os");
const crypto = require("crypto");
const axios = require("axios");
const ffmpeg = require("fluent-ffmpeg");
const ffmpegPath = require("ffmpeg-static");
const { execFile } = require("child_process");
ffmpeg.setFfmpegPath(ffmpegPath);

const app = express();
app.use(express.json({ limit: "50mb" }));
// In-memory job store for the async compose pattern
const jobStore = new Map();

const OUTPUT_DIR = process.env.OUTPUT_DIR || "/outputs";
app.use("/outputs", express.static(OUTPUT_DIR));

const MUSIC_DIR = process.env.MUSIC_DIR || path.join(__dirname, "music");
const MOTION_ASSETS_DIR = process.env.MOTION_ASSETS_DIR || path.join(__dirname, "motion-assets");
const REMOTION_DIR = path.join(__dirname, "remotion");
const TOPIC_HISTORY_PATH = process.env.TOPIC_HISTORY_PATH || path.join(__dirname, "topic_history.json");
const TOPIC_HISTORY_MAX = 90;

const TARGET_W = 1080;
const TARGET_H = 1920;
const FPS = 30;

// Detect video encoder hardware support (libx264 fallback)
const V_ENCODER = process.env.USE_NVENC ? "h264_nvenc" : "libx264";

// Fixed follow/subscribe outro appended to every video
const OUTRO_DURATION_SEC = 2.0;
const DEFAULT_OUTRO_LINE = "Follow for more";

// ---------------------------------------------------------------------------
// Endpoints: Topic History
// ---------------------------------------------------------------------------

app.get("/topic-history", async (req, res) => {
  try {
    if (!fs.existsSync(TOPIC_HISTORY_PATH)) return res.json({ topics: [] });
    const raw = await fsp.readFile(TOPIC_HISTORY_PATH, "utf8");
    return res.json({ topics: JSON.parse(raw) });
  } catch (err) {
    console.error("Failed to read topic history:", err);
    return res.status(500).json({ topics: [], error: err.message });
  }
});

app.post("/topic-history", async (req, res) => {
  try {
    const { topic, hook } = req.body;
    if (!topic) return res.status(400).json({ success: false, error: "topic is required" });

    let topics = [];
    if (fs.existsSync(TOPIC_HISTORY_PATH)) {
      topics = JSON.parse(await fsp.readFile(TOPIC_HISTORY_PATH, "utf8"));
    }
    topics.push({ topic, hook: hook || null, created_at: new Date().toISOString() });
    if (topics.length > TOPIC_HISTORY_MAX) {
      topics = topics.slice(topics.length - TOPIC_HISTORY_MAX);
    }
    await fsp.writeFile(TOPIC_HISTORY_PATH, JSON.stringify(topics, null, 2));
    return res.json({ success: true, count: topics.length });
  } catch (err) {
    console.error("Failed to write topic history:", err);
    return res.status(500).json({ success: false, error: err.message });
  }
});

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function newTmpDir() {
  const dir = path.join(os.tmpdir(), "shorts-" + crypto.randomUUID());
  fs.mkdirSync(dir, { recursive: true });
  return dir;
}

async function downloadFile(url, destPath) {
  const res = await axios.get(url, { responseType: "arraybuffer", timeout: 60000 });
  await fsp.writeFile(destPath, res.data);
  return destPath;
}

async function writeBase64(base64, destPath) {
  await fsp.writeFile(destPath, Buffer.from(base64, "base64"));
  return destPath;
}

function generateSilentAudioBase64(durationSec) {
  return new Promise((resolve, reject) => {
    const tmpPath = path.join(os.tmpdir(), `silence-${crypto.randomUUID()}.mp3`);
    execFile(
      ffmpegPath,
      ["-y", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono", "-t", String(durationSec), "-c:a", "libmp3lame", "-b:a", "64k", tmpPath],
      (err) => {
        if (err) return reject(err);
        fs.readFile(tmpPath, (readErr, data) => {
          fs.unlink(tmpPath, () => {});
          if (readErr) return reject(readErr);
          resolve(data.toString("base64"));
        });
      }
    );
  });
}

function run(cmdBuilder) {
  return new Promise((resolve, reject) => {
    cmdBuilder
      .on("start", (cmd) => console.log("[ffmpeg]", cmd))
      .on("error", (err, stdout, stderr) => {
        console.error("[ffmpeg error]", err.message);
        console.error(stderr);
        reject(err);
      })
      .on("end", () => resolve())
      .run();
  });
}

function ffprobeDuration(filePath) {
  return new Promise((resolve, reject) => {
    ffmpeg.ffprobe(filePath, (err, data) => {
      if (err) return reject(err);
      resolve(data.format.duration);
    });
  });
}

// ---------------------------------------------------------------------------
// Studio Color Grading (split-tone with shadow lift and highlight rolloff)
// ---------------------------------------------------------------------------

function getColorGrade(mood) {
  // Split-tone: warm highlights + cool shadows, shadow lift to prevent
  // crushed blacks on OLED screens, soft highlight rolloff for film look.
  const grades = {
    upbeat: [
      "eq=contrast=1.15:saturation=1.45:brightness=0.02",
      "colorbalance=rs=0.12:gs=0.04:bs=-0.08:rh=0.06:gh=0.02:bh=-0.04",
      "curves=m='0/0.06 0.25/0.30 0.5/0.52 0.75/0.78 1/0.95'",
    ].join(","),
    serious: [
      "eq=contrast=1.18:saturation=0.90:brightness=-0.01",
      "colorbalance=rs=-0.04:gs=0.0:bs=0.06:rh=0.02:gh=-0.01:bh=0.04",
      "curves=m='0/0.05 0.25/0.28 0.5/0.50 0.75/0.76 1/0.93'",
    ].join(","),
    funny: [
      "eq=contrast=1.10:saturation=1.60:brightness=0.03",
      "colorbalance=rs=0.10:gs=0.08:bs=-0.06:rh=0.04:gh=0.06:bh=-0.02",
      "curves=m='0/0.07 0.25/0.31 0.5/0.53 0.75/0.79 1/0.96'",
    ].join(","),
    neutral: [
      "eq=contrast=1.10:saturation=1.15:brightness=0.01",
      "colorbalance=rs=0.02:gs=0.0:bs=0.02:rh=0.03:gh=0.01:bh=-0.01",
      "curves=m='0/0.05 0.25/0.29 0.5/0.51 0.75/0.77 1/0.94'",
    ].join(","),
  };
  return grades[mood] || grades.neutral;
}

function pickMusicTrack(mood) {
  const candidate = path.join(MUSIC_DIR, `${(mood || "neutral").toLowerCase()}.mp3`);
  if (fs.existsSync(candidate)) return candidate;
  return path.join(MUSIC_DIR, "neutral.mp3");
}

// ---------------------------------------------------------------------------
// Remotion Render Bridge
// ---------------------------------------------------------------------------

function renderRemotion(compositionId, outputPath, durationSec, props) {
  return new Promise((resolve, reject) => {
    const bridgePath = path.join(REMOTION_DIR, "render-bridge.mjs");
    const args = [
      bridgePath,
      compositionId,
      outputPath,
      String(durationSec),
      JSON.stringify(props),
    ];

    console.log(`[remotion] Rendering ${compositionId} (${durationSec}s)...`);
    const child = execFile("node", args, {
      cwd: REMOTION_DIR,
      timeout: 300000, // 5 min max
      maxBuffer: 10 * 1024 * 1024,
    }, (err, stdout, stderr) => {
      if (stdout) console.log("[remotion stdout]", stdout);
      if (stderr) console.log("[remotion stderr]", stderr);
      if (err) {
        console.error("[remotion] Render failed:", err.message);
        return reject(err);
      }
      resolve(outputPath);
    });
  });
}

// ---------------------------------------------------------------------------
// Stock Scene Processing (ffmpeg — eased zoompan, cinematic grading)
// ---------------------------------------------------------------------------

async function buildStockVideoScene(stockVideoPath, audioPath, duration, outPath, sceneIdx, mood) {
  const stockDuration = await ffprobeDuration(stockVideoPath);
  const needsPad = stockDuration < duration;

  // Cinematic processing: scale to fill, crop, split-tone grade,
  // vignette, and subtle film grain (very low to avoid bitrate bloat)
  const gradeFilter = getColorGrade(mood);
  const padFilter = needsPad
    ? `,tpad=stop_mode=clone:stop_duration=${(duration - stockDuration + 0.1).toFixed(3)}`
    : "";

  const videoFilter = [
    `[0:v]scale=${TARGET_W}:${TARGET_H}:force_original_aspect_ratio=increase`,
    `crop=${TARGET_W}:${TARGET_H}${padFilter}`,
    gradeFilter,
    `vignette=angle=PI/10:aspect=9/16`,
    `unsharp=5:5:0.4:5:5:0.0`,
  ].join(",") + "[processed]";

  await run(
    ffmpeg()
      .input(stockVideoPath)
      .input(audioPath)
      .complexFilter([videoFilter])
      .outputOptions([
        "-map", "[processed]",
        "-map", "1:a",
        "-t", String(duration),
        "-af", "loudnorm=I=-16:TP=-1.5:LRA=11",
        "-c:v", V_ENCODER,
        "-r", String(FPS),
        "-preset", "veryfast",
        "-crf", "18",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-b:a", "192k",
      ])
      .output(outPath)
  );

  return outPath;
}

async function buildImageScene(imagePaths, audioPath, duration, outPath, sceneIdx, mood) {
  // Eased Ken Burns with sinusoidal motion (not linear)
  // Creates organic, handheld-feeling camera movement
  const fps = FPS;
  const CUT_INTERVAL_SEC = sceneIdx === 0 ? 3.5 : 4.5;
  const numSegments = Math.max(1, Math.round(duration / CUT_INTERVAL_SEC));
  const segDuration = duration / numSegments;
  const totalFrames = Math.ceil(segDuration * fps);
  const gradeFilter = getColorGrade(mood);

  const segmentPaths = [];
  for (let seg = 0; seg < numSegments; seg++) {
    const imgPath = imagePaths[seg % imagePaths.length];
    const segOutPath = path.join(path.dirname(outPath), `seg_${sceneIdx}_${seg}.mp4`);
    const panLeftToRight = seg % 2 === 0;

    // Sinusoidal easing: slow start, slow end, gentle drift through the middle
    // zoompan expressions use on/d for normalized progress
    const xExpr = panLeftToRight
      ? `'iw*0.035*(1-cos(PI*on/${totalFrames}))/2'`
      : `'iw*0.035*(1+cos(PI*on/${totalFrames}))/2'`;

    // Subtle zoom drift (1.09 -> 1.07 or vice versa) for organic feel
    const zoomExpr = seg % 2 === 0
      ? `'1.09-0.02*(1-cos(PI*on/${totalFrames}))/2'`
      : `'1.07+0.02*(1-cos(PI*on/${totalFrames}))/2'`;

    // Gentle punch-in on the first segment only, eased over its own window
    const punchFrames = Math.min(18, Math.round(totalFrames * 0.3));
    const finalZoom = sceneIdx === 0 && seg === 0
      ? `'if(lte(on,${punchFrames}),1.13-0.04*on/${punchFrames},${zoomExpr.slice(1, -1)})'`
      : zoomExpr;

    const filterGraph = [
      // Upscale well past the output resolution before zoompan - cropping
      // from a source close to the output size makes the per-frame crop
      // window round to whole pixels unevenly, which reads as flicker/
      // vibration. The extra sub-pixel headroom eliminates that jitter.
      `[0:v]scale=-2:6000,zoompan=z=${finalZoom}:x=${xExpr}:y='ih*0.02*(1-cos(PI*on/${totalFrames}))/2':d=${totalFrames}:s=${TARGET_W}x${TARGET_H}:fps=${fps}[zoomed]`,
      `[zoomed]${gradeFilter}[graded]`,
      `[graded]vignette=angle=PI/10:aspect=9/16[vignetted]`,
      `[vignetted]unsharp=5:5:0.4:5:5:0.0[final]`,
    ];

    await run(
      ffmpeg()
        .input(imgPath)
        .complexFilter(filterGraph)
        .outputOptions([
          "-map", "[final]",
          "-t", String(segDuration),
          "-c:v", V_ENCODER,
          "-r", String(fps),
          "-preset", "veryfast",
          "-crf", "18",
          "-pix_fmt", "yuv420p",
          "-an",
        ])
        .output(segOutPath)
    );
    segmentPaths.push(segOutPath);
  }

  // Concatenate segments
  const sceneVideoPath = path.join(path.dirname(outPath), `scenevid_${sceneIdx}.mp4`);
  if (segmentPaths.length === 1) {
    fs.copyFileSync(segmentPaths[0], sceneVideoPath);
  } else {
    const listPath = path.join(path.dirname(outPath), `seglist_${sceneIdx}.txt`);
    const listContent = segmentPaths.map((p) => `file '${p.replace(/'/g, "'\\''")}'`).join("\n");
    await fsp.writeFile(listPath, listContent);
    await run(
      ffmpeg()
        .input(listPath)
        .inputOptions(["-f", "concat", "-safe", "0"])
        .outputOptions(["-c", "copy"])
        .output(sceneVideoPath)
    );
  }

  // Mux with audio
  await run(
    ffmpeg()
      .input(sceneVideoPath)
      .input(audioPath)
      .outputOptions([
        "-map", "0:v",
        "-map", "1:a",
        "-t", String(duration),
        "-af", "loudnorm=I=-16:TP=-1.5:LRA=11",
        "-c:v", "copy",
        "-c:a", "aac",
        "-b:a", "192k",
      ])
      .output(outPath)
  );

  return outPath;
}

// ---------------------------------------------------------------------------
// Template Scene Processing (Remotion — studio motion graphics)
// ---------------------------------------------------------------------------

async function buildTemplateScene(templateName, templateData, duration, audioPath, outPath, tmpDir, mood) {
  // Map template names to Remotion composition IDs
  const compositionMap = {
    stat_reveal: "StatReveal",
    comparison: "Comparison",
    kinetic_text: "KineticText",
  };

  const compositionId = compositionMap[templateName];
  if (!compositionId) {
    throw new Error(`Unknown template_name "${templateName}"`);
  }

  // Build props for the Remotion composition
  let props = { mood: mood || "neutral" };
  if (templateName === "stat_reveal") {
    props.statValue = templateData?.statValue || "";
    props.label = templateData?.label || "";
    props.icon = templateData?.icon || "activity";
  } else if (templateName === "comparison") {
    props.leftLabel = templateData?.leftLabel || "";
    props.leftValue = templateData?.leftValue || "";
    props.rightLabel = templateData?.rightLabel || "";
    props.rightValue = templateData?.rightValue || "";
  } else if (templateName === "kinetic_text") {
    props.line = templateData?.line || "";
  }

  // Render template via Remotion
  const templateVideoPath = path.join(tmpDir, `remotion_${templateName}_${Date.now()}.mp4`);
  await renderRemotion(compositionId, templateVideoPath, duration, props);

  // Mux Remotion video with audio
  const templateDuration = await ffprobeDuration(templateVideoPath);
  const videoFilter = templateDuration < duration
    ? `[0:v]tpad=stop_mode=clone:stop_duration=${(duration - templateDuration + 0.1).toFixed(3)}[padded]`
    : `[0:v]null[padded]`;

  await run(
    ffmpeg()
      .input(templateVideoPath)
      .input(audioPath)
      .complexFilter([videoFilter])
      .outputOptions([
        "-map", "[padded]",
        "-map", "1:a",
        "-t", String(duration),
        "-af", "loudnorm=I=-16:TP=-1.5:LRA=11",
        "-c:v", V_ENCODER,
        "-r", String(FPS),
        "-preset", "veryfast",
        "-crf", "18",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-b:a", "192k",
      ])
      .output(outPath)
  );

  return outPath;
}

// ---------------------------------------------------------------------------
// Karaoke ASS Caption Builder (burn-in via ffmpeg — no transparency issues)
// ---------------------------------------------------------------------------

function toAssTime(sec) {
  const h = Math.floor(sec / 3600);
  const m = Math.floor((sec % 3600) / 60);
  const s = (sec % 60).toFixed(2);
  return `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(5, "0")}`;
}

function buildAssFromAlignment(scenes, offsets, commentHook, totalDuration) {
  const header = `[Script Info]
ScriptType: v4.00+
PlayResX: ${TARGET_W}
PlayResY: ${TARGET_H}
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Caption,Inter Bold,64,&H00FFFFFF,&H000000FF,&H40000000,&H80000000,0,0,0,0,100,100,0,0,1,3,4,2,60,60,420,1
Style: CaptionHL,Inter Bold,68,&H0096E0FF,&H000000FF,&H40000000,&H80000000,0,0,0,0,105,105,0,0,1,3,4,2,60,60,420,1
Style: CommentHook,Inter Bold,54,&H00FFFFFF,&H000000FF,&H40202020,&HC0000000,0,0,0,0,100,100,0,0,3,0,4,2,80,80,680,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
`;

  let events = "";
  const WORDS_PER_CHUNK = 2;

  scenes.forEach((scene, sceneIdx) => {
    const alignment = scene?.audio?.alignment;
    if (!alignment) return;

    const chars = alignment.characters;
    const starts = alignment.character_start_times_seconds;
    const ends = alignment.character_end_times_seconds;

    const words = [];
    let current = "";
    let wordStart = null;
    for (let i = 0; i < chars.length; i++) {
      const ch = chars[i];
      if (ch === " " || ch === "\n") {
        if (current) {
          words.push({ text: current, start: wordStart, end: ends[i - 1] });
          current = "";
          wordStart = null;
        }
        continue;
      }
      if (wordStart === null) wordStart = starts[i];
      current += ch;
    }
    if (current) words.push({ text: current, start: wordStart, end: ends[ends.length - 1] });

    for (let i = 0; i < words.length; i += WORDS_PER_CHUNK) {
      const chunk = words.slice(i, i + WORDS_PER_CHUNK);
      if (!chunk.length || chunk[0].start == null) continue;

      chunk.forEach((w) => {
        const wStart = w.start + offsets[sceneIdx];
        const wEnd = w.end + offsets[sceneIdx];
        const highlightText = chunk
          .map((item) => {
            if (item === w) {
              return `{\\rCaptionHL}${item.text}{\\r}`;
            }
            return item.text;
          })
          .join(" ");

        events += `Dialogue: 0,${toAssTime(wStart)},${toAssTime(wEnd)},Caption,,0,0,0,,${highlightText}\n`;
      });
    }
  });

  if (commentHook && totalDuration) {
    const hookDuration = Math.min(1.8, totalDuration * 0.4);
    const hookStart = Math.max(0, totalDuration - hookDuration);
    const escaped = commentHook.replace(/\\/g, "").replace(/\{/g, "").replace(/\}/g, "");
    events += `Dialogue: 1,${toAssTime(hookStart)},${toAssTime(totalDuration)},CommentHook,,0,0,0,,{\\fscx0\\fscy0\\t(0,200,\\fscx120\\fscy120)\\t(200,300,\\fscx100\\fscy100)}${escaped}\n`;
  }

  return header + events;
}

// ---------------------------------------------------------------------------
// Caption Overlay via Remotion (kept for future use with VP9/RGBA output)
// ---------------------------------------------------------------------------

function extractWordsFromAlignment(scenes, offsets) {
  const allWords = [];

  scenes.forEach((scene, sceneIdx) => {
    const alignment = scene?.audio?.alignment;
    if (!alignment) return;

    const chars = alignment.characters;
    const starts = alignment.character_start_times_seconds;
    const ends = alignment.character_end_times_seconds;

    let current = "";
    let wordStart = null;
    for (let i = 0; i < chars.length; i++) {
      const ch = chars[i];
      if (ch === " " || ch === "\n") {
        if (current) {
          allWords.push({
            text: current,
            start: wordStart + offsets[sceneIdx],
            end: ends[i - 1] + offsets[sceneIdx],
          });
          current = "";
          wordStart = null;
        }
        continue;
      }
      if (wordStart === null) wordStart = starts[i];
      current += ch;
    }
    if (current && wordStart !== null) {
      allWords.push({
        text: current,
        start: wordStart + offsets[sceneIdx],
        end: ends[ends.length - 1] + offsets[sceneIdx],
      });
    }
  });

  return allWords;
}

async function renderCaptionOverlay(scenes, offsets, commentHook, totalDuration, outPath) {
  const words = extractWordsFromAlignment(scenes, offsets);
  const props = { words, commentHook: commentHook || "", totalDuration };

  await renderRemotion("CaptionOverlay", outPath, totalDuration, props);
  return outPath;
}

// ---------------------------------------------------------------------------
// Scene Concatenation (hard cuts - no crossfade)
// ---------------------------------------------------------------------------

async function concatScenes(scenePaths, outPath) {
  if (scenePaths.length === 1) {
    fs.copyFileSync(scenePaths[0], outPath);
    return outPath;
  }

  const listPath = path.join(path.dirname(outPath), "concat_scenes.txt");
  const listContent = scenePaths.map((p) => `file '${p.replace(/'/g, "'\\''")}'`).join("\n");
  await fsp.writeFile(listPath, listContent);

  await run(
    ffmpeg()
      .input(listPath)
      .inputOptions(["-f", "concat", "-safe", "0"])
      .outputOptions(["-c", "copy"])
      .output(outPath)
  );

  return outPath;
}

// ---------------------------------------------------------------------------
// Main Compose Pipeline
// ---------------------------------------------------------------------------

async function runComposeJob(reqBody, jobId, tmpDir) {
  try {
    const { hook, caption_style, comment_hook, data: scenes } = reqBody;
    if (!Array.isArray(scenes) || scenes.length === 0) {
      throw new Error("No scenes provided");
    }

    const mood = caption_style || "neutral";

    // Append a fixed follow/subscribe outro card as the final scene of
    // every video - a designed template CTA, not AI-varied per video.
    const outroAudioBase64 = await generateSilentAudioBase64(OUTRO_DURATION_SEC);
    scenes.push({
      scene_index: scenes.length,
      visual_source: "template",
      template_name: "kinetic_text",
      template_data: { line: reqBody.outro_line || DEFAULT_OUTRO_LINE },
      audio: { audio_base64: outroAudioBase64 },
    });

    console.log(`[job ${jobId}] Composing ${scenes.length} scenes (mood: ${mood})`);

    // ===== PHASE 1: Build individual scenes in parallel =====
    const sceneResults = await Promise.all(
      scenes.map(async (scene, i) => {
        const audioPath = path.join(tmpDir, `voice_${i}.mp3`);
        if (scene?.audio?.audio_base64) {
          await writeBase64(scene.audio.audio_base64, audioPath);
        } else if (scene?.audio?.audio_url) {
          await downloadFile(scene.audio.audio_url, audioPath);
        } else {
          throw new Error(`Scene ${i} missing audio`);
        }

        const duration = await ffprobeDuration(audioPath);
        const outPath = path.join(tmpDir, `scene_${i}_final.mp4`);

        const isTemplate = scene?.visual_source === "template";
        const isStockVideo = !isTemplate && !!scene?.video_url;

        if (isTemplate) {
          if (!scene.template_name) throw new Error(`Scene ${i}: visual_source=template but no template_name`);
          await buildTemplateScene(scene.template_name, scene.template_data, duration, audioPath, outPath, tmpDir, mood);
        } else if (isStockVideo) {
          const stockVideoPath = path.join(tmpDir, `stock_${i}.mp4`);
          await downloadFile(scene.video_url, stockVideoPath);
          await buildStockVideoScene(stockVideoPath, audioPath, duration, outPath, i, mood);
        } else {
          const imageUrls = scene?.images;
          if (!Array.isArray(imageUrls) || !imageUrls.length) {
            throw new Error(`Scene ${i}: missing images array (and no video_url)`);
          }
          const imagePaths = await Promise.all(
            imageUrls.map(async (url, j) => {
              const p = path.join(tmpDir, `scene_${i}_img_${j}.png`);
              return await downloadFile(url, p);
            })
          );
          await buildImageScene(imagePaths, audioPath, duration, outPath, i, mood);
        }

        return { path: outPath, duration };
      })
    );

    const scenePaths = sceneResults.map((r) => r.path);
    const durations = sceneResults.map((r) => r.duration);

    // ===== PHASE 2: Concatenate scenes (hard cuts) =====
    const concatPath = path.join(tmpDir, "concat.mp4");
    await concatScenes(scenePaths, concatPath);

    // Calculate actual scene offsets (no overlap - hard cuts)
    const offsets = [0];
    for (let i = 1; i < durations.length; i++) {
      offsets.push(offsets[i - 1] + durations[i - 1]);
    }
    const totalVideoDuration = durations.reduce((a, b) => a + b, 0);

    // ===== PHASE 3: Burn-in captions via ASS (proven approach) =====
    // Remotion caption overlay requires VP9/RGBA to preserve transparency,
    // which adds complexity. ASS captions burned in by ffmpeg are reliable,
    // fast, and visually good enough with proper styling.
    const assPath = path.join(tmpDir, "captions.ass");
    // comment_hook should land in the last moments of the actual content,
    // not the appended outro card - exclude the outro from its timing window.
    const contentDuration = totalVideoDuration - OUTRO_DURATION_SEC;
    const assContent = buildAssFromAlignment(scenes, offsets, comment_hook, contentDuration);
    await fsp.writeFile(assPath, assContent);

    // ===== PHASE 4: Sound design + Audio mixing + Final composite =====
    const musicPath = pickMusicTrack(mood);
    const sfxDir = path.join(MOTION_ASSETS_DIR, "sfx");
    const sfxFiles = {
      whoosh: path.join(sfxDir, "whoosh.wav"),
      impact: path.join(sfxDir, "impact.wav"),
      riser: path.join(sfxDir, "riser.wav"),
    };
    const sfxAvailable = {
      whoosh: fs.existsSync(sfxFiles.whoosh),
      impact: fs.existsSync(sfxFiles.impact),
      riser: fs.existsSync(sfxFiles.riser),
    };

    // SFX events synced to real scene transitions
    const sfxEvents = [];
    for (let i = 1; i < scenes.length; i++) {
      // Whoosh + sub-bass thump on every scene cut (not just templates)
      if (sfxAvailable.whoosh) sfxEvents.push({ type: "whoosh", time: offsets[i], volume: 0.30 });
      if (sfxAvailable.impact) sfxEvents.push({ type: "impact", time: offsets[i], volume: 0.25 });
    }
    // Extra emphasis on template reveals
    scenes.forEach((s, i) => {
      if (s.visual_source === "template") {
        if (sfxAvailable.impact) sfxEvents.push({ type: "impact", time: offsets[i], volume: 0.45 });
        if (sfxAvailable.riser) sfxEvents.push({ type: "riser", time: Math.max(0, offsets[i] - 0.8), volume: 0.25 });
      }
    });

    // ===== PHASE 5: Final composite — video + captions + music + SFX =====
    const finalPath = path.join(tmpDir, "final.mp4");
    const outputFileName = `short_${jobId}.mp4`;
    const outputFullPath = path.join(OUTPUT_DIR, outputFileName);
    await fsp.mkdir(OUTPUT_DIR, { recursive: true });

    const hasMusic = fs.existsSync(musicPath);
    const hasAss = fs.existsSync(assPath);
    const safeAssPath = assPath.replace(/\\/g, "/").replace(/:/g, "\\:");

    const finalCmd = ffmpeg().input(concatPath);
    if (hasMusic) finalCmd.input(musicPath);
    sfxEvents.forEach((ev) => finalCmd.input(sfxFiles[ev.type]));

    // Track input indices
    let nextIdx = 1;
    const musicIdx = hasMusic ? nextIdx++ : null;
    const sfxIndices = sfxEvents.map(() => nextIdx++);

    // Build video filter: ASS caption burn-in + fade in/out
    const fadeOutStart = Math.max(0, totalVideoDuration - 0.5);
    const videoFilter = hasAss
      ? `[0:v]ass=${safeAssPath},fade=t=in:st=0:d=0.3,fade=t=out:st=${fadeOutStart.toFixed(2)}:d=0.5[final_v]`
      : `[0:v]fade=t=in:st=0:d=0.3,fade=t=out:st=${fadeOutStart.toFixed(2)}:d=0.5[final_v]`;

    // Build audio filter: ducked music + synced SFX
    const audioFilters = [];
    const mixLabels = ["0:a"];

    if (hasMusic) {
      // Gentler ducking: ratio 4 instead of 10, shaped attack/release
      audioFilters.push(`[${musicIdx}:a]aloop=loop=-1:size=2e9,volume=0.15[music]`);
      audioFilters.push(`[music][0:a]sidechaincompress=threshold=0.04:ratio=4:attack=20:release=200[duckedmusic]`);
      mixLabels.push("duckedmusic");
    }

    sfxEvents.forEach((ev, idx) => {
      const inputIdx = sfxIndices[idx];
      const ms = Math.round(ev.time * 1000);
      const label = `sfx${idx}`;
      audioFilters.push(`[${inputIdx}:a]volume=${ev.volume},adelay=${ms}|${ms}[${label}]`);
      mixLabels.push(label);
    });

    if (mixLabels.length > 1) {
      audioFilters.push(`[${mixLabels.join("][")}]amix=inputs=${mixLabels.length}:duration=first:normalize=0[final_a]`);
    }

    const allFilters = [videoFilter, ...audioFilters];
    finalCmd.complexFilter(allFilters);

    // Studio-grade final encoding:
    // - CRF 16 (higher quality source for YouTube's re-encode)
    // - Explicit BT.709 colorspace flags
    // - High profile for maximum quality at 1080p30
    finalCmd.outputOptions([
      "-map", "[final_v]",
      "-map", mixLabels.length > 1 ? "[final_a]" : "0:a",
      "-c:v", V_ENCODER,
      "-preset", "medium",
      "-crf", "16",
      "-profile:v", "high",
      "-level:v", "4.1",
      "-color_primaries", "bt709",
      "-color_trc", "bt709",
      "-colorspace", "bt709",
      "-pix_fmt", "yuv420p",
      "-c:a", "aac",
      "-b:a", "192k",
      "-ac", "2",
      "-shortest",
      "-movflags", "+faststart",
    ]);
    finalCmd.output(finalPath);
    await run(finalCmd);

    await fsp.copyFile(finalPath, outputFullPath);
    console.log(`[job ${jobId}] Done -> ${outputFullPath}`);
    return { success: true, output_path: outputFullPath, job_id: jobId };

  } catch (err) {
    console.error(`[job ${jobId}] FAILED:`, err);
    throw err;
  } finally {
    if (!process.env.DEBUG_KEEP_TMP) {
      await fsp.rm(tmpDir, { recursive: true, force: true }).catch(() => { });
    }
  }
}

// ---------------------------------------------------------------------------
// Async Job API
// ---------------------------------------------------------------------------

app.post("/compose", (req, res) => {
  const jobId = crypto.randomUUID();
  const tmpDir = newTmpDir();

  jobStore.set(jobId, { status: "processing", startedAt: Date.now() });

  runComposeJob(req.body, jobId, tmpDir)
    .then((result) => {
      jobStore.set(jobId, { status: "done", result, finishedAt: Date.now() });
    })
    .catch((err) => {
      jobStore.set(jobId, { status: "failed", error: err.message, finishedAt: Date.now() });
    });

  return res.status(202).json({ job_id: jobId, status: "processing" });
});

app.get("/compose-status/:jobId", (req, res) => {
  const job = jobStore.get(req.params.jobId);
  if (!job) {
    return res.status(404).json({ status: "not_found", error: `No job with id ${req.params.jobId}` });
  }
  if (job.status === "done") {
    jobStore.delete(req.params.jobId);
    return res.json({ status: "done", success: true, ...job.result });
  }
  if (job.status === "failed") {
    jobStore.delete(req.params.jobId);
    return res.status(500).json({ status: "failed", success: false, error: job.error });
  }
  return res.json({ status: "processing" });
});

const PORT = process.env.PORT || 4000;
app.listen(PORT, () => console.log(`Studio compose engine listening on :${PORT}`));
