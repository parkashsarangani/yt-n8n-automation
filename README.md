# YouTube Shorts Facts Automation Pipeline

A fully automated pipeline that generates, voices, composes, and uploads YouTube
Shorts — posting 5x/day with zero manual intervention. Studio-grade output
quality via a hybrid Remotion + FFmpeg rendering architecture.

## Architecture

```
n8n (workflow orchestration)
  │
  ├─ Claude API — open-ended topic selection, script writing (2-stage), editorial review
  ├─ ElevenLabs — text-to-speech with word-level timestamps
  ├─ Pexels API — stock VIDEO clips and PHOTOS for scenes that need real footage
  ├─ shorts-compose (this repo) — hybrid video assembly, async job-polling
  │    ├─ Remotion (React) — studio motion graphics (stat reveals, comparisons,
  │    │    kinetic text) with spring animations, easing curves, and proper
  │    │    typography; also handles caption overlay with per-word highlighting
  │    ├─ FFmpeg — stock video processing (scale/crop/grade), eased Ken Burns
  │    │    on images, audio normalization, music ducking, SFX mixing,
  │    │    crossfade transitions, and final encoding (CRF 16, BT.709)
  │    ├─ Split-tone color science per mood (warm highlights + cool shadows,
  │    │    shadow lift, highlight rolloff, cinematic vignette)
  │    ├─ Scene transitions: 0.4s crossfades between all scenes via xfade
  │    ├─ Sound design: whoosh + sub-bass on every cut, impact + riser on
  │    │    template reveals, gently-ducked background music (ratio 4, shaped)
  │    └─ Final: fade-in/out, BT.709 colorspace, high profile 4.1, faststart
  └─ YouTube Data API — upload, AI-content disclosure
```

All of this is self-hosted on a local Ubuntu server, exposed via a Cloudflare
Tunnel, with `n8n` and `shorts-compose` running as Docker Compose services.

### Why the hybrid Remotion + FFmpeg approach

FFmpeg is unbeatable for raw video processing (scaling, cropping, encoding,
audio mixing), but its filter-graph-based compositing has severe limits for
motion graphics: no easing curves, no spring physics, no proper typography
control, and ASS subtitles look noticeably worse than CSS-rendered text.

Remotion renders React components to video frames via headless Chromium —
giving full CSS animations, spring physics, SVG, and web fonts. The tradeoff
is render time (~2-4 min for a 20s video at 30fps), but the async job-polling
pattern already handles this.

The split:
- **Remotion**: template scenes (stat_reveal, comparison, kinetic_text) +
  caption overlay with karaoke highlighting
- **FFmpeg**: stock video scenes, image Ken Burns, audio mixing, crossfade
  transitions, final encoding

### Why async job-polling (unchanged from v1)

Render time exceeds Cloudflare's 120s proxy timeout. `/compose` returns a
`job_id` immediately; the caller polls `/compose-status/:jobId` until done.

## Repo layout

```
n8n/workflow.json              - the full n8n workflow (import into n8n)
shorts-compose/                - the video composition service
  compose.js                     - main orchestration (async job API, hybrid pipeline)
  Dockerfile
  package.json
  remotion/                      - Remotion project (studio motion graphics)
    src/
      index.ts                     - Remotion entry point
      Root.tsx                     - composition registry
      compositions/
        StatReveal.tsx               - animated stat/number reveal
        Comparison.tsx               - side-by-side comparison cards
        KineticText.tsx              - word-by-word kinetic typography
        CaptionOverlay.tsx           - per-word karaoke captions
        SceneTransition.tsx          - transition overlays
      lib/
        easing.ts                    - spring, expo, back-out, cinematic easing
        colors.ts                    - mood-based color schemes (split-tone)
    render-bridge.mjs              - Node.js bridge (called from compose.js)
    package.json
    tsconfig.json
  motion-assets/                 - real licensed assets
    fonts/                         Inter (SIL Open Font License)
    icons/                         useAnimations icon set (CC-BY 4.0)
    backgrounds/                   generated gradient/card backgrounds
    elements/                      generated growing-bar animation
    sfx/                           synthesized whoosh/impact/riser SFX
docker-compose.yml             - deploys n8n + shorts-compose
```

## Setup

### 1. Credentials (configure directly in n8n, not in this repo)

- Anthropic (Claude) API key
- ElevenLabs API key + voice ID
- Pexels API key
- YouTube Data API v3 (OAuth2 for upload)

### 2. Deploy the stack

```bash
docker compose up -d --build
```

The first build takes longer (installs Chromium + Remotion dependencies inside
the container). Subsequent rebuilds use Docker layer caching.

### 3. Import the workflow

Import `n8n/workflow.json` into your n8n instance, then reconnect each
credential (n8n stores credentials separately from the workflow file by
design — none are included here).

### 4. Confirm the compose service

```bash
docker logs -f shorts-compose
```

### 5. (Optional) Preview Remotion compositions locally

```bash
cd shorts-compose/remotion
npm install
npx remotion studio
```

This opens the Remotion Studio where you can preview and tweak template
animations before deploying.

## Content pipeline, briefly

1. **Topic generation** — genuinely open-ended, not restricted to a fixed
   niche list. Hard exclusion on medical/health content. Anti-clustering
   checks topic *shape*, not just subject. History capped at 90 entries.
2. **Stage 1 (draft, Claude Opus) + Stage 2 (editorial, Claude Sonnet)** —
   two-pass script generation. Length target 70-90 words (~20-25s). Scripts
   end with a specific, non-generic spoken CTA tied to the exact fact.
3. **Validation** — non-throwing check that triggers automatic retry with a
   fresh topic on failure.
4. **Visual assembly** — Claude picks per-scene between a real Pexels video
   clip or a Remotion motion-graphics template, based on whether the beat
   is filmable or a number/comparison/punchy line.
5. **Compose** — hybrid Remotion + FFmpeg pipeline assembles scenes with
   studio color grading, crossfade transitions, synced SFX, per-word
   karaoke captions, ducked music, and BT.709-flagged final encoding.

## Studio quality improvements (v2)

| Area | Before (v1) | After (v2) |
|------|-------------|------------|
| Transitions | Hard cuts only | 0.4s crossfades (xfade) + fade in/out |
| Color grade | Basic EQ + saturation | Split-tone (warm highlights, cool shadows), shadow lift, highlight rolloff, cinematic curves |
| Motion | Linear zoompan | Sinusoidal eased Ken Burns, punch-in at cuts |
| Templates | ASS subtitle overlays on static bg | Full Remotion React animations with spring physics, staggered reveals |
| Captions | ASS hard-burn with outline | Remotion-rendered with scale punch, soft shadow, fixed baseline |
| Audio mix | Aggressive sidechain (ratio 10) | Gentle duck (ratio 4, shaped), sub-bass on every cut |
| Encoding | CRF 18, no colorspace flags | CRF 16, BT.709, high profile 4.1, faststart |
| Typography | System fontconfig rendering | CSS/Web font rendering via Remotion (letter-spacing, shadows) |

## Licensing notes for bundled assets

See `LICENSES.md`. In short: Inter is SIL Open Font License (no attribution
required). The icon set is CC-BY 4.0 (**attribution to useanimations.com is
required** — this has not yet been added and is a known open item). The SFX
files are synthesized programmatically, no third-party licensing.

## Known limitations / open items

- Icon coverage doesn't yet cover every possible topic angle.
- `stat_reveal` template defaults to a generic icon; the schema doesn't yet
  let Claude pick a specific icon per scene.
- CC-BY attribution for the icon set is not yet added to the channel.
- Remotion rendering adds ~2-4 min to total compose time (acceptable given
  the async job pattern, but limits real-time preview).
- Remotion requires ~4-6GB RAM during rendering (Chromium + frame buffer).
  The docker-compose sets a 6GB memory limit accordingly.
- Custom thumbnails were removed entirely — YouTube falls back to auto-frame.
