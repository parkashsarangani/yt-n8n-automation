#!/usr/bin/env python3
"""Final runtime hardening for the transformed b-roll resolver."""
from __future__ import annotations

import sys
from pathlib import Path

MARKER = "PREPROD_BROLL_HARDENING"


def replace_required(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        return text
    if old not in text:
        raise ValueError(f"could not patch {label}: anchor not found")
    return text.replace(old, new, 1)


SAFE_GET_OLD = '''async function safeGet(url, config = {}, timeout = 15000) {
  try {
    const r = await axios.get(url, { timeout, ...config });
    return r.data;
  } catch {
    return null;
  }
}'''

SAFE_GET_NEW = '''// PREPROD_BROLL_HARDENING: one bounded retry for transient/free stock lookups.
async function safeGet(url, config = {}, timeout = 15000) {
  for (let attempt = 0; attempt < 2; attempt++) {
    try {
      const r = await axios.get(url, { timeout, ...config });
      return r.data;
    } catch (err) {
      const status = Number(err?.response?.status || 0);
      const retryable = !status || status === 429 || status >= 500;
      if (!retryable || attempt === 1) return null;
      await new Promise((resolve) => setTimeout(resolve, 350 * (attempt + 1)));
    }
  }
  return null;
}'''

PARSE_SCORE_OLD = '''function parseScoreJson(text) {
  const raw = String(text || "").trim().replace(/^```(?:json)?\\s*/i, "").replace(/```\\s*$/, "");
  const a = raw.indexOf("{");
  const b = raw.lastIndexOf("}");
  if (a >= 0 && b > a) {
    try { return JSON.parse(raw.slice(a, b + 1)); } catch { /* fall through */ }
  }
  const n = raw.match(/\\d{1,3}/);
  const v = n ? Math.max(0, Math.min(100, Number(n[0]))) : 0;
  return {
    relevance: v,
    scroll_stop: v,
    mobile_clarity: v,
    composition: v,
    motion_energy: v,
    uniqueness: v,
    overall: v,
  };
}'''

PARSE_SCORE_NEW = '''// PREPROD_BROLL_HARDENING: choose the last complete score object after self-correction.
function extractScoreObjects(s) {
  const out = [];
  let i = 0;
  while (i < s.length) {
    const start = s.indexOf("{", i);
    if (start < 0) break;
    let depth = 0, inStr = false, esc = false, end = -1;
    for (let j = start; j < s.length; j++) {
      const ch = s[j];
      if (inStr) {
        if (esc) esc = false;
        else if (ch === "\\\\") esc = true;
        else if (ch === '"') inStr = false;
      } else if (ch === '"') inStr = true;
      else if (ch === "{") depth += 1;
      else if (ch === "}") {
        depth -= 1;
        if (depth === 0) { end = j; break; }
      }
    }
    if (end < 0) { i = start + 1; continue; }
    out.push(s.slice(start, end + 1));
    i = end + 1;
  }
  return out;
}

function parseScoreJson(text) {
  const raw = String(text || "").trim().replace(/^```(?:json)?\\s*/i, "").replace(/```\\s*$/, "");
  const blocks = extractScoreObjects(raw);
  for (let i = blocks.length - 1; i >= 0; i--) {
    try {
      const parsed = JSON.parse(blocks[i]);
      if (parsed && typeof parsed === "object" && (
        Number.isFinite(Number(parsed.overall)) ||
        Number.isFinite(Number(parsed.relevance)) ||
        Number.isFinite(Number(parsed.scroll_stop))
      )) return parsed;
    } catch { /* try the previous complete object */ }
  }
  const n = raw.match(/\\d{1,3}/);
  const v = n ? Math.max(0, Math.min(100, Number(n[0]))) : 0;
  return {
    relevance: v,
    scroll_stop: v,
    mobile_clarity: v,
    composition: v,
    motion_energy: v,
    uniqueness: v,
    overall: v,
  };
}'''


def upgrade(path: Path) -> None:
    text = path.read_text()
    text = replace_required(text, SAFE_GET_OLD, SAFE_GET_NEW, "stock lookup retry")
    text = replace_required(text, PARSE_SCORE_OLD, PARSE_SCORE_NEW, "vision score JSON recovery")
    text = replace_required(
        text,
        'const RUN_MAX_VISION_CALLS = Math.max(1, Number(process.env.BROLL_RUN_MAX_VISION_CALLS || 18));',
        'const RUN_MAX_VISION_CALLS = Math.max(1, Number(process.env.BROLL_RUN_MAX_VISION_CALLS || 28));',
        "run-level vision budget",
    )
    if MARKER not in text:
        raise RuntimeError("b-roll runtime hardening marker missing after transform")
    if "BROLL_RUN_MAX_VISION_CALLS || 18" in text:
        raise RuntimeError("stale 18-call run default survived runtime hardening")
    path.write_text(text)


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: upgrade-compose-runtime-hardening.py BROLL_RESOLVER_JS")
    path = Path(sys.argv[1])
    upgrade(path)
    print(f"runtime-hardened b-roll resolver written to {path}")


if __name__ == "__main__":
    main()
