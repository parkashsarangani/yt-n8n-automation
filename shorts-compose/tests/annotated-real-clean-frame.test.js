const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const componentPath = path.join(__dirname, "..", "remotion", "src", "compositions", "AnnotatedReal.tsx");
const source = fs.readFileSync(componentPath, "utf8");

test("AnnotatedReal keeps vision diagnostics out of audience-facing video", () => {
  assert.doesNotMatch(source, /Callouts are positioned from visual verification/i);
  assert.doesNotMatch(source, /annotations\s*\.\s*(slice|map)\s*\(/);
  assert.doesNotMatch(source, /<line\b|<circle\b/i);
  assert.doesNotMatch(source, /\{\s*a\.label\s*\}/);
});

test("AnnotatedReal preserves the verified image without diagnostic overlays", () => {
  assert.match(source, /objectFit:\s*"contain"/);
  assert.match(source, /backwards compatibility with already-produced workflow payloads/i);
  assert.match(source, /must never leak into the final Short/i);
});
