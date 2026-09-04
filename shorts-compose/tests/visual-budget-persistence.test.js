const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { spawnSync } = require("node:child_process");

const modulePath = path.join(__dirname, "..", "visualBudget.js");

function child(statePath, code) {
  const result = spawnSync(process.execPath, ["-e", code], {
    encoding: "utf8",
    env: {
      ...process.env,
      BROLL_BUDGET_STATE_PATH: statePath,
      BROLL_RUN_MAX_VISION_CALLS: "2",
      BROLL_SCORE_CACHE_MAX: "100",
    },
  });
  if (result.status !== 0) throw new Error(result.stderr || `child exited ${result.status}`);
  return JSON.parse(result.stdout.trim());
}

test("vision budget survives fresh Node processes and enforces one shared ceiling", () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "visual-budget-test-"));
  const statePath = path.join(dir, "state.json");
  const req = JSON.stringify(modulePath);

  const first = child(statePath, `const b=require(${req});console.log(JSON.stringify(b.reserveVisionCall('run-persist')));`);
  assert.equal(first.allowed, true);
  assert.equal(first.used, 1);

  const second = child(statePath, `const b=require(${req});console.log(JSON.stringify(b.reserveVisionCall('run-persist')));`);
  assert.equal(second.allowed, true);
  assert.equal(second.used, 2);

  const third = child(statePath, `const b=require(${req});console.log(JSON.stringify(b.reserveVisionCall('run-persist')));`);
  assert.equal(third.allowed, false);
  assert.equal(third.reason, "run_vision_budget_exhausted");

  const snapshot = child(statePath, `const b=require(${req});console.log(JSON.stringify(b.getBudgetState('run-persist')));`);
  assert.equal(snapshot.run_used, 2);
  assert.equal(snapshot.run_remaining, 0);
  assert.equal(snapshot.durable_state, true);
});

test("template fallback reservation is atomic across fresh processes", () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "visual-budget-template-test-"));
  const statePath = path.join(dir, "state.json");
  const req = JSON.stringify(modulePath);

  const first = child(statePath, `const b=require(${req});console.log(JSON.stringify(b.reserveTemplateFallback('run-template',2,{planned_template_count:0})));`);
  assert.equal(first.allowed, true);

  const second = child(statePath, `const b=require(${req});console.log(JSON.stringify(b.reserveTemplateFallback('run-template',3,{planned_template_count:0})));`);
  assert.equal(second.allowed, false);
  assert.equal(second.reason, "template_fallback_cap_exhausted");
});
