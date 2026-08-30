#!/usr/bin/env python3
"""Patch compose.js for VISUAL_MATCHING_V4 passthrough, proof renderers and final QA."""
from __future__ import annotations
import sys
from pathlib import Path

MARKER = "VISUAL_MATCHING_V4_COMPOSE"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        return text
    if old not in text:
        raise ValueError(f"{label} anchor missing")
    return text.replace(old, new, 1)


def upgrade(text: str) -> str:
    if MARKER in text:
        return text
    import_anchor = 'const { resolveBroll } = require("./brollResolver");'
    text = replace_once(text, import_anchor, import_anchor + '\nconst { reviewFinalVideo } = require("./finalVisualQa");', "final QA import")

    # The older transforms enumerate resolver fields. V4 intentionally passes
    # the complete typed request so new contract fields cannot be silently lost.
    start = text.find('app.post("/resolve-broll", async (req, res) => {')
    if start < 0:
        raise ValueError("resolve-broll endpoint missing")
    end = text.find('\n});', start)
    if end < 0:
        raise ValueError("resolve-broll endpoint end missing")
    end += len('\n});')
    endpoint = '''app.post("/resolve-broll", async (req, res) => {
  try {
    const result = await resolveBroll(req.body || {});
    res.json(result);
  } catch (e) {
    res.json({ ok: false, reason: "error", error: String((e && e.message) || e) });
  }
});'''
    text = text[:start] + endpoint + text[end:]

    # The creative-system transform owns preflight, but V4 adds first-class
    # proof templates after that transform runs. Expand the same fail-fast set.
    text = replace_once(
        text,
        '    const allowedTemplates = new Set(["kinetic_text", "stat_reveal", "comparison"]);',
        '    const allowedTemplates = new Set(["kinetic_text", "stat_reveal", "comparison", "map", "timeline", "diagram", "annotated_real"]);',
        "V4 template preflight",
    )

    # V4 structured proof renderers. Map/timeline/diagram are now deterministic
    # Remotion compositions, and annotated_real renders the exact verified image
    # with VLM-grounded callout coordinates.
    old_map = '''  const compositionMap = {
    stat_reveal: "StatReveal",
    comparison: "Comparison",
    kinetic_text: "KineticText",
  };'''
    new_map = '''  const compositionMap = {
    stat_reveal: "StatReveal",
    comparison: "Comparison",
    kinetic_text: "KineticText",
    map: "MapVisual",
    timeline: "TimelineVisual",
    diagram: "DiagramVisual",
    annotated_real: "AnnotatedReal",
  };'''
    text = replace_once(text, old_map, new_map, "structured composition map")

    old_props = '''  } else if (templateName === "kinetic_text") {
    props.line = templateData?.line || "";
  }
'''
    new_props = '''  } else if (templateName === "kinetic_text") {
    props.line = templateData?.line || "";
  } else if (templateName === "map") {
    props.title = templateData?.title || "Where it happens";
    props.locations = Array.isArray(templateData?.locations) ? templateData.locations : [];
    props.connections = Array.isArray(templateData?.connections) ? templateData.connections : [];
  } else if (templateName === "timeline") {
    props.title = templateData?.title || "How it unfolded";
    props.events = Array.isArray(templateData?.events) ? templateData.events : [];
  } else if (templateName === "diagram") {
    props.title = templateData?.title || "How it connects";
    props.nodes = Array.isArray(templateData?.nodes) ? templateData.nodes : [];
    props.edges = Array.isArray(templateData?.edges) ? templateData.edges : [];
  } else if (templateName === "annotated_real") {
    props.imageUrl = templateData?.imageUrl || "";
    props.imageWidth = Number(templateData?.imageWidth || 1080);
    props.imageHeight = Number(templateData?.imageHeight || 1920);
    props.title = templateData?.title || "";
    props.annotations = Array.isArray(templateData?.annotations) ? templateData.annotations : [];
  }
'''
    text = replace_once(text, old_props, new_props, "structured template props")

    old = '''    finalCmd.output(finalPath);
    await run(finalCmd);

    await fsp.copyFile(finalPath, outputFullPath);
    console.log(`[job ${jobId}] Done -> ${outputFullPath}`);
    return { success: true, output_path: outputFullPath, job_id: jobId };'''
    new = '''    finalCmd.output(finalPath);
    await run(finalCmd);

    // VISUAL_MATCHING_V4_COMPOSE: final rendered-pixel QA. This happens after
    // captions/branding/mix are applied and before the artifact is exposed for
    // upload, so retrieval correctness cannot be undone by crop/composition.
    const finalVisualQa = await reviewFinalVideo(finalPath, scenes, durations);
    if (!finalVisualQa.passed) {
      const summary = (finalVisualQa.issues || []).map((x) => `scene ${x.scene_index}: ${x.problem} (semantic=${x.semantic_match ?? 'n/a'}, score=${x.score ?? 'n/a'})`).join('; ');
      throw new Error(`Final visual QA rejected rendered Short: ${summary || 'unknown visual mismatch'}`);
    }

    await fsp.copyFile(finalPath, outputFullPath);
    console.log(`[job ${jobId}] Done -> ${outputFullPath}`);
    return { success: true, output_path: outputFullPath, job_id: jobId, final_visual_qa: finalVisualQa };'''
    text = replace_once(text, old, new, "final render QA")
    return text + f"\n// {MARKER}\n"


def main() -> None:
    if len(sys.argv) not in (2, 3):
        raise SystemExit("usage: visual_matching_v4_compose.py INPUT [OUTPUT]")
    src = Path(sys.argv[1]); dst = Path(sys.argv[2]) if len(sys.argv) == 3 else src
    dst.write_text(upgrade(src.read_text()))
    print(f"{MARKER} compose written to {dst}")


if __name__ == "__main__":
    main()
