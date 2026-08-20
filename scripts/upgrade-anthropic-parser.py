#!/usr/bin/env python3
"""Harden Anthropic response parsing and deterministic visual-schema repair.

Anthropic adaptive-thinking responses may place thinking/signature blocks before
text. The production workflow still had parsers that assumed content[0].text,
which fails even when a valid text block is present later in the response.

The Visual Director can also omit or contradict non-creative schema metadata
(first_frame_type, engagement_mode, search_queries). Those omissions should not
burn the whole script/topic retry budget. Repair only deterministic metadata
before the existing fail-closed quality and asset gates run.

The final transform also aligns commissioning/writer/editor/visual prompts to
the deterministic quality and b-roll gates.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from upgrade_quality_alignment import assert_alignment, upgrade as upgrade_quality_alignment

MARKER = "ANTHROPIC_TEXT_BLOCK_GUARD"
VISUAL_SCHEMA_MARKER = "VISUAL_SCHEMA_NORMALIZER"


def node_by_name(workflow: dict, name: str) -> dict:
    for node in workflow.get("nodes", []):
        if node.get("name") == name:
            return node
    raise KeyError(f"required n8n node not found: {name}")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        return text
    if old not in text:
        raise ValueError(f"could not patch {label}: anchor not found")
    return text.replace(old, new, 1)


def robust_text_extract(label: str) -> str:
    return f"""// {MARKER}: Anthropic may emit thinking/signature blocks before text.\nconst contentBlocks = Array.isArray(response.content) ? response.content : [];\nconst textBlocks = contentBlocks.filter(b => b && b.type === 'text' && typeof b.text === 'string');\nlet raw = textBlocks.map(b => b.text).join('\\n').trim();\nif (!raw) {{\n  const blockTypes = contentBlocks.map(b => b?.type || 'unknown').join(', ') || 'none';\n  if (response.stop_reason === 'max_tokens') {{\n    throw new Error('{label} hit max_tokens before producing a text block (content types: ' + blockTypes + ')');\n  }}\n  throw new Error('{label} returned no text block (stop_reason: ' + (response.stop_reason || 'unknown') + ', content types: ' + blockTypes + ')');\n}}"""


def patch_draft_parser(workflow: dict) -> None:
    node = node_by_name(workflow, "Parse Draft JSON")
    code = node["parameters"]["jsCode"]
    old = """let raw = response.content?.[0]?.text;\nif (!raw) throw new Error('Claude draft response missing content[0].text');"""
    node["parameters"]["jsCode"] = replace_once(
        code,
        old,
        robust_text_extract("Claude draft response"),
        "draft Anthropic text parser",
    )


def patch_editor_parser(workflow: dict) -> None:
    node = node_by_name(workflow, "Parse Editorial For Visual Director")
    code = node["parameters"]["jsCode"]
    old = "let raw=String(response.content?.[0]?.text||'').trim().replace(/^```(?:json)?\\s*/i,'').replace(/```\\s*$/,'');"
    new = (
        f"/* {MARKER}: select text blocks instead of assuming content[0] is text. */"
        "const contentBlocks=Array.isArray(response.content)?response.content:[];"
        "const textBlocks=contentBlocks.filter(b=>b&&b.type==='text'&&typeof b.text==='string');"
        "let raw=String(textBlocks.map(b=>b.text).join('\\n')||'').trim().replace(/^```(?:json)?\\s*/i,'').replace(/```\\s*$/,'');"
        "if(!raw){const blockTypes=contentBlocks.map(b=>b?.type||'unknown').join(', ')||'none';"
        "if(response.stop_reason==='max_tokens')throw new Error('Editorial API hit max_tokens before producing a text block (content types: '+blockTypes+')');"
        "throw new Error('Editorial API returned no text block (stop_reason: '+(response.stop_reason||'unknown')+', content types: '+blockTypes+')');}"
    )
    node["parameters"]["jsCode"] = replace_once(
        code,
        old,
        new,
        "editor Anthropic text parser",
    )


def patch_final_parser(workflow: dict) -> None:
    node = node_by_name(workflow, "Validate Final Script")
    code = node["parameters"]["jsCode"]
    old = """let raw = response.content?.[0]?.text;\nif (!raw) throw new Error('Claude editor response missing content[0].text');"""
    node["parameters"]["jsCode"] = replace_once(
        code,
        old,
        robust_text_extract("Claude visual-director response"),
        "final Anthropic text parser",
    )


def patch_visual_schema_normalizer(workflow: dict) -> None:
    node = node_by_name(workflow, "Validate Final Script")
    code = node["parameters"]["jsCode"]
    if VISUAL_SCHEMA_MARKER in code:
        return

    # This must run immediately after the Visual Director JSON has parsed and
    # before *any* schema checks. A previous version inserted it beside the
    # later creative-system gate, after the legacy scene validator had already
    # rejected missing stock_search_query values.
    anchor = "const errors = [];"
    normalizer = f"""// {VISUAL_SCHEMA_MARKER}: repair deterministic Visual Director omissions before fail-closed validation.\n// This only normalizes metadata/search hints; it does not change narration, facts, quality scores, or asset thresholds.\nconst normalizeSearchQuery=(value,maxWords=5)=>String(value||'').replace(/[^a-zA-Z0-9' -]+/g,' ').replace(/\\s+/g,' ').trim().split(' ').filter(Boolean).slice(0,maxWords).join(' ');\nconst dedupeSearchQueries=(values)=>{{const out=[];const seen=new Set();for(const value of values){{const q=normalizeSearchQuery(value);const key=q.toLowerCase();if(q&&!seen.has(key)){{seen.add(key);out.push(q);}}}}return out;}};\nif(!parsed.first_frame_type){{const byFormat={{documentary_cinematic:'hero_motion',comparison_reveal:'scale_comparison',minimal_proof:'result_first',archival_history:'archive_proof',macro_detail:'macro_anomaly',kinetic_data:'kinetic_stat'}};parsed.first_frame_type=byFormat[parsed.creative_format]||'result_first';}}\nconst hasComment=Boolean(String(parsed.comment_hook||'').trim());\nconst hasShareOutro=Boolean(String(parsed.outro_line||'').trim());\nparsed.engagement_mode=hasComment&&hasShareOutro?'comment_and_share':hasComment?'comment_only':hasShareOutro?'share_only':'none';\nif(Array.isArray(parsed.scenes)){{parsed.scenes.forEach((s,i)=>{{if(!s||s?.template_data?.is_outro||s.visual_source==='template')return;let queries=dedupeSearchQueries([...(Array.isArray(s.search_queries)?s.search_queries:[]),s.stock_search_query,s.visual_prompt,s.named_subject,s.point]);const base=queries[0]||normalizeSearchQuery(s.visual_prompt||s.named_subject||s.point||parsed.title||'visual subject',4);if(queries.length<2&&base){{const suffix=i===0?'close up':s.visual_role==='comparison'?'comparison':'detail';queries=dedupeSearchQueries([...queries,`${{base}} ${{suffix}}`,`${{base}} footage`]);}}s.search_queries=queries.slice(0,4);if(!String(s.stock_search_query||'').trim()&&s.search_queries[0])s.stock_search_query=s.search_queries[0];}});}}\n\n"""
    if anchor not in code:
        raise ValueError("could not patch visual schema normalizer: pre-validation anchor not found")
    node["parameters"]["jsCode"] = code.replace(anchor, normalizer + anchor, 1)


def upgrade(workflow: dict) -> dict:
    patch_draft_parser(workflow)
    patch_editor_parser(workflow)
    patch_final_parser(workflow)
    patch_visual_schema_normalizer(workflow)
    upgrade_quality_alignment(workflow)
    return workflow


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit("usage: upgrade-anthropic-parser.py INPUT_WORKFLOW OUTPUT_WORKFLOW")
    src, dst = map(Path, sys.argv[1:])
    workflow = json.loads(src.read_text())
    upgraded = upgrade(workflow)
    validate_code = node_by_name(upgraded, "Validate Final Script")["parameters"]["jsCode"]
    if VISUAL_SCHEMA_MARKER not in validate_code:
        raise RuntimeError("visual schema normalizer did not land in Validate Final Script")

    # Regression guard for the production failure that followed PR #73: the
    # normalizer must execute before both the errors array is created and the
    # legacy stock_search_query validation branch runs.
    marker_pos = validate_code.index(VISUAL_SCHEMA_MARKER)
    errors_pos = validate_code.index("const errors = [];")
    stock_check_pos = validate_code.index("missing stock_search_query")
    if not marker_pos < errors_pos < stock_check_pos:
        raise RuntimeError(
            "visual schema normalizer ordering is unsafe: it must precede all validation checks"
        )

    assert_alignment(upgraded)

    dst.write_text(json.dumps(upgraded, indent=2) + "\n")
    print(f"Anthropic parser workflow written to {dst}")


if __name__ == "__main__":
    main()
