# YouTube Shorts Facts Automation Pipeline

A fully automated pipeline that generates, voices, composes, and uploads
YouTube Shorts — posting **3×/day** with zero manual intervention. Each video is
a punchy **20–30s single-fact Short**: one surprising, counterintuitive fact
about an instantly recognizable subject, with cinematic visuals, per-word
captions, and a spoken engagement beat.

## Architecture

```
n8n (workflow orchestration, Europe/Berlin, 3× daily: 14:00 / 19:00 / 22:00)
  │
  ├─ Claude API — topic selection (single curiosity facts), 2-stage script
  │    (draft → editorial rewrite), validation with auto-retry
  ├─ ElevenLabs — text-to-speech with word-level timestamps (per scene)
  ├─ Pexels API — stock VIDEO clips and PHOTOS for scenes that need real footage
  │    └─ Video search first, automatic photo fallback if no video found
  ├─ shorts-compose (this repo) — hybrid video assembly, async job-polling
  │    ├─ Remotion (React) — studio motion-graphics templates (stat reveals,
  │    │    comparisons, kinetic text) with spring physics and web typography
  │    ├─ FFmpeg — stock video processing (scale/crop/grade), eased Ken Burns
  │    │    on photos, audio normalization, music ducking, SFX mixing,
  │    │    crossfade transitions, and final encoding (CRF 16, BT.709)
  │    ├─ Split-tone color science per mood (warm highlights + cool shadows,
  │    │    shadow lift, highlight rolloff, cinematic vignette)
  │    ├─ Scene transitions: 0.4s crossfades between all scenes via xfade
  │    ├─ Sound design: whoosh + sub-bass on every cut, impact + riser on
  │    │    template reveals, gently-ducked background music (ratio 4, shaped)
  │    ├─ Per-word "karaoke" captions burned via ASS, with active-word pop
  │    └─ Final: fade-in/out, BT.709 colorspace, high profile 4.1, faststart
  └─ YouTube Data API — upload, AI-content disclosure
```

All of this is self-hosted on a local Ubuntu server, exposed via a Cloudflare
Tunnel, with `n8n` and `shorts-compose` running as Docker Compose services.
Deploys are automated: a push to `main` triggers a self-hosted GitHub Actions
runner that rebuilds `shorts-compose` and PUTs the workflow to the n8n API.

### Why the hybrid Remotion + FFmpeg approach

FFmpeg is unbeatable for raw video processing (scaling, cropping, encoding,
audio mixing, Ken Burns on stills), but its filter-graph compositing has severe
limits for motion graphics: no easing curves, no spring physics, no proper
typography control.

Remotion renders React components to video frames via headless Chromium —
giving full CSS animations, spring physics, SVG, and web fonts. The tradeoff is
render time, but the async job-polling pattern already handles it.

The split:
- **Remotion**: template scenes (stat_reveal, comparison, kinetic_text),
  including the branded outro card
- **FFmpeg**: stock video/image scenes, color grade, audio mixing, captions,
  concatenation, and final encoding

### Why async job-polling

Render time exceeds Cloudflare's 120s proxy timeout. `/compose` returns a
`job_id` immediately; the caller polls `/compose-status/:jobId` until done.

## Repo layout

```
n8n/workflow.json              - the full n8n workflow (import into n8n)
shorts-compose/                - the video composition service
  compose.js                     - main orchestration (async job API, pipeline)
  Dockerfile
  package.json
  remotion/                      - Remotion project (studio motion graphics)
    src/
      index.ts                     - Remotion entry point
      Root.tsx                     - composition registry
      compositions/
        StatReveal.tsx               - animated stat/number reveal
        Comparison.tsx               - side-by-side comparison cards
        KineticText.tsx              - word-by-word kinetic typography (+ outro)
        CaptionOverlay.tsx           - per-word karaoke captions
      lib/
        easing.ts                    - spring, expo, back-out, cinematic easing
        colors.ts                    - mood-based color schemes
    render-bridge.mjs              - Node.js bridge (called from compose.js)
  motion-assets/                 - real licensed assets
    fonts/                         Inter (SIL Open Font License)
    icons/                         useAnimations icon set (CC-BY 4.0)
    sfx/                           synthesized riser/impact/whoosh SFX
  music/                         - (optional) per-mood tracks; none committed,
                                   so videos currently render without music
docker-compose.yml             - deploys n8n + shorts-compose
.github/workflows/deploy.yml   - CI: build + deploy on push to main
```

## Setup

### 1. Credentials (configure directly in n8n, not in this repo)

- Anthropic (Claude) API key
- ElevenLabs API key + voice ID
- Pexels API key (HTTP Header Auth in n8n)
- YouTube Data API v3 (OAuth2 for upload)

n8n stores credentials separately from the workflow file by design — none are
included here. Reconnect each after importing the workflow.

### 2. Environment (shorts-compose)

Set in the server environment / `.env`:

| Var | Default | Purpose |
|-----|---------|---------|
| `TOPIC_HISTORY_PATH` | `/app/data/topic_history.json` | Dedup state (persisted, see below). |
| `OUTPUT_DIR` | `/app/outputs` | Rendered videos (persisted). |

### 3. Deploy the stack

```bash
docker compose up -d --build
```

The first build takes longer (installs Chromium + Remotion dependencies inside
the container). Subsequent rebuilds use Docker layer caching. In production,
pushing to `main` deploys automatically via the GitHub Actions runner.

### 4. Persistence

Topic history and outputs live in **named Docker volumes** (`shorts_data`,
`shorts_outputs`), not bind mounts — so `git clean` on deploy can never wipe
them. Anything you want version-controlled (e.g. music tracks) goes in the repo
and is baked into the image via `COPY`.

### 5. Import the workflow

Import `n8n/workflow.json` into your n8n instance, then reconnect each
credential.

### 6. (Optional) Preview Remotion compositions locally

```bash
cd shorts-compose/remotion
npm install
npx remotion studio
```

## Content pipeline, briefly

1. **Topic generation** — one **surprising, counterintuitive fact** about an
   **instantly recognizable** subject (the human body, space, well-known
   animals, everyday objects, famous places, money, sport, common tech, big
   historical events). Two hard bans: **no biographies/life stories** and **no
   obscure subjects**. Hard exclusion on medical/health content. Anti-clustering
   on both subject and category. History capped at 90 entries.
2. **Stage 1 (draft) + Stage 2 (editorial rewrite)** — two-pass script
   generation. **20–30s, ~60–90 words, 3–4 scenes**, with the fact landing in
   the **first 3 seconds** and each beat carrying BUT/THEREFORE tension (never
   and-then listing).
3. **Titles** lead with **stakes and emotion**, not just the topic, while
   withholding the resolution (no payoff numbers). ≤60 chars, front-loaded.
4. **Engagement** — a one-tap comment question (yes/no or single word) is woven
   into the narration around the two-thirds mark and mirrored on-screen
   (`comment_hook`); the story **ends on its kicker**, then a short **spoken
   outro** asks viewers to share. The outro is a real narrated scene over the
   branded card — voiced by the same TTS, not silent.
5. **Validation** — non-throwing check that triggers automatic retry with a
   fresh topic on failure; injects the spoken outro scene.
6. **Visual assembly** — each scene is either a **Pexels stock video/photo**
   (videos processed directly, photos rendered with eased Ken Burns) or a
   Remotion motion-graphics template, based on whether the beat is depictable
   or a number/comparison.
7. **Compose** — FFmpeg + Remotion assemble the scenes with split-tone color
   grading, crossfade transitions, per-word karaoke captions, gapless
   voiceover, (optional) ducked music, and a BT.709-flagged final encode.

## Editing / quality notes

| Area | Current approach |
|------|------------------|
| Cuts | **Crossfade transitions** (0.4s) between scenes via xfade |
| Color grade | **Split-tone** per mood: warm highlights + cool shadows, shadow lift, highlight rolloff, cinematic vignette |
| Motion | Stock video (direct) or **eased Ken Burns** on photos with sinusoidal motion |
| Source | **Pexels** stock video (preferred) with automatic photo fallback |
| Captions | Per-word ASS burn-in with active-word scale "pop"; gold/green highlight for keywords and numbers |
| Sound design | Whoosh + sub-bass on every cut, impact + riser on template reveals |
| Voice | **Gapless** rejoin of per-scene TTS (single loudnorm, no AAC-priming clicks at scene seams) |
| Music | Gently ducked under the voice when a per-mood track exists (none committed by default) |
| Encoding | CRF 16, high profile, BT.709 primaries/trc/colorspace, faststart, 1080×1920 @ 30fps |

## Posting schedule

3×/day at **14:00 / 19:00 / 22:00 Europe/Berlin** — chosen to hit DE afternoon,
the DE-evening + US-midday overlap, and US afternoon (top audiences: Germany and
USA). Change the cron expressions in the workflow's Schedule Trigger to adjust.

## External paid APIs

Anthropic (Claude), ElevenLabs (TTS), and Pexels (stock media) are the external
APIs. Pexels is free for most use cases. YouTube Data API is free within quota.

## Licensing notes for bundled assets

See `LICENSES.md`. In short: Inter is SIL Open Font License (no attribution
required). The icon set is CC-BY 4.0 (**attribution to useanimations.com is
required** — a known open item). The SFX files are synthesized programmatically,
no third-party licensing.

## Known limitations / open items

- No music tracks are committed, so videos render without a soundtrack until
  per-mood files are added to `shorts-compose/music/`.
- CC-BY attribution for the icon set is not yet added to the channel.
- Remotion rendering adds render time and needs ~4–6GB RAM (Chromium + frame
  buffer); docker-compose sets a 6GB memory limit accordingly.
- Custom thumbnails are not set — YouTube falls back to an auto-frame.
