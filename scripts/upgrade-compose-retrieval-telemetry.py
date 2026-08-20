#!/usr/bin/env python3
"""Patch compose service with isolated retrieval-telemetry persistence/read API."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

MARKER = "RETRIEVAL_TELEMETRY_ENDPOINT_V1"


def patch(text: str) -> str:
    if MARKER in text:
        return text

    require_anchor = 'const feedback = require("./feedbackLoop");'
    require_replacement = require_anchor + '\nconst retrievalTelemetry = require("./retrievalTelemetryStore");'
    if require_anchor not in text:
        raise ValueError("feedback require anchor missing")
    text = text.replace(require_anchor, require_replacement, 1)

    old = '''app.post("/performance/log", async (req, res) => {
  try {
    const result = await feedback.logPublished(req.body || {});
    res.json({ success: true, ...result });
  } catch (err) {
    res.status(400).json({ success: false, error: err.message });
  }
});'''
    new = '''// RETRIEVAL_TELEMETRY_ENDPOINT_V1: telemetry failure must never block normal publish logging.
app.post("/performance/log", async (req, res) => {
  try {
    try {
      await retrievalTelemetry.log(req.body || {});
    } catch (telemetryErr) {
      console.warn("[retrieval-telemetry] write failed:", telemetryErr?.message || telemetryErr);
    }
    const result = await feedback.logPublished(req.body || {});
    res.json({ success: true, ...result });
  } catch (err) {
    res.status(400).json({ success: false, error: err.message });
  }
});

app.get("/performance/retrieval", async (req, res) => {
  try {
    const limit = Math.max(1, Math.min(100, Number(req.query.limit) || 20));
    const items = await retrievalTelemetry.getRecent({ limit });
    res.json({ count: items.length, items });
  } catch (err) {
    res.status(500).json({ count: 0, items: [], error: err.message });
  }
});'''
    if old not in text:
        raise ValueError("performance/log endpoint anchor missing")
    return text.replace(old, new, 1)


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: upgrade-compose-retrieval-telemetry.py COMPOSE_JS")
    path = Path(sys.argv[1])
    text = patch(path.read_text())
    path.write_text(text)
    p = subprocess.run(["node", "--check", str(path)], text=True, capture_output=True)
    if p.returncode != 0:
        raise RuntimeError("compose retrieval telemetry syntax check failed:\n" + p.stdout + p.stderr)
    if MARKER not in text or '/performance/retrieval' not in text:
        raise RuntimeError("compose retrieval telemetry patch did not land")
    print(f"retrieval telemetry endpoints written to {path}")


if __name__ == "__main__":
    main()
