#!/usr/bin/env node
/**
 * Standalone regression test for the n8n workflow's deploy-time transform
 * chain and the JS logic embedded in its Code nodes.
 *
 * This does NOT touch the production server, n8n, or any API - it builds the
 * fully-transformed workflow.json locally (by actually running the same 5
 * Python transform scripts deploy.yml runs) and then exercises the resulting
 * node code with `new Function()` against synthetic inputs, the same way a
 * real n8n Code/HTTP node would receive them.
 *
 * Usage: node scripts/test-workflow-logic.js
 * Exit code 0 = all pass, 1 = at least one failure.
 */
'use strict';

const fs = require('fs');
const os = require('os');
const path = require('path');
const { execFileSync } = require('child_process');

const REPO_ROOT = path.resolve(__dirname, '..');
const PY = process.platform === 'win32' ? 'python' : 'python3';

// ---------------------------------------------------------------------------
// Minimal test harness (zero dependencies)
// ---------------------------------------------------------------------------
let pass = 0;
let fail = 0;
const failures = [];

function check(label, condition, detail) {
  if (condition) {
    pass += 1;
    console.log(`  ✓ ${label}`);
  } else {
    fail += 1;
    failures.push(label + (detail ? ` -- ${detail}` : ''));
    console.log(`  ✗ ${label}${detail ? ` -- ${detail}` : ''}`);
  }
}

function section(title) {
  console.log(`\n${title}`);
}

function throws(fn, label, matcher) {
  try {
    fn();
    check(label, false, 'expected to throw, did not');
  } catch (e) {
    const ok = matcher ? matcher(e.message) : true;
    check(label, ok, ok ? undefined : `wrong error: ${e.message}`);
  }
}

function doesNotThrow(fn, label) {
  try {
    fn();
    check(label, true);
  } catch (e) {
    check(label, false, `threw: ${e.message}`);
  }
}

// ---------------------------------------------------------------------------
// Build the fully-transformed workflow by running the real deploy-time chain
// ---------------------------------------------------------------------------
function buildWorkflow() {
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'wf-test-'));
  const scriptsDir = path.join(tmp, 'scripts');
  const shortsDir = path.join(tmp, 'shorts-compose');
  const n8nDir = path.join(tmp, 'n8n');
  fs.mkdirSync(scriptsDir);
  fs.mkdirSync(shortsDir);
  fs.mkdirSync(n8nDir);

  for (const f of fs.readdirSync(path.join(REPO_ROOT, 'scripts'))) {
    if (f.endsWith('.py')) {
      fs.copyFileSync(path.join(REPO_ROOT, 'scripts', f), path.join(scriptsDir, f));
    }
  }
  fs.copyFileSync(
    path.join(REPO_ROOT, 'shorts-compose', 'channel-voice.json'),
    path.join(shortsDir, 'channel-voice.json'),
  );
  fs.copyFileSync(path.join(REPO_ROOT, 'n8n', 'workflow.json'), path.join(n8nDir, 'workflow.json'));

  const steps = [
    ['upgrade-viral-shorts.py', 'workflow.json', 'v1.json'],
    ['upgrade-creative-system.py', 'v1.json', 'v2.json'],
    ['upgrade-workflow-api-budget.py', 'v2.json', 'v3.json'],
    ['upgrade-topic-latency.py', 'v3.json', 'v4.json'],
    ['upgrade-anthropic-parser.py', 'v4.json', 'final.json'],
  ];
  for (const [script, input, output] of steps) {
    execFileSync(PY, [path.join(scriptsDir, script), path.join(n8nDir, input), path.join(n8nDir, output)], {
      cwd: tmp,
      stdio: 'pipe',
    });
  }

  const finalPath = path.join(n8nDir, 'final.json');
  const raw = fs.readFileSync(finalPath, 'utf8');
  return { workflow: JSON.parse(raw), tmpDir: tmp };
}

function nodeMap(workflow) {
  const m = {};
  for (const n of workflow.nodes) m[n.name] = n;
  return m;
}

function runNodeCode(nodes, nodeName, input, extraGlobals) {
  const node = nodes[nodeName];
  if (!node) throw new Error(`node not found: ${nodeName}`);
  const args = ['$input'];
  const vals = [{ first: () => ({ json: input }) }];
  if (extraGlobals) {
    for (const [k, v] of Object.entries(extraGlobals)) {
      args.push(k);
      vals.push(v);
    }
  }
  const fn = new Function(...args, node.parameters.jsCode);
  return fn(...vals);
}

// ---------------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------------
function main() {
  console.log('Building fully-transformed workflow via the real 5-stage deploy chain...');
  const { workflow, tmpDir } = buildWorkflow();
  const nodes = nodeMap(workflow);
  console.log(`Built OK: ${workflow.nodes.length} nodes.\n`);
  console.log('='.repeat(70));

  // -------------------------------------------------------------------
  section('1. Overall workflow structure');
  // -------------------------------------------------------------------
  doesNotThrow(() => JSON.stringify(workflow), 'workflow serializes as valid JSON');
  check('exactly one workflow-level node array', Array.isArray(workflow.nodes), undefined);

  const seenPos = new Map();
  let collisions = 0;
  for (const n of workflow.nodes) {
    const key = n.position.join(',');
    if (seenPos.has(key)) { collisions += 1; console.log(`    collision at ${key}: ${seenPos.get(key)} vs ${n.name}`); }
    seenPos.set(key, n.name);
  }
  check('zero node position collisions', collisions === 0, `${collisions} collisions`);

  const c = workflow.connections;
  const first = (src) => c[src] && c[src].main[0][0] && c[src].main[0][0].node;
  check('topic chain: Generate Topic -> Parse Topic Pool', first('Claude: Generate Topic') === 'Parse Topic Pool');
  check('topic chain: Parse Topic Pool -> Commission Shortlist', first('Parse Topic Pool') === 'Claude: Commission Topic Shortlist');
  check('topic chain: Commission Shortlist -> Extract Generated Topic', first('Claude: Commission Topic Shortlist') === 'Extract Generated Topic');
  check('script chain: Editorial Rewrite -> Parse Editorial', first('Claude: Editorial Rewrite (Stage 2)') === 'Parse Editorial For Visual Director');
  check('script chain: Parse Editorial -> Visual Director', first('Parse Editorial For Visual Director') === 'Claude: Visual Director');
  check('script chain: Visual Director -> Validate Final Script', first('Claude: Visual Director') === 'Validate Final Script');

  // -------------------------------------------------------------------
  section('2. Request timeouts (the hung-execution bug)');
  // -------------------------------------------------------------------
  const timeoutExpectations = {
    'Claude: Generate Topic': 120000,
    'Claude: Commission Topic Shortlist': 90000,
    'Claude: Visual Director': 90000,
    'Claude: Draft Script (Stage 1)': 120000,
    'Claude: Editorial Rewrite (Stage 2)': 120000,
    'ElevenLabs: TTS+Timestamps': 60000,
  };
  for (const [name, expected] of Object.entries(timeoutExpectations)) {
    const actual = nodes[name] && nodes[name].parameters.options && nodes[name].parameters.options.timeout;
    check(`${name} has timeout ${expected}`, actual === expected, `got ${actual}`);
  }

  // -------------------------------------------------------------------
  section('3. Retry-attempt counter (the unbounded-loop bug)');
  // -------------------------------------------------------------------
  // IMPORTANT: an earlier version of this test mocked $('NodeName').item as a
  // simple dictionary lookup and the fix appeared to pass - but that mock did
  // not reflect n8n's real behavior. $('NodeName').item depends on
  // paired-item lineage, which the loop-back edge through the independent
  // "Claude: Generate Topic" HTTP call does not reliably preserve. Confirmed
  // live in production: 5 full retry cycles, scriptAttempt=1 every single
  // time. The fix now uses $getWorkflowStaticData('node'), which does not
  // depend on dataflow/lineage at all - a plain persistent object is an
  // accurate mock of it, unlike $('NodeName').item.
  {
    // Workflow static data persists across the whole n8n instance for this
    // workflow, not just within the mock - model that with one shared object
    // both nodes read/write, exactly like the real $getWorkflowStaticData('node').
    const staticStore = {};
    const getStaticData = () => staticStore;

    const initCode = nodes['Init Script Attempt Counter'].parameters.jsCode;
    const incrementCode = nodes['Increment Script Attempt'].parameters.jsCode;

    function runInit(inputItems) {
      const fn = new Function('$getWorkflowStaticData', '$input', 'return (function(){' + initCode + '})()');
      return fn(getStaticData, { all: () => inputItems });
    }
    function runIncrement(errs) {
      const fn = new Function('$getWorkflowStaticData', '$input', 'return (function(){' + incrementCode + '})()');
      const result = fn(getStaticData, { first: () => ({ json: { _validationErrors: errs } }) });
      return result.json.scriptAttempt;
    }

    // Simulate a stale counter left over from a PREVIOUS execution (static
    // data persists across runs) - Init must reset it, not just skip if unset.
    staticStore.scriptAttempt = 7;
    runInit([{ json: { topics: [] } }]);
    check('Init resets a stale cross-execution counter back to 0', staticStore.scriptAttempt === 0, `got ${staticStore.scriptAttempt}`);

    const seq = [runIncrement(['a']), runIncrement(['b']), runIncrement(['c']), runIncrement(['d'])];
    check('counter increments 1,2,3,4 across loop iterations', JSON.stringify(seq) === JSON.stringify([1, 2, 3, 4]), `got ${JSON.stringify(seq)}`);
    check('counter would now correctly cap at attempt 3 (3 < 3 is false)', !(seq[2] < 3), undefined);

    // A second execution must not see the first execution's leftover count.
    runInit([{ json: { topics: [] } }]);
    check('a fresh execution starts the counter at 0 again after Init', staticStore.scriptAttempt === 0, `got ${staticStore.scriptAttempt}`);
    check('Init passes input items through unchanged', (() => {
      const passed = runInit([{ json: { topics: ['x', 'y'] } }]);
      return Array.isArray(passed) && passed[0].json.topics.length === 2;
    })());
  }

  // -------------------------------------------------------------------
  section('4. Parse Topic Pool (candidate pool = 4, truncation guard)');
  // -------------------------------------------------------------------
  {
    const mkCandidate = (i) => ({
      topic: `topic ${i}`, archetype: 'looks_fake_but_real', research_query: 'q', first_frame_concept: 'f',
      share_reason: 's', evidence_score: 80, visual_score: 80, share_score: 80, reason: 'r', score: 80,
    });
    const ok4 = { content: [{ type: 'text', text: JSON.stringify({ candidates: [1, 2, 3, 4].map(mkCandidate) }) }], stop_reason: 'end_turn' };
    doesNotThrow(() => {
      const r = runNodeCode(nodes, 'Parse Topic Pool', ok4);
      check('  -> pool has 4 entries', r.json.pool.length === 4);
      check('  -> shortlist has 4 entries', r.json.shortlist.length === 4);
    }, '4 valid candidates -> succeeds');

    const tooFew = { content: [{ type: 'text', text: JSON.stringify({ candidates: [mkCandidate(1)] }) }], stop_reason: 'end_turn' };
    throws(() => runNodeCode(nodes, 'Parse Topic Pool', tooFew), 'only 1 candidate -> throws floor error',
      (m) => m.includes('fewer than 3 usable candidates'));

    const truncated = { content: [{ type: 'text', text: '{"candidates":[' + JSON.stringify(mkCandidate(1)) + ',{"topic":"cut off mid' }], stop_reason: 'max_tokens' };
    throws(() => runNodeCode(nodes, 'Parse Topic Pool', truncated), 'max_tokens truncation -> clear diagnostic, not raw SyntaxError',
      (m) => m.includes('truncated by max_tokens'));

    const noTextBlock = { content: [{ type: 'thinking', thinking: '...' }], stop_reason: 'max_tokens' };
    throws(() => runNodeCode(nodes, 'Parse Topic Pool', noTextBlock), 'only thinking block, max_tokens -> clear diagnostic',
      (m) => m.includes('max_tokens') && m.includes('text block'));

    // Regression test for a real production failure: Claude wrote a broken
    // false-start object, caught itself mid-response ("Wait, I need to
    // output proper JSON only."), then wrote the correct JSON right after -
    // both landed in the same complete (non-truncated) response. The old
    // naive indexOf('{')..lastIndexOf('}') extraction grabbed from the
    // false start's opening brace to the real JSON's closing brace, mashing
    // garbage and valid JSON together and crashing with a cryptic
    // SyntaxError even though stop_reason was 'end_turn', not truncated.
    const selfCorrected = {
      content: [{
        type: 'text',
        text: '{"candidates":[[]][0] || null}\n\nWait, I need to output proper JSON only.\n\n'
          + JSON.stringify({ candidates: [1, 2, 3, 4].map(mkCandidate) }),
      }],
      stop_reason: 'end_turn',
    };
    doesNotThrow(() => {
      const r = runNodeCode(nodes, 'Parse Topic Pool', selfCorrected);
      check('  -> recovers the real 4-candidate JSON after a self-correction false-start', r.json.pool.length === 4);
    }, 'Claude self-correction false-start (real production failure) -> recovers correct JSON instead of crashing');
  }

  // -------------------------------------------------------------------
  section('5. Parse Draft JSON / Parse Editorial For Visual Director (undefined-return bug)');
  // -------------------------------------------------------------------
  {
    const draftOk = { content: [{ type: 'text', text: '{"hook":"h"}' }], stop_reason: 'end_turn' };
    const r1 = runNodeCode(nodes, 'Parse Draft JSON', draftOk);
    check('Parse Draft JSON returns a real item, not undefined', r1 !== undefined && r1.json && r1.json.draft.hook === 'h');

    const editOk = { content: [{ type: 'text', text: '{"hook":"h","scenes":[]}' }], stop_reason: 'end_turn' };
    const r2 = runNodeCode(nodes, 'Parse Editorial For Visual Director', editOk);
    check('Parse Editorial returns a real item, not undefined (regression test for the swallowed-comment bug)', r2 !== undefined && r2.json && r2.json.script.hook === 'h');

    const editTruncated = { content: [{ type: 'thinking', thinking: 'x' }], stop_reason: 'max_tokens' };
    throws(() => runNodeCode(nodes, 'Parse Editorial For Visual Director', editTruncated), 'Parse Editorial max_tokens truncation -> clear diagnostic',
      (m) => m.includes('max_tokens'));
  }

  // -------------------------------------------------------------------
  section('6. Validate Final Script - quality gate thresholds + calculation correctness');
  // -------------------------------------------------------------------
  {
    const code = nodes['Validate Final Script'].parameters.jsCode;
    const thresholdMatch = code.match(/qualityMinimums = \{([^}]+)\}/);
    check('qualityMinimums block found', !!thresholdMatch);
    const thresholds = {};
    for (const line of thresholdMatch[1].split(',')) {
      const m = line.match(/(\w+):\s*(\d+)/);
      if (m) thresholds[m[1]] = Number(m[2]);
    }
    const expectedThresholds = {
      concept_strength: 76, hook_strength: 78, evidence_strength: 74, payoff_strength: 76,
      information_density: 74, first_frame_strength: 78, visual_progression: 74, shareability: 76,
      naturalness: 74, distinctiveness: 74, voice_specificity: 72, overall: 77,
    };
    for (const [k, v] of Object.entries(expectedThresholds)) {
      check(`threshold ${k} = ${v}`, thresholds[k] === v, `got ${thresholds[k]}`);
    }
    check('visual_plan_quality threshold = 78', code.includes('below publish threshold 78'), undefined);

    function goodQuality(overrides) {
      return Object.assign({
        concept_strength: 80, hook_strength: 80, evidence_strength: 80, payoff_strength: 80,
        information_density: 80, first_frame_strength: 80, visual_progression: 80,
        shareability: 80, naturalness: 80, distinctiveness: 80, voice_specificity: 80, overall: 80,
      }, overrides);
    }
    const scene = { scene_index: 0, point: 'the point of this scene', narration: 'a real narration line that is definitely long enough to pass', visual_source: 'stock', visual_type: 'real', visual_prompt: 'a real visual prompt describing this specific scene in detail', negative_prompt: 'no readable text, no legible numbers', stock_search_query: 'a real query', search_queries: ['query one', 'query two'], visual_role: 'hero' };
    function buildScript(quality) {
      return {
        hook: 'a real hook that is long enough', title: 'a real title', caption_style: 'neutral', trigger: 'disbelief',
        caption_mode: 'karaoke', creative_format: 'documentary_cinematic', engagement_mode: 'none', first_frame_type: 'hero_motion',
        tags: ['a', 'b', 'c', 'd', 'e'], seo_description: 'a description that is long enough to satisfy the minimum length check',
        comment_hook: null, payoff: { claim: 'a specific promise the hook makes', resolved_in_scene: 0 },
        scenes: [scene, { ...scene, scene_index: 1 }, { ...scene, scene_index: 2 }],
        quality,
      };
    }
    function validate(quality) {
      const response = { content: [{ type: 'text', text: JSON.stringify(buildScript(quality)) }], stop_reason: 'end_turn' };
      return runNodeCode(nodes, 'Validate Final Script', response);
    }

    const passing = validate(goodQuality());
    check('a genuinely good script (all 80s, consistent overall) passes', passing.json._scriptValid === true, JSON.stringify(passing.json._validationErrors));

    const belowGate = validate(goodQuality({ hook_strength: 70 }));
    check('a script scoring below the new mid-70s gate is still rejected', belowGate.json._scriptValid === false &&
      belowGate.json._validationErrors.some((e) => e.includes('hook_strength')));

    const inflated = validate(goodQuality({ concept_strength: 76, overall: 90 }));
    check('inflated overall (exceeds weakest dimension by >5) is rejected',
      inflated.json._validationErrors && inflated.json._validationErrors.some((e) => e.includes('exceeds the weakest scored dimension')));

    const consistent = validate(goodQuality({ concept_strength: 76, overall: 80 }));
    const hasOverallError = consistent.json._validationErrors && consistent.json._validationErrors.some((e) => e.includes('overall'));
    check('consistent overall (within 5 of weakest dimension) is not flagged by the overall-consistency check', !hasOverallError,
      JSON.stringify(consistent.json._validationErrors));
  }

  // -------------------------------------------------------------------
  section('7. Merge By scene_index - asset quality aggregation ("resources" fix)');
  // -------------------------------------------------------------------
  {
    const code = nodes['Merge By scene_index (not position)'].parameters.jsCode;
    const fn = new Function('$input', '$', code);
    const mockDollar = () => ({
      item: {
        json: {
          hook: 'h', comment_hook: 'c', full_script: 'f', caption_style: 'neutral', caption_mode: 'karaoke',
          creative_format: 'documentary_cinematic', visual_grammar: 'x', engagement_mode: 'none', outro_line: null,
        },
      },
    });

    function runMerge(videos, audios) {
      return fn({ all: () => [{ json: { data: videos } }, { json: { data: audios } }] }, mockDollar);
    }

    const mixed = runMerge(
      [
        { scene_index: 0, images: ['a'], visual_source: 'stock', asset_score: 82 },
        { scene_index: 1, images: ['b'], visual_source: 'stock', asset_score: 90 },
        { scene_index: 2, visual_source: 'template', template_name: 'kinetic_text', template_data: {} },
      ],
      [0, 1, 2].map((i) => ({ scene_index: i, audio: { a: 1 } })),
    );
    check('mixed stock+template scenes: asset_quality_min = 82', mixed.json.asset_quality_min === 82, `got ${mixed.json.asset_quality_min}`);
    check('mixed stock+template scenes: asset_quality_avg = 86', mixed.json.asset_quality_avg === 86, `got ${mixed.json.asset_quality_avg}`);
    check('template scene correctly excluded from per-scene asset_score', mixed.json.data[2].asset_score === undefined);

    const allTemplate = runMerge(
      [{ scene_index: 0, visual_source: 'template', template_name: 'kinetic_text', template_data: {} }],
      [{ scene_index: 0, audio: { a: 1 } }],
    );
    check('all-template video: asset_quality_min is null (not 0, not NaN)', allTemplate.json.asset_quality_min === null);
    check('all-template video: asset_quality_avg is null (not 0, not NaN)', allTemplate.json.asset_quality_avg === null);

    const logCode = nodes['Log Published Video'].parameters.jsonBody;
    check('Log Published Video no longer hardcodes null', !logCode.includes('asset_quality_min: null'));
    check('Log Published Video references the real aggregated field', logCode.includes("$('Merge By scene_index (not position)').item.json.asset_quality_min"));
  }

  // -------------------------------------------------------------------
  console.log('\n' + '='.repeat(70));
  console.log(`${pass} passed, ${fail} failed`);
  if (fail > 0) {
    console.log('\nFailures:');
    for (const f of failures) console.log('  - ' + f);
  }
  fs.rmSync(tmpDir, { recursive: true, force: true });
  process.exit(fail > 0 ? 1 : 0);
}

main();
