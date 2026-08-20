#!/usr/bin/env python3
"""Harden Anthropic JSON parsing and deterministic visual-schema repair.

Every Anthropic JSON-producing stage uses the same contract after this final
transform:
- concatenate every text block in order (adaptive thinking may split content),
- fail clearly on max_tokens truncation,
- recover the LAST complete valid JSON object when Claude self-corrects,
- preserve fail-closed creative and asset-quality gates.

The final transform also aligns commissioning/writer/editor/visual prompts to
the deterministic quality and b-roll gates.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from upgrade_quality_alignment import assert_alignment, upgrade as upgrade_quality_alignment

MARKER = "ANTHROPIC_TEXT_BLOCK_GUARD"
JSON_RECOVERY_MARKER = "LAST_VALID_JSON_OBJECT"
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
    # Join with no separator: if Anthropic splits a JSON string across two text
    # blocks, injecting a newline would corrupt the JSON string literal.
    return f"""// {MARKER}: Anthropic may emit thinking/signature blocks before or between text.\nconst contentBlocks = Array.isArray(response.content) ? response.content : [];\nconst textBlocks = contentBlocks.filter(b => b && b.type === 'text' && typeof b.text === 'string');\nlet raw = textBlocks.map(b => b.text).join('').trim();\nif (!raw) {{\n  const blockTypes = contentBlocks.map(b => b?.type || 'unknown').join(', ') || 'none';\n  if (response.stop_reason === 'max_tokens') {{\n    throw new Error('{label} hit max_tokens before producing a text block (content types: ' + blockTypes + ')');\n  }}\n  throw new Error('{label} returned no text block (stop_reason: ' + (response.stop_reason || 'unknown') + ', content types: ' + blockTypes + ')');\n}}"""


def last_valid_json_js() -> str:
    return f"""// {JSON_RECOVERY_MARKER}: Claude can emit a malformed false start and then a corrected JSON object.\nfunction extractBalancedJsonObjects(s) {{\n  const out = [];\n  let i = 0;\n  while (i < s.length) {{\n    const start = s.indexOf('{{', i);\n    if (start < 0) break;\n    let depth = 0, inStr = false, esc = false, end = -1;\n    for (let j = start; j < s.length; j++) {{\n      const ch = s[j];\n      if (inStr) {{\n        if (esc) esc = false;\n        else if (ch === '\\\\') esc = true;\n        else if (ch === '\"') inStr = false;\n      }} else if (ch === '\"') inStr = true;\n      else if (ch === '{{') depth += 1;\n      else if (ch === '}}') {{\n        depth -= 1;\n        if (depth === 0) {{ end = j; break; }}\n      }}\n    }}\n    if (end < 0) break;\n    out.push(s.slice(start, end + 1));\n    i = end + 1;\n  }}\n  return out;\n}}\nfunction parseLastValidJsonObject(s) {{\n  const value = String(s || '');\n  // Stage 1/2 use an assistant prefill of "{{", so also scan a prefixed copy.\n  // Direct candidates come first; prefixed candidates come last so a complete\n  // prefill-repaired object wins when the leading brace is absent.\n  const candidates = [...extractBalancedJsonObjects(value), ...extractBalancedJsonObjects('{{' + value)];\n  for (let i = candidates.length - 1; i >= 0; i--) {{\n    try {{\n      const parsed = JSON.parse(candidates[i]);\n      if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) return parsed;\n    }} catch {{}}\n  }}\n  for (const candidate of [value, '{{' + value]) {{\n    try {{\n      const parsed = JSON.parse(candidate);\n      if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) return parsed;\n    }} catch {{}}\n  }}\n  return undefined;\n}}"""


def patch_topic_pool_parser(workflow: dict) -> None:
    node = node_by_name(workflow, "Parse Topic Pool")
    code = node["parameters"]["jsCode"]
    old = "const tb=contentBlocks.find(b=>b&&b.type==='text');\nlet raw=String(tb?.text||'').trim().replace(/^```(?:json)?\\s*/i,'').replace(/```\\s*$/,'');"
    new = (
        f"// {MARKER}: consume all text blocks, not only the first one.\n"
        "const textBlocks=contentBlocks.filter(b=>b&&b.type==='text'&&typeof b.text==='string');\n"
        "let raw=String(textBlocks.map(b=>b.text).join('')||'').trim().replace(/^```(?:json)?\\s*/i,'').replace(/```\\s*$/,'');"
    )
    node["parameters"]["jsCode"] = replace_once(code, old, new, "topic-pool Anthropic text blocks")


def patch_commission_parser(workflow: dict) -> None:
    """Replace the inherited Generate Topic parser with a strict commissioner parser.

    Commission Topic Shortlist returns ranked candidates, so the old fallback
    that treated malformed JSON as a single topic is unsafe here: it can silently
    convert model prose/garbage into a production topic. Fail closed instead.
    """
    node = node_by_name(workflow, "Extract Generated Topic")
    node["parameters"]["jsCode"] = f"""const response = $input.first().json;\nif (response.error) throw new Error('Topic commissioning API error: ' + JSON.stringify(response.error));\n{robust_text_extract('Topic commissioning response')}\nif (response.stop_reason === 'max_tokens') throw new Error('Topic commissioning response was cut off by max_tokens - refusing a partial shortlist');\nraw = raw.replace(/^```(?:json)?\\s*/i, '').replace(/```\\s*$/, '').trim();\n{last_valid_json_js()}\nconst obj = parseLastValidJsonObject(raw);\nif (!obj || !Array.isArray(obj.candidates)) throw new Error('Topic commissioning returned no valid candidates JSON object (stop_reason: ' + (response.stop_reason || 'unknown') + ')');\nlet candidates = obj.candidates\n  .filter(c => c && c.topic && String(c.topic).trim().length >= 10)\n  .map(c => ({{\n    topic: String(c.topic).trim(),\n    archetype: String(c.archetype || 'looks_fake_but_real').trim(),\n    research_query: String(c.research_query || c.topic).trim(),\n    first_frame_concept: String(c.first_frame_concept || '').trim(),\n    share_reason: String(c.share_reason || '').trim(),\n    evidence_score: Number(c.evidence_score) || 0,\n    visual_score: Number(c.visual_score) || 0,\n    share_score: Number(c.share_score) || 0,\n    concept_score: Number(c.concept_score) || 0,\n    payoff_score: Number(c.payoff_score) || 0,\n    novelty_score: Number(c.novelty_score) || 0,\n    execution_score: Number(c.execution_score) || 0,\n    distinctiveness_score: Number(c.distinctiveness_score) || 0,\n    share_trigger: String(c.share_trigger || ''),\n    send_to_person: String(c.send_to_person || ''),\n    novelty_delta: String(c.novelty_delta || ''),\n    proof_visual: String(c.proof_visual || ''),\n    stock_feasibility: Number(c.stock_feasibility) || 0,\n    stock_query_seed: Array.isArray(c.stock_query_seed) ? c.stock_query_seed.map(String).filter(Boolean).slice(0, 4) : [],\n    reason: String(c.reason || ''),\n    score: Number(c.score) || 0,\n  }}))\n  .sort((a, b) => b.score - a.score);\nif (!candidates.length) throw new Error('Topic commissioning produced zero usable candidates');\nconst used = (($('Ensure Topics Array').item.json.topics) || []).map(t => String((t && t.topic) || '').toLowerCase()).filter(Boolean);\nconst words = s => String(s || '').toLowerCase().replace(/[^a-z0-9 ]/g, ' ').split(/\\s+/).filter(w => w.length > 3);\nfunction tooSimilar(topic) {{\n  const tl = String(topic || '').toLowerCase();\n  const w = new Set(words(topic));\n  for (const u of used) {{\n    if (u && (u.includes(tl) || tl.includes(u))) return true;\n    const uw = words(u);\n    if (uw.length && uw.filter(x => w.has(x)).length / uw.length >= 0.6) return true;\n  }}\n  return false;\n}}\nconst picked = candidates.find(c => !tooSimilar(c.topic)) || candidates[0];\nreturn {{ json: {{\n  topic: picked.topic, archetype: picked.archetype || 'looks_fake_but_real', score: picked.score,\n  research_query: picked.research_query || picked.topic, first_frame_concept: picked.first_frame_concept || '',\n  share_reason: picked.share_reason || '', evidence_score: picked.evidence_score || 0, visual_score: picked.visual_score || 0,\n  share_score: picked.share_score || 0, concept_score: picked.concept_score || 0, payoff_score: picked.payoff_score || 0,\n  novelty_score: picked.novelty_score || 0, execution_score: picked.execution_score || 0,\n  distinctiveness_score: picked.distinctiveness_score || 0, share_trigger: picked.share_trigger || '',\n  send_to_person: picked.send_to_person || '', novelty_delta: picked.novelty_delta || '', proof_visual: picked.proof_visual || '',\n  stock_feasibility: picked.stock_feasibility || 0, stock_query_seed: picked.stock_query_seed || [],\n  candidates, candidate_pool: $('Parse Topic Pool').item.json.pool || candidates\n}} }};"""


def patch_draft_parser(workflow: dict) -> None:
    node = node_by_name(workflow, "Parse Draft JSON")
    code = node["parameters"]["jsCode"]
    old_text = """let raw = response.content?.[0]?.text;\nif (!raw) throw new Error('Claude draft response missing content[0].text');"""
    code = replace_once(code, old_text, robust_text_extract("Claude draft response"), "draft Anthropic text parser")
    old_parse = "const parsed = tryParse(raw) || tryParse('{' + raw) || tryParse(extractJsonObject('{' + raw)) || tryParse(extractJsonObject(raw));"
    new_parse = last_valid_json_js() + "\nconst parsed = parseLastValidJsonObject(raw);"
    node["parameters"]["jsCode"] = replace_once(code, old_parse, new_parse, "draft last-valid JSON recovery")


def patch_editor_parser(workflow: dict) -> None:
    node = node_by_name(workflow, "Parse Editorial For Visual Director")
    node["parameters"]["jsCode"] = f"""const response=$input.first().json;\nif(response.error)throw new Error('Editorial API error: '+JSON.stringify(response.error));\n{robust_text_extract('Editorial API response')}\nif(response.stop_reason==='max_tokens')throw new Error('Editorial API hit max_tokens with partial text - the JSON response was truncated before completion');\nraw=raw.replace(/^```(?:json)?\\s*/i,'').replace(/```\\s*$/,'').trim();\n{last_valid_json_js()}\nconst parsed=parseLastValidJsonObject(raw);\nif(!parsed)throw new Error('Editorial pass returned no valid complete JSON object (stop_reason: '+(response.stop_reason||'unknown')+')');\nreturn {{json:{{script:parsed}}}};"""


def patch_final_parser(workflow: dict) -> None:
    node = node_by_name(workflow, "Validate Final Script")
    code = node["parameters"]["jsCode"]
    old_text = """let raw = response.content?.[0]?.text;\nif (!raw) throw new Error('Claude editor response missing content[0].text');"""
    code = replace_once(code, old_text, robust_text_extract("Claude visual-director response"), "final Anthropic text parser")
    old_parse = "const parsed = tryParse(raw) || tryParse('{' + raw) || tryParse(extractJsonObject('{' + raw)) || tryParse(extractJsonObject(raw));"
    new_parse = last_valid_json_js() + "\nconst parsed = parseLastValidJsonObject(raw);"
    code = replace_once(code, old_parse, new_parse, "final last-valid JSON recovery")
    code = code.replace(
        "Claude editorial rewrite was cut off by max_tokens - likely truncated mid-JSON. Increase max_tokens on the \\\"Claude: Editorial Rewrite (Stage 2)\\\" node.",
        "Claude visual-director response was cut off by max_tokens - likely truncated mid-JSON; refusing partial output.",
    )
    node["parameters"]["jsCode"] = code


def patch_visual_schema_normalizer(workflow: dict) -> None:
    node = node_by_name(workflow, "Validate Final Script")
    code = node["parameters"]["jsCode"]
    if VISUAL_SCHEMA_MARKER in code:
        return

    anchor = "const errors = [];"
    normalizer = f"""// {VISUAL_SCHEMA_MARKER}: repair deterministic Visual Director omissions before fail-closed validation.\n// This normalizes metadata/search hints and keeps full_script synchronized with final scene narration.\n// It does not change facts, quality scores, evidence, or asset thresholds.\nconst normalizeSearchQuery=(value,maxWords=5)=>String(value||'').replace(/[^a-zA-Z0-9' -]+/g,' ').replace(/\\s+/g,' ').trim().split(' ').filter(Boolean).slice(0,maxWords).join(' ');\nconst dedupeSearchQueries=(values)=>{{const out=[];const seen=new Set();for(const value of values){{const q=normalizeSearchQuery(value);const key=q.toLowerCase();if(q&&!seen.has(key)){{seen.add(key);out.push(q);}}}}return out;}};\nif(!parsed.first_frame_type){{const byFormat={{documentary_cinematic:'hero_motion',comparison_reveal:'scale_comparison',minimal_proof:'result_first',archival_history:'archive_proof',macro_detail:'macro_anomaly',kinetic_data:'kinetic_stat'}};parsed.first_frame_type=byFormat[parsed.creative_format]||'result_first';}}\nconst hasComment=Boolean(String(parsed.comment_hook||'').trim());\nconst hasShareOutro=Boolean(String(parsed.outro_line||'').trim());\nparsed.engagement_mode=hasComment&&hasShareOutro?'comment_and_share':hasComment?'comment_only':hasShareOutro?'share_only':'none';\nif(Array.isArray(parsed.scenes)){{\n  const orderedContentScenes=parsed.scenes.filter(s=>s&&!s?.template_data?.is_outro).sort((a,b)=>Number(a.scene_index)-Number(b.scene_index));\n  const rebuiltFullScript=orderedContentScenes.map(s=>String(s.narration||'').trim()).filter(Boolean).join(' ');\n  if(rebuiltFullScript)parsed.full_script=rebuiltFullScript;\n  parsed.scenes.forEach((s,i)=>{{\n    if(!s||s?.template_data?.is_outro||s.visual_source==='template')return;\n    let queries=dedupeSearchQueries([...(Array.isArray(s.search_queries)?s.search_queries:[]),s.stock_search_query,s.named_subject,s.visual_prompt,s.point]);\n    const base=queries[0]||normalizeSearchQuery(s.named_subject||s.visual_prompt||s.point||parsed.title||'visual subject',4);\n    const broad=normalizeSearchQuery(s.named_subject||base,3)||base;\n    const variantSuffix=i===0?'close up':s.visual_role==='comparison'?'comparison':'detail';\n    queries=dedupeSearchQueries([...queries,broad,`${{broad}} ${{variantSuffix}}`,`${{broad}} footage`]);\n    const wanted=i===0?4:3;\n    s.search_queries=queries.slice(0,wanted);\n    if(!String(s.stock_search_query||'').trim()&&s.search_queries[0])s.stock_search_query=s.search_queries[0];\n  }});\n}}\n\n"""
    if anchor not in code:
        raise ValueError("could not patch visual schema normalizer: pre-validation anchor not found")
    code = code.replace(anchor, normalizer + anchor, 1)
    # Prompt + deterministic normalizer now guarantee three retrieval variants;
    # enforce the same contract instead of silently accepting only two.
    code = code.replace(
        "(!Array.isArray(s.search_queries)||s.search_queries.filter(Boolean).length<2))errors.push(`scene ${i} needs at least 2 search_queries`)",
        "(!Array.isArray(s.search_queries)||s.search_queries.filter(Boolean).length<3))errors.push(`scene ${i} needs at least 3 search_queries`)",
    )
    node["parameters"]["jsCode"] = code


def upgrade(workflow: dict) -> dict:
    # Apply prompt alignment first, then harden the final generated nodes so the
    # parser layer always sees the exact schema/prompts that production will use.
    upgrade_quality_alignment(workflow)
    patch_topic_pool_parser(workflow)
    patch_commission_parser(workflow)
    patch_draft_parser(workflow)
    patch_editor_parser(workflow)
    patch_final_parser(workflow)
    patch_visual_schema_normalizer(workflow)
    return workflow


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit("usage: upgrade-anthropic-parser.py INPUT_WORKFLOW OUTPUT_WORKFLOW")
    src, dst = map(Path, sys.argv[1:])
    workflow = json.loads(src.read_text())
    upgraded = upgrade(workflow)

    names = {n.get("name"): n for n in upgraded.get("nodes", [])}
    for parser_name in ["Extract Generated Topic", "Parse Draft JSON", "Parse Editorial For Visual Director", "Validate Final Script"]:
        code = names[parser_name]["parameters"]["jsCode"]
        if MARKER not in code or JSON_RECOVERY_MARKER not in code:
            raise RuntimeError(f"Anthropic parser hardening did not land in {parser_name}")
        if "content?.[0]?.text" in code:
            raise RuntimeError(f"brittle content[0].text parser survived in {parser_name}")
    topic_pool_code = names["Parse Topic Pool"]["parameters"]["jsCode"]
    if MARKER not in topic_pool_code or "textBlocks.map(b=>b.text).join('')" not in topic_pool_code:
        raise RuntimeError("topic-pool multi-text-block hardening did not land")

    validate_code = names["Validate Final Script"]["parameters"]["jsCode"]
    if VISUAL_SCHEMA_MARKER not in validate_code:
        raise RuntimeError("visual schema normalizer did not land in Validate Final Script")
    marker_pos = validate_code.index(VISUAL_SCHEMA_MARKER)
    errors_pos = validate_code.index("const errors = [];")
    stock_check_pos = validate_code.index("missing stock_search_query")
    if not marker_pos < errors_pos < stock_check_pos:
        raise RuntimeError("visual schema normalizer ordering is unsafe: it must precede all validation checks")
    if "needs at least 3 search_queries" not in validate_code:
        raise RuntimeError("visual retrieval validator drifted below the three-query contract")
    if "rebuiltFullScript" not in validate_code:
        raise RuntimeError("full_script is no longer synchronized with final scene narration")

    assert_alignment(upgraded)

    dst.write_text(json.dumps(upgraded, indent=2) + "\n")
    print(f"Anthropic parser workflow written to {dst}")


if __name__ == "__main__":
    main()
