# YouTube Shorts Facts Automation Pipeline

A fully automated pipeline that generates, voices, composes, and uploads YouTube
Shorts across 7 content niches (billion-dollar frauds, failed ventures, landmark
lawsuits, economic bubbles, historical disasters, scale/data stories, and
ancient history) — running 4x/day with zero manual intervention.

## Architecture

```
n8n (workflow orchestration)
  │
  ├─ Claude API — topic generation, script writing (2-stage), editorial review
  ├─ ElevenLabs — text-to-speech with word-level timestamps
  ├─ Pexels API — stock photography for scenes that need a real photo
  ├─ shorts-compose (this repo) — ffmpeg-based video assembly
  │    ├─ Stock scenes: multi-image pan/Ken-Burns cuts every ~5s
  │    ├─ Template scenes: motion-graphics (stat reveals, comparisons,
  │    │  kinetic text) built from real licensed assets - no browser/
  │    │  Puppeteer dependency, pure ffmpeg + pre-rendered clips
  │    └─ ASS-based animated captions + comment-hook overlay
  └─ YouTube Data API — upload, AI-content disclosure
```

All of this is self-hosted on a local Ubuntu server, exposed via a Cloudflare
Tunnel, with `n8n` and `shorts-compose` running as Docker Compose services.

## Repo layout

```
n8n/workflow.json          - the full n8n workflow (import into n8n)
shorts-compose/            - the video composition service
  compose.js                 - main ffmpeg orchestration logic
  Dockerfile
  package.json
  motion-assets/             - real licensed fonts/icons used by template scenes
    fonts/                     Inter (SIL Open Font License)
    icons/                     useAnimations icon set (CC-BY 4.0 - see LICENSES.md)
    backgrounds/               generated gradient/card backgrounds
    elements/                  generated growing-bar animation
docker-compose.yml          - the full local server stack (n8n + shorts-compose)
```

## Setup

### 1. Credentials (configure directly in n8n, not in this repo)
- Anthropic (Claude) API key
- ElevenLabs API key + voice ID
- Pexels API key
- YouTube Data API v3 (OAuth2 for upload, or a plain API key for the trending-search node)

### 2. Deploy the stack
```bash
docker compose up -d --build
```

### 3. Import the workflow
Import `n8n/workflow.json` into your n8n instance, then reconnect each
credential (n8n stores credentials separately from the workflow file by
design — none are included here).

### 4. Confirm the compose service
```bash
docker logs -f shorts-compose
curl http://localhost:4000/health   # if you've added a health route
```

## Content pipeline, briefly

1. **Topic generation** — rotates across 7 niches, with a real-randomness
   history-forcing mechanism (not left to the LLM's own "randomness," which
   is unreliable) and a hard exclusion on medical/health content.
2. **Stage 1 (draft) + Stage 2 (editorial)** — two-pass script generation
   with dramatic, direct-address hook style, factual-integrity rules
   (comparative scale over invented precision), and a length target tuned
   to the ~33-40s sweet spot for Shorts retention.
3. **Validation** — a non-throwing check that triggers automatic retry with
   a fresh topic on failure (bad JSON, banned content, medical topics,
   scene/beat mismatches), rather than either crashing or posting a broken
   video.
4. **Visual assembly** — Claude picks per-scene between a real stock photo
   (Pexels) or a motion-graphics template, based on whether the beat is a
   concrete photographable thing or a number/comparison/punchy line.
5. **Compose** — ffmpeg assembles scenes, normalizes frame rate (a real bug
   fixed this session — mixed fps between Pexels and template scenes
   silently stretched the video track), burns in animated captions, mixes
   music, and disclosure-tags the upload.

## Licensing notes for bundled assets

See `LICENSES.md`. In short: Inter is SIL Open Font License (no attribution
required). The icon set is CC-BY 4.0 (**attribution to useanimations.com is
required** somewhere in your channel/description if you use these assets
commercially — this has not yet been added and is a known open item).

## Known limitations / open items

- Icon coverage doesn't yet include all 7 niches (no lawsuit/gavel or
  history/map icons yet — only alert/warning, trend arrows, lock, activity,
  archive, star).
- `stat_reveal` template always defaults to the "activity" icon; the
  schema doesn't yet let Claude pick a specific icon per scene.
- `package.json` dependency versions were reconstructed from `compose.js`'s
  actual `require()` calls, not copied from a verified lockfile — worth
  diffing against your real working `node_modules` before trusting blindly.
- CC-BY attribution for the icon set is not yet added anywhere in the
  channel.
