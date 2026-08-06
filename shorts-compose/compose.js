/**
 * compose.js
 * -----------------------------------------------------------------------
 * Express endpoint: POST /compose
 * High-retention short-form video compositor (TikTok/Reels/Shorts)
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
// In-memory job store for the async compose pattern - avoids holding a
// single HTTP connection open for the whole render (which was hitting
// Cloudflare's 120s proxy timeout as render time grew with more features).
const jobStore = new Map();


const OUTPUT_DIR = process.env.OUTPUT_DIR || "/outputs";
app.use("/outputs", express.static(OUTPUT_DIR));

const MUSIC_DIR = process.env.MUSIC_DIR || path.join(__dirname, "music");
const MOTION_ASSETS_DIR = process.env.MOTION_ASSETS_DIR || path.join(__dirname, "motion-assets");
const TOPIC_HISTORY_PATH = process.env.TOPIC_HISTORY_PATH || path.join(__dirname, "topic_history.json");
const TOPIC_HISTORY_MAX = 90; // raised from 30 - at 5x/day, 30 entries aged out in ~6 days, letting real hits (e.g. "Everyone jumped at once") get regenerated as unintentional near-duplicates once they rolled off

const TARGET_W = 1080;
const TARGET_H = 1920;

// Detect video encoder hardware support (libx264 fallback)
const V_ENCODER = process.env.USE_NVENC ? "h264_nvenc" : "libx264";

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

function getColorGrade(mood) {
  // Verified via real HSV measurement: serious < neutral < upbeat < funny,
  // in both saturation and brightness - a sensible emotional ordering.
  const grades = {
    upbeat: "eq=contrast=1.18:saturation=1.55:brightness=0.03,colorbalance=rs=0.15:gs=0.04:bs=-0.10",
    serious: "eq=contrast=1.20:saturation=0.85:brightness=-0.02,colorbalance=rs=-0.05:gs=0.0:bs=0.08",
    funny: "eq=contrast=1.12:saturation=1.75:brightness=0.04,colorbalance=rs=0.12:gs=0.10:bs=-0.08",
    neutral: "eq=contrast=1.12:saturation=1.2:brightness=0.01",
  };
  return grades[mood] || grades.neutral;
}

function pickMusicTrack(mood) {
  const candidate = path.join(MUSIC_DIR, `${(mood || "neutral").toLowerCase()}.mp3`);
  if (fs.existsSync(candidate)) return candidate;
  return path.join(MUSIC_DIR, "neutral.mp3");
}

function toAssTimeGlobal(sec) {
  const h = Math.floor(sec / 3600);
  const m = Math.floor((sec % 3600) / 60);
  const s = (sec % 60).toFixed(2);
  return `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(5, "0")}`;
}

function escapeAssText(text) {
  return String(text || "").replace(/\\/g, "\\\\").replace(/\n/g, "\\N").replace(/\{/g, "(").replace(/\}/g, ")");
}

// ---------------------------------------------------------------------------
// Motion Template Engine
// ---------------------------------------------------------------------------

async function buildTemplateScene(templateName, templateData, duration, outPath, tmpDir) {
  const bg = path.join(MOTION_ASSETS_DIR, "backgrounds", "gradient_charcoal.png");
  const assPath = path.join(tmpDir, `tpl_${Date.now()}_${Math.random().toString(36).slice(2)}.ass`);
  const safeAssPath = assPath.replace(/\\/g, "/").replace(/:/g, "\\:");
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
          `[0:v][icn]overlay=440:280:enable=between(t\\,0.1\\,${d})[bgicon]`,
          `[bgicon]ass=${safeAssPath}[final]`,
        ])
        .outputOptions(["-map", "[final]", "-t", String(d), "-c:v", V_ENCODER, "-r", "30", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p"])
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
          `[0:v][cardL]overlay=100:680:enable=gte(t\\,0.1)[s1]`,
          `[s1][cardR]overlay=560:680:enable=gte(t\\,0.5)[s2]`,
          `[3:v]scale=60:300[barL]`,
          `[s2][barL]overlay=280:900:enable=gte(t\\,1.0)[s3]`,
          `[4:v]scale=60:300[barR]`,
          `[s3][barR]overlay=740:900:enable=gte(t\\,1.4)[s4]`,
          `[s4]ass=${safeAssPath}[final]`,
        ])
        .outputOptions(["-map", "[final]", "-t", String(d), "-c:v", V_ENCODER, "-r", "30", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p"])
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
        .complexFilter([`[0:v]ass=${safeAssPath}[final]`])
        .outputOptions(["-map", "[final]", "-t", String(d), "-c:v", V_ENCODER, "-r", "30", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p"])
        .output(outPath)
    );
  } else {
    throw new Error(`Unknown template_name "${templateName}"`);
  }

  return outPath;
}

// ---------------------------------------------------------------------------
// Karaoke Animated ASS Subtitle Builder
// ---------------------------------------------------------------------------

function buildAssFromAlignment(scenes, totalOffsetsSec, commentHook, totalDuration) {
  const header = `[Script Info]
ScriptType: v4.00+
PlayResX: ${TARGET_W}
PlayResY: ${TARGET_H}
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Caption,Montserrat ExtraBold,76,&H00FFFFFF,&H000000FF,&H00101010,&H80000000,-1,0,0,0,100,100,0,0,1,5,3,2,60,60,420,1
Style: CommentHook,Montserrat ExtraBold,58,&H00FFFFFF,&H000000FF,&H00202020,&HC0000000,-1,0,0,0,100,100,0,0,3,0,0,2,80,80,680,1

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
  const WORDS_PER_CHUNK = 2; // High-retention short-form standard

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
        const wStart = w.start + totalOffsetsSec[sceneIdx];
        const wEnd = w.end + totalOffsetsSec[sceneIdx];
        const highlightText = chunk
          .map((item) => {
            if (item.text === w.text) {
              return `{\\c&H0000FFFF&\\fscx110\\fscy110}${item.text.toUpperCase()}{\\r}`;
            }
            return `{\\c&H00FFFFFF&}${item.text.toUpperCase()}`;
          })
          .join(" ");

        events += `Dialogue: 0,${toAssTime(wStart)},${toAssTime(wEnd)},Caption,,0,0,0,,${highlightText}\n`;
      });
    }
  });

  if (commentHook && totalDuration) {
    const hookDuration = Math.min(1.8, totalDuration * 0.4);
    const hookStart = Math.max(0, totalDuration - hookDuration);
    const escapedHook = commentHook.toUpperCase().replace(/\\/g, "").replace(/\{/g, "").replace(/\}/g, "");
    events += `Dialogue: 1,${toAssTime(hookStart)},${toAssTime(totalDuration)},CommentHook,,0,0,0,,{\\fscx0\\fscy0\\t(0,200,\\fscx120\\fscy120)\\t(200,300,\\fscx100\\fscy100)}${escapedHook}\n`;
  }

  return header + events;
}

// ---------------------------------------------------------------------------
// Main Express Compose Pipeline
// ---------------------------------------------------------------------------

async function runComposeJob(reqBody, jobId, tmpDir) {
  try {
    const { hook, caption_style, comment_hook, data: scenes } = reqBody;
    if (!Array.isArray(scenes) || scenes.length === 0) {
      throw new Error("No scenes provided");
    }

    console.log(`[job ${jobId}] Composing ${scenes.length} scenes`);

    // 1. Parallel Scene Asset Fetching
    const sceneFiles = await Promise.all(
      scenes.map(async (scene, i) => {
        const isTemplate = scene?.visual_source === "template";
        let imagePaths = null;
        let templateVideoPath = null;

        const isStockVideo = !isTemplate && !!scene?.video_url;
        let stockVideoPath = null;

        if (isTemplate) {
          if (!scene.template_name) throw new Error(`Scene ${i} has visual_source=template but no template_name`);
          templateVideoPath = path.join(tmpDir, `scene_${i}_template.mp4`);
          await buildTemplateScene(scene.template_name, scene.template_data, 4.0, templateVideoPath, tmpDir);
        } else if (isStockVideo) {
          // Pexels video-clip sourcing - real motion instead of panned stills
          stockVideoPath = path.join(tmpDir, `scene_${i}_stockvideo.mp4`);
          await downloadFile(scene.video_url, stockVideoPath);
        } else {
          const imageUrls = scene?.images;
          if (!Array.isArray(imageUrls) || !imageUrls.length) {
            throw new Error(`Scene ${i} missing images array (and no video_url present)`);
          }
          imagePaths = await Promise.all(
            imageUrls.map(async (url, j) => {
              const p = path.join(tmpDir, `scene_${i}_img_${j}.png`);
              return await downloadFile(url, p);
            })
          );
        }

        const audioPath = path.join(tmpDir, `voice_${i}.mp3`);
        if (scene?.audio?.audio_base64) {
          await writeBase64(scene.audio.audio_base64, audioPath);
        } else if (scene?.audio?.audio_url) {
          await downloadFile(scene.audio.audio_url, audioPath);
        } else {
          throw new Error(`Scene ${i} missing audio`);
        }

        return { imagePaths, templateVideoPath, stockVideoPath, audioPath, scene };
      })
    );

    // 2. Normalize and apply editor dynamics per scene
    const normalizedPaths = [];
    for (let i = 0; i < sceneFiles.length; i++) {
      const { imagePaths, templateVideoPath, stockVideoPath, audioPath } = sceneFiles[i];
      const duration = await ffprobeDuration(audioPath);
      const outPath = path.join(tmpDir, `norm_${i}.mp4`);

      if (templateVideoPath) {
        const templateDuration = await ffprobeDuration(templateVideoPath);
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
              "-af", `loudnorm=I=-16:TP=-1.5:LRA=11`,
              "-c:v", V_ENCODER,
              "-r", "30",
              "-preset", "veryfast",
              "-crf", "20",
              "-pix_fmt", "yuv420p",
              "-c:a", "aac",
              "-b:a", "192k",
            ])
            .output(outPath)
        );

        normalizedPaths.push(outPath);
        continue;
      }

      if (stockVideoPath) {
        // Real ffprobe'd duration, not the Pexels-reported metadata field -
        // avoids any drift between what the API claims and the actual file.
        const stockDuration = await ffprobeDuration(stockVideoPath);
        const needsPad = stockDuration < duration;
        const videoFilter = needsPad
          ? `[0:v]scale=${TARGET_W}:${TARGET_H}:force_original_aspect_ratio=increase,crop=${TARGET_W}:${TARGET_H},tpad=stop_mode=clone:stop_duration=${(duration - stockDuration + 0.1).toFixed(3)},${getColorGrade(caption_style)},vignette=angle=PI/12[padded]`
          : `[0:v]scale=${TARGET_W}:${TARGET_H}:force_original_aspect_ratio=increase,crop=${TARGET_W}:${TARGET_H},${getColorGrade(caption_style)},vignette=angle=PI/12[padded]`;

        await run(
          ffmpeg()
            .input(stockVideoPath)
            .input(audioPath)
            .complexFilter([videoFilter])
            .outputOptions([
              "-map", "[padded]",
              "-map", "1:a", // narration only - the stock clip's own audio is never mapped, discarded entirely
              "-t", String(duration),
              "-af", `loudnorm=I=-16:TP=-1.5:LRA=11`,
              "-c:v", V_ENCODER,
              "-r", "30",
              "-preset", "veryfast",
              "-crf", "20",
              "-pix_fmt", "yuv420p",
              "-c:a", "aac",
              "-b:a", "192k",
            ])
            .output(outPath)
        );

        normalizedPaths.push(outPath);
        continue;
      }

      // Fast cuts for scene 0 (1.8s hook), body scenes cut at 2.5s
      const CUT_INTERVAL_SEC = i === 0 ? 1.8 : 2.5;
      const numSegments = Math.max(1, Math.round(duration / CUT_INTERVAL_SEC));
      const segDuration = duration / numSegments;
      const fps = 30;
      const totalFrames = Math.ceil(segDuration * fps);

      const segmentPaths = [];
      for (let seg = 0; seg < numSegments; seg++) {
        const imgPath = imagePaths[seg % imagePaths.length];
        const segOutPath = path.join(tmpDir, `scene_${i}_seg_${seg}.mp4`);

        const panLeftToRight = seg % 2 === 0;

        let filterGraph = [];

        if (i === 0 && seg === 0) {
          // Dynamic Zoom + Pan Hook Effect using zoompan
          const xExpr = panLeftToRight
            ? `'iw*0.05*on/${totalFrames}'`
            : `'iw*0.05*(1-on/${totalFrames})'`;

          filterGraph = [
            `[0:v]zoompan=z='if(lte(on,15),1.15,1.15-0.15*(on-15)/${totalFrames})':x=${xExpr}:y='ih*0.05':d=${totalFrames}:s=${TARGET_W}x${TARGET_H}:fps=${fps}[zoomed]`,
            `[zoomed]${getColorGrade(caption_style)}[eqed]`,
            `[eqed]unsharp=5:5:0.8:5:5:0.0[cropped]`
          ];
        } else {
          // Standard Ken Burns Pan + Punch-In Transition (same verified
          // conditional-zoom pattern proven on the scene-0 hook effect,
          // now applied to every cut for a consistent "snap" feel)
          const xExpr = panLeftToRight
            ? `'iw*0.08*on/${totalFrames}'`
            : `'iw*0.08*(1-on/${totalFrames})'`;
          const punchFrames = Math.min(10, Math.round(totalFrames * 0.2));

          filterGraph = [
            `[0:v]zoompan=z='if(lte(on,${punchFrames}),1.18-0.06*on/${punchFrames},1.12)':x=${xExpr}:y='ih*0.06':d=${totalFrames}:s=${TARGET_W}x${TARGET_H}:fps=${fps}[zoomed]`,
            `[zoomed]${getColorGrade(caption_style)}[eqed]`,
            `[eqed]unsharp=5:5:0.8:5:5:0.0[cropped]`
          ];
        }

        await run(
          ffmpeg()
            .input(imgPath)
            .complexFilter(filterGraph)
            .outputOptions([
              "-map", "[cropped]",
              "-t", String(segDuration),
              "-c:v", V_ENCODER,
              "-r", String(fps),
              "-preset", "veryfast",
              "-crf", "20",
              "-pix_fmt", "yuv420p",
              "-an",
            ])
            .output(segOutPath)
        );
        segmentPaths.push(segOutPath);
      }

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

      await run(
        ffmpeg()
          .input(sceneVideoPath)
          .input(audioPath)
          .outputOptions([
            "-map", "0:v",
            "-map", "1:a",
            "-t", String(duration),
            "-af", `loudnorm=I=-16:TP=-1.5:LRA=11`,
            "-c:v", "copy",
            "-c:a", "aac",
            "-b:a", "192k",
          ])
          .output(outPath)
      );

      normalizedPaths.push(outPath);
    }

    // 3. Demux Concat Pass
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
      const concatListPath = path.join(tmpDir, "concat_list.txt");
      const concatListContent = normalizedPaths
        .map((p) => `file '${p.replace(/'/g, "'\\''")}'`)
        .join("\n");
      await fsp.writeFile(concatListPath, concatListContent);

      await run(
        ffmpeg()
          .input(concatListPath)
          .inputOptions(["-f", "concat", "-safe", "0"])
          .outputOptions([
            "-c:v", V_ENCODER,
            "-r", "30",
            "-preset", "veryfast",
            "-crf", "20",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            "-b:a", "192k",
            "-fflags", "+genpts",
          ])
          .output(concatPath)
      );
    }

    // 4. Generate Subtitles (Karaoke Highlight ASS Format)
    const totalVideoDuration = durations.reduce((a, b) => a + b, 0);
    const assContent = buildAssFromAlignment(scenes, offsets, comment_hook, totalVideoDuration);
    const assPath = path.join(tmpDir, "captions.ass");
    await fsp.writeFile(assPath, assContent);

// 5. Sound Design, Audio Mixing & Final Burn-in
    const musicPath = pickMusicTrack(caption_style);
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

    // Build synced SFX events from REAL scene timing - a whoosh at every
    // scene cut, and an impact + leading riser at every template reveal
    // (verified via real waveform peak-detection during development: exact
    // sample-accurate timing, not approximate).
    const sfxEvents = [];
    for (let i = 1; i < scenes.length; i++) {
      if (sfxAvailable.whoosh) sfxEvents.push({ type: "whoosh", time: offsets[i], volume: 0.35 });
    }
    scenes.forEach((s, i) => {
      if (s.visual_source === "template") {
        if (sfxAvailable.impact) sfxEvents.push({ type: "impact", time: offsets[i], volume: 0.5 });
        if (sfxAvailable.riser) sfxEvents.push({ type: "riser", time: Math.max(0, offsets[i] - 0.8), volume: 0.3 });
      }
    });

    const finalPath = path.join(tmpDir, "final.mp4");
    const outputFileName = `short_${jobId}.mp4`;
    const outputFullPath = path.join(OUTPUT_DIR, outputFileName);
    await fsp.mkdir(OUTPUT_DIR, { recursive: true });

    const safeAssPath = assPath.replace(/\\/g, "/").replace(/:/g, "\\:");
    const hasMusic = fs.existsSync(musicPath);

    const finalCmd = ffmpeg().input(concatPath);
    if (hasMusic) finalCmd.input(musicPath);
    sfxEvents.forEach((ev) => finalCmd.input(sfxFiles[ev.type]));

    // Input indices: 0=video, [1]=music if present, then one per SFX event
    let nextInputIdx = 1;
    const musicInputIdx = hasMusic ? nextInputIdx++ : null;
    const sfxInputIndices = sfxEvents.map(() => nextInputIdx++);

    const audioFilterParts = [];
    const mixLabels = ["0:a"];

    if (hasMusic) {
      audioFilterParts.push(`[${musicInputIdx}:a]aloop=loop=-1:size=2e9,volume=0.18[music]`);
      audioFilterParts.push(`[music][0:a]sidechaincompress=threshold=0.03:ratio=10:attack=10:release=180[duckedmusic]`);
      mixLabels.push("duckedmusic");
    }

    sfxEvents.forEach((ev, idx) => {
      const inputIdx = sfxInputIndices[idx];
      const ms = Math.round(ev.time * 1000);
      const label = `sfx${idx}`;
      audioFilterParts.push(`[${inputIdx}:a]volume=${ev.volume},adelay=${ms}|${ms}[${label}]`);
      mixLabels.push(label);
    });

    if (mixLabels.length > 1) {
      audioFilterParts.push(`[${mixLabels.join("][")}]amix=inputs=${mixLabels.length}:duration=first[mixedaudio]`);
    }

    const videoFilter = `[0:v]vignette=angle=PI/12[polished]`; // film grain removed - confirmed via real render test to bloat file size ~14.7x (temporal per-frame noise defeats H.264 inter-frame prediction), turning a ~20s Short into a 500MB+ file
    const captionFilter = `[polished]ass=${safeAssPath}[captioned]`;
    const finalFilters = [...audioFilterParts, videoFilter, captionFilter];

    finalCmd.complexFilter(finalFilters);
    finalCmd.outputOptions([
      "-map", "[captioned]",
      "-map", mixLabels.length > 1 ? "[mixedaudio]" : "0:a",
      "-c:v", V_ENCODER,
      "-preset", "medium",
      "-crf", "18",
      "-pix_fmt", "yuv420p",
      "-c:a", "aac",
      "-b:a", "192k",
      "-shortest",
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
// Async job API - /compose starts the render and returns immediately with a
// job_id (never holds the HTTP connection open), /compose-status/:jobId is
// polled by the caller (n8n) until the render finishes. This is what
// actually fixes the Cloudflare 524 timeout - not a bigger timeout number,
// but never holding one long connection open in the first place.
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
    // Clear after first successful fetch - jobs aren't meant to be polled
    // forever, and this keeps the in-memory store from growing unbounded.
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
app.listen(PORT, () => console.log(`FFmpeg compose engine listening on port :${PORT}`));