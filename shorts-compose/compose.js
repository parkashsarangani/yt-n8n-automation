/**
 * compose.js
 * -----------------------------------------------------------------------
 * Express endpoint: POST /compose
 *
 * Input JSON shape (from n8n "Aggregate All Scenes" node):
 * {
 *   "hook": "string",
 *   "caption_style": "upbeat" | "serious" | "funny" | ...,
 *   "data": [
 *     {
 *       "narration": "scene text",
 *       "visual_prompt": "...",
 *       "video": { "video": { "url": "https://.../scene.mp4" } },   // fal.ai result shape
 *       "audio": {                                                    // ElevenLabs with-timestamps shape
 *         "audio_base64": "...",
 *         "alignment": {
 *           "characters": ["H","e","l","l","o", " ", ...],
 *           "character_start_times_seconds": [0.0, 0.05, ...],
 *           "character_end_times_seconds": [0.05, 0.10, ...]
 *         }
 *       }
 *     },
 *     ...
 *   ]
 * }
 *
 * Output: { "success": true, "output_path": "/outputs/short_<id>.mp4" }
 *
 * Design goals for "smooth quality" (fixing the things stock-footage/no-caption
 * pipelines get wrong):
 *   1. Word-level animated captions (not static subtitle blocks) — biggest
 *      perceived-quality lever for Shorts.
 *   2. Crossfade transitions between AI-generated scenes instead of hard cuts.
 *   3. Slight auto zoom (Ken Burns-style push-in) on every clip so nothing
 *      feels like a frozen frame, even if the source video has little motion.
 *   4. Background music bed, auto-ducked under the voice track (sidechain).
 *   5. Loudness normalization on the voice track so volume is consistent
 *      across scenes/videos (viewers notice volume jumps immediately).
 *   6. Vertical-safe layout: captions kept inside the "safe zone" so YouTube's
 *      UI (like/comment/subscribe buttons) never covers them.
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
ffmpeg.setFfmpegPath(ffmpegPath);

const app = express();
app.use(express.json({ limit: "50mb" }));

const OUTPUT_DIR = process.env.OUTPUT_DIR || "/outputs";
// Serves finished videos for the "Download Final Video" n8n node to fetch -
// this route was missing entirely from this file (confirmed via grep), which
// is the actual root cause of the persistent 404s, not tunnel routing.
app.use("/outputs", express.static(OUTPUT_DIR));
const MUSIC_DIR = process.env.MUSIC_DIR || path.join(__dirname, "music"); // put royalty-free tracks here, one per mood
const TOPIC_HISTORY_PATH = process.env.TOPIC_HISTORY_PATH || path.join(__dirname, "topic_history.json");
const TOPIC_HISTORY_MAX = 30; // keep last N topics to avoid an unbounded file and unbounded prompt size
const TARGET_W = 1080;
const TARGET_H = 1920;
// Oversized canvas for the panning-crop motion effect (~12% larger than target,
// giving room to slowly pan without ever showing the frame edge).
const oversizeW = Math.round(TARGET_W * 1.12);
const oversizeH = Math.round(TARGET_H * 1.12);

// ---------------------------------------------------------------------------
// Topic history endpoints - used by n8n to avoid Claude repeating the same
// angle/topic across automated runs. Plain JSON file, no DB needed at this volume.
// ---------------------------------------------------------------------------

app.get("/topic-history", async (req, res) => {
  try {
    if (!fs.existsSync(TOPIC_HISTORY_PATH)) return res.json({ topics: [] });
    const raw = await fsp.readFile(TOPIC_HISTORY_PATH, "utf8");
    const topics = JSON.parse(raw);
    return res.json({ topics });
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

/**
 * Pick a music track based on mood tag. Falls back to "neutral.mp3".
 * Drop your own royalty-free tracks into MUSIC_DIR named after moods,
 * e.g. upbeat.mp3, serious.mp3, funny.mp3, neutral.mp3
 */
function pickMusicTrack(mood) {
  const candidate = path.join(MUSIC_DIR, `${(mood || "neutral").toLowerCase()}.mp3`);
  if (fs.existsSync(candidate)) return candidate;
  return path.join(MUSIC_DIR, "neutral.mp3");
}

const MOTION_ASSETS_DIR = process.env.MOTION_ASSETS_DIR || path.join(__dirname, "motion-assets");

function toAssTimeGlobal(sec) {
  const h = Math.floor(sec / 3600);
  const m = Math.floor((sec % 3600) / 60);
  const s = (sec % 60).toFixed(2);
  return `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(5, "0")}`;
}

function escapeAssText(text) {
  return String(text || "").replace(/\\/g, "\\\\").replace(/\n/g, "\\N").replace(/\{/g, "(").replace(/\}/g, ")");
}

/**
 * Builds a template scene (stat_reveal / comparison / kinetic_text) entirely
 * via ffmpeg + pre-rendered real assets - replaces the earlier Revideo/
 * Puppeteer-based renderer entirely. No browser dependency, no separate
 * render service - everything runs inside this same process.
 *
 * Assets referenced (must exist under MOTION_ASSETS_DIR, see deploy docs):
 *   backgrounds/gradient_charcoal.png, backgrounds/card_left.png,
 *   backgrounds/card_right.png, elements/growing_bar_gold.mov,
 *   icons/<name>.mov, fonts/Inter-*.ttf (installed system-wide in the image)
 */
async function buildTemplateScene(templateName, templateData, duration, outPath, tmpDir) {
  const bg = path.join(MOTION_ASSETS_DIR, "backgrounds", "gradient_charcoal.png");
  const assPath = path.join(tmpDir, `tpl_${Date.now()}_${Math.random().toString(36).slice(2)}.ass`);
  const d = Math.max(duration, 0.5);

  if (templateName === "stat_reveal") {
    const icon = path.join(MOTION_ASSETS_DIR, "icons", "activity.mov");
    const statValue = escapeAssText(templateData?.statValue || "");
    const label = escapeAssText(String(templateData?.label || "").toUpperCase());

    const ass = `[Script Info]\nPlayResX: ${TARGET_W}\nPlayResY: ${TARGET_H}\n\n[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\nStyle: StatNum,Inter Black,180,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,-1,0,0,0,100,100,0,0,1,0,0,2,60,60,900,1\nStyle: StatLabel,Inter,44,&H009CA3CD,&H000000FF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,0,0,2,60,60,760,1\n\n[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\nDialogue: 0,${toAssTimeGlobal(0.3)},${toAssTimeGlobal(d)},StatNum,,0,0,0,,{\\fad(300,0)}${statValue}\nDialogue: 0,${toAssTimeGlobal(0.7)},${toAssTimeGlobal(d)},StatLabel,,0,0,0,,{\\fad(300,0)}${label}\n`;
    await fsp.writeFile(assPath, ass);

    await run(
      ffmpeg()
        .input(bg).inputOptions(["-loop", "1"])
        .input(icon)
        .complexFilter([
          `[1:v]scale=200:200[icn]`,
          `[0:v][icn]overlay=440:280:enable='between(t,0.1,${d})'[bgicon]`,
          `[bgicon]ass=${assPath.replace(/:/g, "\\:")}[final]`,
        ])
        .outputOptions(["-map", "[final]", "-t", String(d), "-c:v", "libx264", "-r", "30", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p"])
        .output(outPath)
    );
  } else if (templateName === "comparison") {
    const cardLeft = path.join(MOTION_ASSETS_DIR, "backgrounds", "card_left.png");
    const cardRight = path.join(MOTION_ASSETS_DIR, "backgrounds", "card_right.png");
    const bar = path.join(MOTION_ASSETS_DIR, "elements", "growing_bar_gold.mov");
    const leftLabel = escapeAssText(String(templateData?.leftLabel || "").toUpperCase());
    const leftValue = escapeAssText(templateData?.leftValue || "");
    const rightLabel = escapeAssText(String(templateData?.rightLabel || "").toUpperCase());
    const rightValue = escapeAssText(templateData?.rightValue || "");

    const ass = `[Script Info]\nPlayResX: ${TARGET_W}\nPlayResY: ${TARGET_H}\n\n[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\nStyle: CardLabel,Inter,32,&H009CA3CD,&H000000FF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,0,0,7,0,0,0,1\nStyle: CardValueL,Inter Black,68,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,0,0,7,0,0,0,1\nStyle: CardValueR,Inter Black,68,&H0000A7D4,&H000000FF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,0,0,7,0,0,0,1\n\n[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\nDialogue: 0,${toAssTimeGlobal(0.3)},${toAssTimeGlobal(d)},CardLabel,,0,0,0,,{\\fad(300,0)\\pos(140,650)}${leftLabel}\nDialogue: 0,${toAssTimeGlobal(0.9)},${toAssTimeGlobal(d)},CardValueL,,0,0,0,,{\\fad(300,0)\\pos(140,720)}${leftValue}\nDialogue: 0,${toAssTimeGlobal(1.3)},${toAssTimeGlobal(d)},CardLabel,,0,0,0,,{\\fad(300,0)\\pos(660,650)}${rightLabel}\nDialogue: 0,${toAssTimeGlobal(1.9)},${toAssTimeGlobal(d)},CardValueR,,0,0,0,,{\\fad(300,0)\\pos(660,720)}${rightValue}\n`;
    await fsp.writeFile(assPath, ass);

    await run(
      ffmpeg()
        .input(bg).inputOptions(["-loop", "1"])
        .input(cardLeft).inputOptions(["-loop", "1"])
        .input(cardRight).inputOptions(["-loop", "1"])
        .input(bar)
        .input(bar)
        .complexFilter([
          `[1:v]scale=420:560[cardL]`,
          `[2:v]scale=420:560[cardR]`,
          `[0:v][cardL]overlay=100:680:enable='gte(t,0.1)'[s1]`,
          `[s1][cardR]overlay=560:680:enable='gte(t,0.5)'[s2]`,
          `[3:v]scale=60:300[barL]`,
          `[s2][barL]overlay=280:900:enable='gte(t,1.0)'[s3]`,
          `[4:v]scale=60:300[barR]`,
          `[s3][barR]overlay=740:900:enable='gte(t,1.4)'[s4]`,
          `[s4]ass=${assPath.replace(/:/g, "\\:")}[final]`,
        ])
        .outputOptions(["-map", "[final]", "-t", String(d), "-c:v", "libx264", "-r", "30", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p"])
        .output(outPath)
    );
  } else if (templateName === "kinetic_text") {
    const line = String(templateData?.line || "").trim();
    const words = line.split(/\s+/).filter(Boolean);
    const perWordDelay = 0.15;
    let events = "";
    words.forEach((w, i) => {
      const start = 0.2 + i * perWordDelay;
      events += `Dialogue: 0,${toAssTimeGlobal(start)},${toAssTimeGlobal(d)},Line,,0,0,0,,{\\fad(150,0)}${escapeAssText(w)}\n`;
    });
    const ass = `[Script Info]\nPlayResX: ${TARGET_W}\nPlayResY: ${TARGET_H}\n\n[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\nStyle: Line,Inter,78,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,-1,0,0,0,100,100,0,0,1,0,0,5,80,80,0,1\n\n[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n${events}`;
    await fsp.writeFile(assPath, ass);

    await run(
      ffmpeg()
        .input(bg).inputOptions(["-loop", "1"])
        .complexFilter([`[0:v]ass=${assPath.replace(/:/g, "\\:")}[final]`])
        .outputOptions(["-map", "[final]", "-t", String(d), "-c:v", "libx264", "-r", "30", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p"])
        .output(outPath)
    );
  } else {
    throw new Error(`Unknown template_name "${templateName}" - expected stat_reveal, comparison, or kinetic_text`);
  }

  return outPath;
}

/**
 * Build an ASS subtitle file with word-level pop-in animation from
 * ElevenLabs character-level timestamps. ASS (not SRT) is used because it
 * supports per-line styling/animation tags that make captions look "designed"
 * rather than default-subtitle.
 *
 * We group characters into words, then into short caption chunks (~3-4 words)
 * so text never floods the vertical-safe zone, and animate each chunk with a
 * quick scale-pop as it appears.
 */
function buildAssFromAlignment(scenes, totalOffsetsSec, commentHook, totalDuration) {
  const header = `[Script Info]
ScriptType: v4.00+
PlayResX: ${TARGET_W}
PlayResY: ${TARGET_H}
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Caption,Montserrat ExtraBold,74,&H0000D7FF,&H000000FF,&H00101010,&H80000000,-1,0,0,0,100,100,0,0,1,5,3,2,60,60,340,1
Style: CommentHook,Montserrat ExtraBold,58,&H00FFFFFF,&H000000FF,&H00202020,&HC0000000,-1,0,0,0,100,100,0,0,3,0,0,2,80,80,420,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
`;

  function toAssTime(sec) {
    const h = Math.floor(sec / 3600);
    const m = Math.floor((sec % 3600) / 60);
    const s = (sec % 60).toFixed(2);
    return `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(5, "0")}`;
  }

  let events = "";
  const WORDS_PER_CHUNK = 3;

  scenes.forEach((scene, sceneIdx) => {
    const alignment = scene?.audio?.alignment;
    if (!alignment) return;

    // Rebuild words with start/end times from character-level data
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

    // Group words into small chunks for readable on-screen captions
    for (let i = 0; i < words.length; i += WORDS_PER_CHUNK) {
      const chunk = words.slice(i, i + WORDS_PER_CHUNK);
      if (!chunk.length || chunk[0].start == null) continue;
      const chunkStart = chunk[0].start + totalOffsetsSec[sceneIdx];
      const chunkEnd = chunk[chunk.length - 1].end + totalOffsetsSec[sceneIdx];
      const text = chunk.map((w) => w.text).join(" ").toUpperCase();

      // \fscx/\fscy pop animation: scales from 60% to 100% over 150ms
      const animatedText = `{\\fad(60,60)\\t(0,150,\\fscx100\\fscy100)\\fscx60\\fscy60}${text}`;

      events += `Dialogue: 0,${toAssTime(chunkStart)},${toAssTime(chunkEnd)},Caption,,0,0,0,,${animatedText}\n`;
    }
  });

  // Append the comment-hook overlay in the final ~1.8s of the video, styled
  // distinctly (boxed background, centered) so it reads as a deliberate
  // call-to-action rather than blending in with the regular captions.
  if (commentHook && totalDuration) {
    const hookDuration = Math.min(1.8, totalDuration * 0.4); // never longer than 40% of a very short video
    const hookStart = Math.max(0, totalDuration - hookDuration);
    const escapedHook = commentHook.toUpperCase().replace(/\\/g, "").replace(/\{/g, "").replace(/\}/g, "");
    events += `Dialogue: 1,${toAssTime(hookStart)},${toAssTime(totalDuration)},CommentHook,,0,0,0,,{\\fad(150,0)}${escapedHook}\n`;
  }

  return header + events;
}

// ---------------------------------------------------------------------------
// Main compose pipeline
// ---------------------------------------------------------------------------

app.post("/compose", async (req, res) => {
  const jobId = crypto.randomUUID();
  const tmpDir = newTmpDir();

  try {
    const { hook, caption_style, comment_hook, data: scenes } = req.body;
    if (!Array.isArray(scenes) || scenes.length === 0) {
      return res.status(400).json({ success: false, error: "No scenes provided" });
    }

    console.log(`[job ${jobId}] Composing ${scenes.length} scenes`);

    // 1. Prepare each scene's visual asset. Two paths now:
    //    - "template": build directly via ffmpeg + real pre-rendered assets
    //      (icons, fonts, backgrounds) - no external render service needed.
    //    - "stock": download the Pexels images array as before (multiple per
    //      scene, cut every ~5s for visual variety).
    const sceneFiles = [];
    for (let i = 0; i < scenes.length; i++) {
      const scene = scenes[i];
      const isTemplate = scene?.visual_source === "template";

      let imagePaths = null;
      let templateVideoPath = null;

      if (isTemplate) {
        if (!scene.template_name) {
          throw new Error(`Scene ${i} has visual_source=template but no template_name`);
        }
        // We don't know the exact narration duration yet (that's determined
        // by the TTS audio below) - build at a reasonable default length,
        // the existing tpad/trim logic downstream already handles matching
        // it precisely to the real audio duration.
        templateVideoPath = path.join(tmpDir, `scene_${i}_template.mp4`);
        await buildTemplateScene(scene.template_name, scene.template_data, 4.0, templateVideoPath, tmpDir);
      } else {
        const imageUrls = scene?.images;
        if (!Array.isArray(imageUrls) || !imageUrls.length) {
          throw new Error(`Scene ${i} missing images array (and visual_source is not "template")`);
        }
        imagePaths = [];
        for (let j = 0; j < imageUrls.length; j++) {
          const p = path.join(tmpDir, `scene_${i}_img_${j}.png`);
          await downloadFile(imageUrls[j], p);
          imagePaths.push(p);
        }
      }

      const audioPath = path.join(tmpDir, `voice_${i}.mp3`);
      if (scene?.audio?.audio_base64) {
        await writeBase64(scene.audio.audio_base64, audioPath);
      } else if (scene?.audio?.audio_url) {
        await downloadFile(scene.audio.audio_url, audioPath);
      } else {
        throw new Error(`Scene ${i} missing audio`);
      }

      sceneFiles.push({ imagePaths, templateVideoPath, audioPath, scene });
    }

    // 2. Normalize each scene. NEW: each scene now shows MULTIPLE images,
    //    cutting to a new one roughly every 5 seconds, instead of one static
    //    image for the whole scene - keeps the frame visually changing so
    //    viewers stay hooked rather than swiping on a long static hold.
    const CUT_INTERVAL_SEC = 5;
    const normalizedPaths = [];
    for (let i = 0; i < sceneFiles.length; i++) {
      const { imagePaths, templateVideoPath, audioPath } = sceneFiles[i];
      const duration = await ffprobeDuration(audioPath);
      const outPath = path.join(tmpDir, `norm_${i}.mp4`);

      if (templateVideoPath) {
        // Pre-rendered Revideo template: already animated, so skip the
        // multi-cut/pan treatment entirely - just match it to this scene's
        // audio duration and mux. If the template runs shorter than the
        // narration, hold its last frame to fill the gap rather than looping
        // the whole animation (a repeat would look like an obvious glitch;
        // a held final frame reads as an intentional pause).
        const templateDuration = await ffprobeDuration(templateVideoPath);
        const audioFadeDur = 0.1;
        const audioFadeOutStart = Math.max(0, duration - audioFadeDur);

        const videoFilter =
          templateDuration < duration
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
              "-af", `loudnorm=I=-16:TP=-1.5:LRA=11,afade=t=in:st=0:d=${audioFadeDur},afade=t=out:st=${audioFadeOutStart.toFixed(3)}:d=${audioFadeDur}`,
              "-c:v", "libx264",
              "-r", "30", // force consistent fps - Revideo's native render fps can differ from Pexels segments, and mixed fps across concat inputs silently stretches the final video track (confirmed root cause of the duration-mismatch bug)
              "-preset", "veryfast",
              "-crf", "20",
              "-pix_fmt", "yuv420p",
              "-c:a", "aac",
              "-b:a", "192k",
            ])
            .output(outPath)
        );

        normalizedPaths.push(outPath);
        continue; // skip the stock-image multi-cut logic below entirely
      }

      // Even split into ~5s segments (no awkward short remainder at the end).
      // Capped by how many distinct images we actually have - if a scene runs
      // longer than 5s * imagePaths.length, images repeat rather than error.
      const numSegments = Math.max(1, Math.round(duration / CUT_INTERVAL_SEC));
      const segDuration = duration / numSegments;

      const audioFadeDur = 0.1;
      const audioFadeOutStart = Math.max(0, duration - audioFadeDur);

      // 2a. Build one silent sub-clip per segment, each a different image,
      // with the same pan/color-grade/sharpen treatment as before, scaled to
      // that segment's own (shorter) duration. Cycle images if we need more
      // segments than we have distinct photos for this scene.
      const segmentPaths = [];
      for (let seg = 0; seg < numSegments; seg++) {
        const imgPath = imagePaths[seg % imagePaths.length];
        const segOutPath = path.join(tmpDir, `scene_${i}_seg_${seg}.mp4`);
        const isFirst = seg === 0;
        const isLast = seg === numSegments - 1;
        const segVideoFadeDur = 0.15;
        const segFadeOutStart = Math.max(0, segDuration - segVideoFadeDur);

        // Alternate pan direction per segment for subtle variety across cuts
        // instead of every image panning the same way.
        const panLeftToRight = seg % 2 === 0;
        const xExpr = panLeftToRight
          ? `(iw-${TARGET_W})*t/${Math.max(segDuration, 0.1).toFixed(3)}`
          : `(iw-${TARGET_W})*(1-t/${Math.max(segDuration, 0.1).toFixed(3)})`;

        const fadeFilters = [];
        if (isFirst) fadeFilters.push(`fade=t=in:st=0:d=${segVideoFadeDur}`);
        if (isLast) fadeFilters.push(`fade=t=out:st=${segFadeOutStart.toFixed(3)}:d=${segVideoFadeDur}`);
        const fadeChain = fadeFilters.length ? ',' + fadeFilters.join(',') : '';

        await run(
          ffmpeg()
            .input(imgPath)
            .inputOptions(["-loop", "1"])
            .complexFilter([
              `[0:v]scale=${oversizeW}:${oversizeH}:force_original_aspect_ratio=increase,crop=${oversizeW}:${oversizeH},crop=${TARGET_W}:${TARGET_H}:x='${xExpr}':y='(ih-${TARGET_H})/2',eq=contrast=1.08:saturation=1.18:brightness=0.01,unsharp=5:5:0.6:5:5:0.0${fadeChain}[cropped]`,
            ])
            .outputOptions([
              "-map", "[cropped]",
              "-t", String(segDuration),
              "-c:v", "libx264",
              "-r", "30", // same fix as the template branch - keep every clip type at one consistent fps before concat
              "-preset", "veryfast",
              "-crf", "20",
              "-pix_fmt", "yuv420p",
              "-an",
            ])
            .output(segOutPath)
        );
        segmentPaths.push(segOutPath);
      }

      // 2b. Concatenate this scene's segments into one silent scene-length
      // video via the concat demuxer (the reliable method - see note below
      // on the outer scene-to-scene concat for why this beats xfade chains).
      const sceneVideoPath = path.join(tmpDir, `scene_${i}_video.mp4`);
      if (segmentPaths.length === 1) {
        fs.copyFileSync(segmentPaths[0], sceneVideoPath);
      } else {
        const listPath = path.join(tmpDir, `scene_${i}_seglist.txt`);
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

      // 2c. Mux the concatenated silent scene video with its single audio
      // track, loudness-normalize, and trim to the exact audio duration.
      await run(
        ffmpeg()
          .input(sceneVideoPath)
          .input(audioPath)
          .outputOptions([
            "-map", "0:v",
            "-map", "1:a",
            "-t", String(duration),
            "-af", `loudnorm=I=-16:TP=-1.5:LRA=11,afade=t=in:st=0:d=${audioFadeDur},afade=t=out:st=${audioFadeOutStart.toFixed(3)}:d=${audioFadeDur}`,
            "-c:v", "copy",
            "-c:a", "aac",
            "-b:a", "192k",
          ])
          .output(outPath)
      );

      normalizedPaths.push(outPath);
    }

    // 3. Compute per-scene start offsets (for caption timing) and concatenate
    //    using the CONCAT DEMUXER - the reliable, industry-standard method.
    //    (A prior version used chained xfade filters for crossfade transitions,
    //    but multi-input xfade chaining is fragile and was silently dropping
    //    clips past the first pair - confirmed via VPS logs showing only the
    //    first scene's duration in the final output. Concat demuxer guarantees
    //    every clip is included; hard cuts instead of crossfades for now.)
    const durations = [];
    for (const p of normalizedPaths) durations.push(await ffprobeDuration(p));

    const offsets = [0];
    for (let i = 1; i < durations.length; i++) {
      offsets.push(offsets[i - 1] + durations[i - 1]);
    }

    const concatPath = path.join(tmpDir, "concat.mp4");

    if (normalizedPaths.length === 1) {
      fs.copyFileSync(normalizedPaths[0], concatPath);
    } else {
      // Write the concat demuxer list file. NOTE: this step re-encodes
      // (not stream-copy) even though all clips share the same codec/res/fps.
      // Stream-copy trusts each input's existing container timestamps as-is -
      // this broke when a scene's clip was itself the product of NESTED
      // concatenation (our multi-segment Pexels cuts, or a Revideo template
      // clip), where internal timestamp irregularities are invisible in the
      // reported duration but cause the demuxer to misjudge boundaries,
      // producing a longer-than-expected final file. Re-encoding forces a
      // clean rebuild of continuous timestamps, trading a little processing
      // time for correctness.
      const concatListPath = path.join(tmpDir, "concat_list.txt");
      const concatListContent = normalizedPaths
        .map((p) => `file '${p.replace(/'/g, "'\\''")}'`)
        .join("\n");
      await fsp.writeFile(concatListPath, concatListContent);

      console.log(`Concatenating ${normalizedPaths.length} clips via concat demuxer (re-encoded)`);

      await run(
        ffmpeg()
          .input(concatListPath)
          .inputOptions(["-f", "concat", "-safe", "0"])
          .outputOptions([
            "-c:v", "libx264",
            "-r", "30", // belt-and-suspenders - real fix is normalizing every input clip above, but this catches anything unexpected
            "-preset", "veryfast",
            "-crf", "20",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            "-b:a", "192k",
            "-fflags", "+genpts",
          ])
          .output(concatPath)
      );

      // Sanity check: confirm the concatenated file's duration roughly matches
      // the sum of all individual clip durations - catches silent truncation
      // immediately instead of shipping a short video unnoticed.
      const expectedDuration = durations.reduce((a, b) => a + b, 0);
      const actualDuration = await ffprobeDuration(concatPath);
      if (Math.abs(actualDuration - expectedDuration) > 1.5) {
        throw new Error(
          `Concat output duration (${actualDuration.toFixed(1)}s) does not match ` +
          `expected sum of clips (${expectedDuration.toFixed(1)}s) - concatenation likely failed silently. ` +
          `Clip count: ${normalizedPaths.length}, individual durations: ${JSON.stringify(durations)}`
        );
      }
    }

    // 4. Build word-level animated captions (ASS) from ElevenLabs alignment,
    //    plus the comment-hook overlay in the final seconds.
    const totalVideoDuration = durations.reduce((a, b) => a + b, 0);
    const assContent = buildAssFromAlignment(scenes, offsets, comment_hook, totalVideoDuration);
    const assPath = path.join(tmpDir, "captions.ass");
    await fsp.writeFile(assPath, assContent);

    // 5. Add background music, auto-ducked under the voice via sidechaincompress,
    //    then burn in captions. Single final pass for quality (avoid re-encoding twice).
    const musicPath = pickMusicTrack(caption_style);
    const finalPath = path.join(tmpDir, "final.mp4");
    const outputFileName = `short_${jobId}.mp4`;
    const outputFullPath = path.join(OUTPUT_DIR, outputFileName);
    await fsp.mkdir(OUTPUT_DIR, { recursive: true });

    const hasMusic = fs.existsSync(musicPath);

    if (hasMusic) {
      await run(
        ffmpeg()
          .input(concatPath)
          .input(musicPath)
          .complexFilter([
            // Loop music if shorter than video, trim to match
            `[1:a]aloop=loop=-1:size=2e9,volume=0.25[music]`,
            // Duck music under the voice track whenever voice is present
            `[music][0:a]sidechaincompress=threshold=0.05:ratio=8:attack=5:release=300[duckedmusic]`,
            `[0:a][duckedmusic]amix=inputs=2:duration=first:dropout_transition=2[mixedaudio]`,
            // Burn captions onto video
            `[0:v]ass=${assPath}[captioned]`,
          ])
          .outputOptions([
            "-map", "[captioned]",
            "-map", "[mixedaudio]",
            "-c:v", "libx264",
            "-preset", "medium",
            "-crf", "18",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            "-b:a", "192k",
            "-shortest",
          ])
          .output(finalPath)
      );
    } else {
      // No music track available yet — still burn captions, keep voice only
      await run(
        ffmpeg()
          .input(concatPath)
          .complexFilter([`[0:v]ass=${assPath}[captioned]`])
          .outputOptions([
            "-map", "[captioned]",
            "-map", "0:a",
            "-c:v", "libx264",
            "-preset", "medium",
            "-crf", "18",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            "-b:a", "192k",
          ])
          .output(finalPath)
      );
    }

    await fsp.copyFile(finalPath, outputFullPath);

    // Cleanup tmp working dir
    await fsp.rm(tmpDir, { recursive: true, force: true });

    console.log(`[job ${jobId}] Done -> ${outputFullPath}`);
    return res.json({ success: true, output_path: outputFullPath, job_id: jobId });
  } catch (err) {
    console.error(`[job ${jobId}] FAILED:`, err);
    console.error(`[job ${jobId}] Preserving tmp dir for debugging: ${tmpDir}`);
    // NOTE: intentionally NOT deleting tmpDir here right now, while actively
    // debugging the concat duration mismatch - we need the actual norm_*.mp4
    // files to inspect. Restore the cleanup once this is resolved, or disk
    // usage will grow with every failed run.
    return res.status(500).json({ success: false, error: err.message, debug_tmp_dir: tmpDir });
  }
});

const PORT = process.env.PORT || 4000;
app.listen(PORT, () => console.log(`FFmpeg compose service listening on :${PORT}`));
