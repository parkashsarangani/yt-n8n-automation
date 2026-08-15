# Signature music (channel identity)

Drop a single track here named **`signature.mp3`**. Whenever it exists,
`pickMusicTrack()` uses it as the background bed on **every** video — a
consistent sonic identity people recognise and return to. Without it, videos
render with no music (or per-mood `<mood>.mp3` if you add those).

It gets baked into the image by the Dockerfile's `COPY`, so committing the file
here is enough — no volume needed.

## Where to get a copyright-safe track

**Safest for a monetised channel — YouTube Audio Library** (it's in your Studio
left nav → *Audio library*). Filter **Attribution → "Not required"**, pick an
instrumental ~30–60s track that fits "curiosity / discovery", download, rename to
`signature.mp3`, drop it here. YouTube guarantees these are clear of Content ID
claims — nothing else does.

**Also fine — Pixabay Music** (`pixabay.com/music`): free for commercial use, no
attribution. Slightly higher (but small) risk of a spurious Content ID claim
than the Audio Library.

Avoid random "free music" sites — most are actually **CC-BY** (attribution
required) or unclear, which risks claims/strikes on a monetised channel.
