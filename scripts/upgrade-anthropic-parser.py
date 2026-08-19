#!/usr/bin/env python3
"""Harden Anthropic response parsing after the topic-latency workflow upgrade.

Anthropic adaptive-thinking responses may place thinking/signature blocks before
text. The production workflow still had parsers that assumed content[0].text,
which fails even when a valid text block is present later in the response.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

MARKER = "ANTHROPIC_TEXT_BLOCK_GUARD"


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


def upgrade(workflow: dict) -> dict:
    patch_draft_parser(workflow)
    patch_editor_parser(workflow)
    patch_final_parser(workflow)
    return workflow


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit("usage: upgrade-anthropic-parser.py INPUT_WORKFLOW OUTPUT_WORKFLOW")
    src, dst = map(Path, sys.argv[1:])
    workflow = json.loads(src.read_text())
    dst.write_text(json.dumps(upgrade(workflow), indent=2) + "\n")
    print(f"Anthropic parser workflow written to {dst}")


if __name__ == "__main__":
    main()
