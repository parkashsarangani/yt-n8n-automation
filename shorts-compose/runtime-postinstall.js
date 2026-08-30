#!/usr/bin/env node
"use strict";

/**
 * ffmpeg-static is retained as a portability fallback, but its bundled binary
 * deliberately omits some input devices/filters (notably lavfi in our Linux
 * build). The production image already installs Debian's full FFmpeg package.
 *
 * compose.js and brollResolver.js historically require("ffmpeg-static") and
 * therefore ignore PATH. During install, replace only that package's binary
 * with a symlink to the full system binary when one is available. Code keeps
 * the same stable path/API while production gains lavfi and the complete
 * codec/filter surface. Developer machines without system FFmpeg keep the
 * package fallback unchanged.
 */
const fs = require("fs");

const systemFfmpeg = process.env.SYSTEM_FFMPEG_PATH || "/usr/bin/ffmpeg";

if (!fs.existsSync(systemFfmpeg)) {
  console.log(`[runtime-postinstall] system FFmpeg not found at ${systemFfmpeg}; keeping ffmpeg-static fallback`);
  process.exit(0);
}

let staticPath;
try {
  staticPath = require("ffmpeg-static");
} catch (err) {
  console.error(`[runtime-postinstall] cannot resolve ffmpeg-static: ${err.message}`);
  process.exit(1);
}

if (!staticPath) {
  console.error("[runtime-postinstall] ffmpeg-static returned no executable path");
  process.exit(1);
}

try {
  let alreadySystem = false;
  try {
    alreadySystem = fs.realpathSync(staticPath) === fs.realpathSync(systemFfmpeg);
  } catch {}

  if (!alreadySystem) {
    fs.rmSync(staticPath, { force: true });
    fs.symlinkSync(systemFfmpeg, staticPath);
  }

  const resolved = fs.realpathSync(staticPath);
  if (resolved !== fs.realpathSync(systemFfmpeg)) {
    throw new Error(`expected ${staticPath} to resolve to ${systemFfmpeg}, got ${resolved}`);
  }
  console.log(`[runtime-postinstall] ffmpeg-static path now uses full system FFmpeg: ${resolved}`);
} catch (err) {
  console.error(`[runtime-postinstall] failed to select full system FFmpeg: ${err.message}`);
  process.exit(1);
}
