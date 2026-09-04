# Third-Party Asset Licenses

This repo bundles a small number of real, licensed design assets used by the
`shorts-compose` motion-graphics templates. They are not original work by
this project and retain their original licenses.

## Fonts — Inter

- Source: https://github.com/rsms/inter
- License: SIL Open Font License 1.1
- No attribution required for use. Free for any purpose, including
  commercial use and modification.

## Icons — useAnimations

- Source: https://github.com/useAnimations/react-useanimations
- License: Creative Commons Attribution 4.0 (CC-BY 4.0)
- Commercial use is permitted with attribution.
- The production artifact builder now appends
  `Motion icon assets: useanimations.com (CC BY 4.0)` to every YouTube
  description under `Sources / credits`, alongside per-scene source credits.
  The same attribution-bearing description is reused by the post-upload
  disclosure/update step so it cannot be accidentally overwritten later.
- Only the raw animation data (JSON) was used, recolored programmatically;
  no modification of the original artwork's design.

## Retrieved real-media assets

The resolver carries each selected asset's `_attribution` metadata through the
scene merge. The V5 production workflow deduplicates those credits and appends
them to the YouTube description automatically. Sources that require attribution
(e.g. eligible Wikimedia/Openverse content) therefore retain their supplied
credit line in the published metadata instead of relying on a manual step.

## Generated assets (no external license)

- `backgrounds/gradient_charcoal.png`, `backgrounds/card_left.png`,
  `backgrounds/card_right.png` — generated programmatically for this
  project (ffmpeg gradient + PIL rounded-rectangle generation).
- `elements/growing_bar_gold.mov` — generated programmatically (Python/PIL
  frame sequence, no external source).
