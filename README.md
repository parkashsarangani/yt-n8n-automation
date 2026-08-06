# YouTube Shorts Facts Automation Pipeline

A fully automated pipeline that generates, voices, composes, and uploads YouTube
Shorts — posting 5x/day with zero manual intervention.

## Architecture

```
n8n (workflow orchestration)
  │
  ├─ Claude API — open-ended topic selection, script writing (2-stage), editorial review
  ├─ ElevenLabs — text-to-speech with word-level timestamps
  ├─ Pexels API — stock VIDEO clips for scenes that need real footage
  ├─ shorts-compose (this repo) — ffmpeg-based video assembly, async job-polling
  │    ├─ Stock scenes: real Pexels video clips, scaled/cropped/graded to fill frame
  │    ├─ Template scenes: motion-graphics (stat reveals, comparisons,
  │    │  kinetic text) built from real licensed assets - no browser/
  │    │  Puppeteer dependency, pure ffmpeg + pre-rendered clips
  │    ├─ Mood-based color grading, vignette, synced whoosh/impact/riser SFX
  │    └─ ASS-based animated karaoke captions + spoken + on-screen CTA
  └─ YouTube Data API — upload, AI-content disclosure
```

All of this is self-hosted on a local Ubuntu server, exposed via a Cloudflare
Tunnel, with `n8n` and `shorts-compose` running as Docker Compose services.

### Why `shorts-compose` uses async job-polling, not a single request

Render time grew past Cloudflare's 120s proxy timeout as features were added
(motion grading, synced SFX, heavier per-segment processing), causing hard
524 timeouts even though the render itself succeeded. `/compose` now returns
a `job_id` immediately; the caller polls `/compose-status/:jobId` until the
job reports done or failed. This removes render time from the timeout
equation entirely, regardless of how heavy future features get.

## Repo layout

```
n8n/workflow.json          - the full n8n workflow (import into n8n)
shorts-compose/            - the video composition service
  compose.js                 - main ffmpeg orchestration logic (async job API)
  Dockerfile
  package.json
  motion-assets/             - real licensed assets used by template scenes
    fonts/                     Inter (SIL Open Font License)
    icons/                     useAnimations icon set (CC-BY 4.0 - see LICENSES.md)
    backgrounds/               generated gradient/card backgrounds
    elements/                  generated growing-bar animation
    sfx/                       synthesized whoosh/impact/riser sound effects
                                (generated via ffmpeg's own audio synthesis -
                                no third-party licensing involved)
```

## Setup

### 1. Credentials (configure directly in n8n, not in this repo)

- Anthropic (Claude) API key
- ElevenLabs API key + voice ID
- Pexels API key
- YouTube Data API v3 (OAuth2 for upload)

### 2. Deploy the stack

```
docker compose up -d --build
```

### 3. Import the workflow

Import `n8n/workflow.json` into your n8n instance, then reconnect each
credential (n8n stores credentials separately from the workflow file by
design — none are included here).

### 4. Confirm the compose service

```
docker logs -f shorts-compose
```

## Content pipeline, briefly

1. **Topic generation** — genuinely open-ended, not restricted to a fixed
   niche list or category taxonomy (an earlier 7-niche system was
   deliberately torn out after repeated real-world testing showed any
   labeled category list - even framed as "inspiration" - functions as a
   restriction). Hard exclusion on medical/health content. An explicit
   anti-clustering rule checks the *shape* of recently-used topics (not
   just the subject) so the model doesn't silently converge on one
   structural pattern (e.g. "what if everyone did X at once") across
   consecutive runs. Topic history is capped at 90 entries (raised from an
   original 30, which was aging out real hits within about 6 days at this
   posting volume).
2. **Stage 1 (draft, Claude Opus) + Stage 2 (editorial, Claude Sonnet)** —
   two-pass script generation. Hooks are dramatic and direct-address, with
   an explicit "reject trivia that's only interesting after the
   explanation" filter at topic-selection time. Length target is 70-90
   words (~20-25s) - tightened from an original 110-130 word target based
   on this channel's own real retention data (best performers held
   59-65%, worst held 30-32% and skewed longer). Scripts end with a
   specific, non-generic spoken call-to-action tied to the exact fact,
   not a bolted-on "comment below."
3. **Validation** — a non-throwing check that triggers automatic retry with
   a fresh topic on failure (bad JSON, banned content, medical topics,
   word-count overage, scene/beat mismatches), rather than either crashing
   or posting a broken video.
4. **Visual assembly** — Claude picks per-scene between a real Pexels video
   clip or a motion-graphics template, based on whether the beat is a
   concrete, filmable thing or a number/comparison/punchy line. Stock
   scenes source genuine video footage (not panned still images) via the
   Pexels Video API, scaled/cropped to fill the frame, with the original
   clip audio always discarded in favor of the ElevenLabs narration.
5. **Compose** — ffmpeg assembles scenes with mood-based color grading,
   vignette, and SFX synced to real scene-cut and template-reveal
   timestamps (not just mixed in globally). Burns in karaoke-style
   captions with per-word highlighting, mixes ducked background music,
   and disclosure-tags the upload. Runs as an async job (see above) rather
   than blocking a single HTTP request for the whole render.

## Licensing notes for bundled assets

See `LICENSES.md`. In short: Inter is SIL Open Font License (no attribution
required). The icon set is CC-BY 4.0 (**attribution to useanimations.com is
required** somewhere in your channel/description if you use these assets
commercially — this has not yet been added and is a known open item). The
SFX files are synthesized programmatically (ffmpeg audio filters), not
sourced from any third party - no attribution needed.

## Known limitations / open items

- Icon coverage doesn't yet cover every possible topic angle (no
  lawsuit/gavel or history/map icons yet — only alert/warning, trend
  arrows, lock, activity, archive, star).
- `stat_reveal` template always defaults to the "activity" icon; the
  schema doesn't yet let Claude pick a specific icon per scene.
- CC-BY attribution for the icon set is not yet added anywhere in the
  channel - a real, open compliance item.
- Custom AI-generated thumbnails were built (Claude + fal.ai) and then
  deliberately removed entirely - YouTube currently falls back to its own
  auto-selected frame. The generation code no longer exists in this repo;
  if revisited, it would need to be rebuilt, not just re-enabled.
- A parallel, non-n8n orchestrator (plain Node.js, no workflow engine) was
  also built as a separate experiment and lives in a different repo/
  project - not part of this one.
