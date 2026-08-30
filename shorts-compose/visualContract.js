const ABSTRACT_PATTERNS = [
  /\bpercent(age)?\b/i,
  /\bmore than\b.*\bcombined\b/i,
  /\bcompared (with|to)\b/i,
  /\bversus\b|\bvs\.?\b/i,
  /\bper (second|minute|hour|day|year)\b/i,
  /\btimes (larger|bigger|smaller|faster|slower|more|less)\b/i,
  /\bworth\b.*\b(dollar|euro|pound|yen)/i,
  /\bweighs? as much as\b/i,
  /\bcontains?\b.*\bof all\b/i,
  /\bnumber of\b|\bamount of\b|\btotal of\b/i,
  /\bgrew? by\b.*\b(cm|mm|met(er|re)s?|feet|inches)\b/i,
];

const ACTION_WORDS = new Set([
  "breaking", "bursting", "burning", "collapsing", "crashing", "cutting", "diving",
  "dropping", "eating", "erupting", "exploding", "falling", "flying", "freezing",
  "growing", "hitting", "jumping", "melting", "opening", "pouring", "running",
  "sinking", "squeezing", "swimming", "tearing", "turning", "walking", "washing",
]);

const DETERMINISTIC_TEMPLATE_PROOF_MODES = new Set([
  "comparison", "number_visualization", "kinetic_text", "diagram", "timeline", "map",
]);

const TEMPLATE_NAME_TO_PROOF_MODE = {
  comparison: "comparison",
  stat_reveal: "number_visualization",
  kinetic_text: "kinetic_text",
  diagram: "diagram",
  timeline: "timeline",
  map: "map",
};

function normalizeText(v) {
  return String(v || "").replace(/\s+/g, " ").trim();
}

function uniq(values) {
  const out = [];
  const seen = new Set();
  for (const raw of values || []) {
    const v = normalizeText(raw);
    const key = v.toLowerCase();
    if (!v || seen.has(key)) continue;
    seen.add(key);
    out.push(v);
  }
  return out;
}

function tokenize(text) {
  return normalizeText(text).toLowerCase().match(/[a-z0-9][a-z0-9'-]*/g) || [];
}

function inferActions(text) {
  const actions = [];
  for (const word of tokenize(text)) {
    if (ACTION_WORDS.has(word) || (word.endsWith("ing") && word.length > 5)) actions.push(word);
  }
  return uniq(actions).slice(0, 4);
}

function inferEntities({ subject, description, narration, query }) {
  const candidates = [];
  if (subject) candidates.push(subject);
  const source = normalizeText(description || narration || query);
  const chunks = source
    .split(/[,;:.]|\b(?:while|with|beside|next to|against|through|inside|outside|over|under)\b/i)
    .map((s) => s.trim())
    .filter(Boolean);
  for (const chunk of chunks) {
    const words = tokenize(chunk).filter((w) => !/^(the|a|an|this|that|these|those|very|real|cinematic|dramatic|close|up|shot|photo|video)$/.test(w));
    if (words.length >= 1) candidates.push(words.slice(0, 5).join(" "));
  }
  return uniq(candidates).slice(0, 5);
}

function inferRelationship(text) {
  const s = normalizeText(text);
  const rules = [
    [/\b(compared (with|to)|versus|vs\.?)\b/i, "explicit comparison between the named subjects"],
    [/\b(squeez|through|inside|within)\w*\b/i, "the subject must visibly interact with or pass through the named object/space"],
    [/\b(bigger|larger|smaller|taller|shorter|heavier|lighter|more than|less than)\b/i, "the size/scale relationship must be visually legible"],
    [/\b(before|after)\b/i, "the before/after relationship must be visually legible"],
  ];
  for (const [re, label] of rules) if (re.test(s)) return [label];
  return [];
}

function classifyProofMode(contract) {
  const text = [contract.narration, contract.visual_claim, contract.description].filter(Boolean).join(" ");
  const byTemplateName = TEMPLATE_NAME_TO_PROOF_MODE[String(contract.template_name || "").toLowerCase()];
  if (byTemplateName) return byTemplateName;
  if (contract.required_relationships.length && /comparison|size\/scale/.test(contract.required_relationships.join(" "))) return "comparison";
  if (ABSTRACT_PATTERNS.some((re) => re.test(text))) return "annotated_real";
  if (contract.required_actions.length) return "literal_video";
  return "literal_image";
}

function hasExplicitArray(input, key) {
  return Object.prototype.hasOwnProperty.call(input, key) && Array.isArray(input[key]);
}
function explicitArray(input, key) {
  return Array.isArray(input[key]) ? uniq(input[key]) : [];
}

function buildVisualContract(input = {}) {
  const subject = normalizeText(input.subject || input.named_subject);
  const description = normalizeText(input.description || input.visual_prompt || input.query);
  const narration = normalizeText(input.narration || input.point);
  const visualClaim = normalizeText(input.visual_claim || narration || description || subject);

  // Explicit Visual Director arrays are authoritative even when deliberately
  // empty. Heuristics exist only for legacy/manual callers that omit the field;
  // they must never invent extra hard-gate entities/actions/relationships after
  // an upstream planner explicitly decided none are required.
  const entitiesSpecified = hasExplicitArray(input, "required_entities");
  const actionsSpecified = hasExplicitArray(input, "required_actions");
  const relationshipsSpecified = hasExplicitArray(input, "required_relationships");
  const legacyActionsSpecified = hasExplicitArray(input, "required_actions_or_relationships");
  const explicitEntities = explicitArray(input, "required_entities");
  const explicitActions = explicitArray(input, "required_actions");
  const explicitRelationships = explicitArray(input, "required_relationships");
  const legacyActions = explicitArray(input, "required_actions_or_relationships");

  // A rendered graphic/text template (comparison card, stat card, kinetic
  // text, diagram, timeline, map) physically cannot depict a literal
  // photographic entity, action, or relationship - it only draws text,
  // numbers, and simple shapes. Whatever required_entities/actions/
  // relationships were planned for this scene before a resolver fallback
  // silently demoted it to a template (see brollResolver's
  // templateFallbackResult) - or before the Visual Director itself chose a
  // template for a beat that still reads like it needs a real photo - no
  // longer describe anything the render can produce. Holding a template
  // scene to that literal bar is an unwinnable QA gate: it fails every
  // time by construction, regardless of how good the template render is.
  // So for these deterministic templates, the hard-gate arrays are forced
  // empty here, overriding whatever the caller passed in.
  const isDeterministicTemplate = Boolean(TEMPLATE_NAME_TO_PROOF_MODE[normalizeText(input.template_name).toLowerCase()]);

  const requiredEntities = isDeterministicTemplate ? [] : (entitiesSpecified
    ? explicitEntities
    : inferEntities({ subject, description: visualClaim || description, narration, query: input.query })).slice(0, 6);
  const requiredActions = isDeterministicTemplate ? [] : (actionsSpecified
    ? explicitActions
    : (legacyActionsSpecified ? legacyActions : inferActions(visualClaim || description))).slice(0, 5);
  const requiredRelationships = isDeterministicTemplate ? [] : (relationshipsSpecified
    ? explicitRelationships
    : inferRelationship(visualClaim || description)).slice(0, 3);

  const forbiddenVisuals = uniq([
    ...(Array.isArray(input.forbidden_visuals) ? input.forbidden_visuals : []),
    "generic filler that only matches the broad topic",
    "a visually attractive shot that omits the action or relationship in the narration",
  ]);

  const contract = {
    scene_index: Number.isFinite(Number(input.scene_index)) ? Number(input.scene_index) : null,
    narration,
    global_subject: normalizeText(input.global_subject || subject),
    subject,
    description,
    visual_claim: visualClaim,
    required_entities: requiredEntities,
    required_actions: requiredActions,
    required_relationships: requiredRelationships,
    forbidden_visuals: forbiddenVisuals,
    acceptable_visuals: uniq(input.acceptable_visuals || input.acceptable_substitutes || []),
    creative_format: normalizeText(input.creative_format),
    template_name: normalizeText(input.template_name),
    template_data: isDeterministicTemplate && input.template_data && typeof input.template_data === "object" ? input.template_data : null,
    is_deterministic_template: isDeterministicTemplate,
  };
  contract.visual_proof_mode = normalizeText(input.visual_proof_mode) || classifyProofMode(contract);
  return contract;
}

function shouldPreferTemplate(contract) {
  return DETERMINISTIC_TEMPLATE_PROOF_MODES.has(contract.visual_proof_mode);
}

// Summarize what a deterministic template will actually put on screen, so
// the QA judge has something concrete to check legibility/accuracy against
// instead of the free-text visual_claim (which is often written assuming a
// photo - e.g. "must show a verified archival image of X" - even for a
// scene the Visual Director deliberately planned as a text card, or for a
// scene a resolver fallback silently demoted from real footage. That claim
// text primes the judge to expect a photograph no card can produce).
function summarizeTemplateData(templateName, templateData) {
  if (!templateData || typeof templateData !== "object") return "";
  const d = templateData;
  switch (templateName) {
    case "comparison":
      return `On-screen text should read: "${d.leftLabel || ""}: ${d.leftValue || ""}" versus "${d.rightLabel || ""}: ${d.rightValue || ""}".`;
    case "stat_reveal":
      return `On-screen text should read: "${d.statValue || ""}" labeled "${d.label || ""}".`;
    case "kinetic_text":
      return `On-screen text should read: "${d.line || ""}".`;
    case "timeline":
      if (Array.isArray(d.events) && d.events.length) {
        const events = d.events.map((e) => `${e?.date || ""}: ${e?.label || ""}${e?.detail ? ` (${e.detail})` : ""}`).join("; ");
        return `On-screen text should read: title "${d.title || ""}", events - ${events}.`;
      }
      return d.title ? `On-screen text should read: title "${d.title}".` : "";
    case "diagram":
    case "map":
      return d.title ? `On-screen text should read: title "${d.title}".` : "";
    default:
      return "";
  }
}

function buildScoringTarget(contract) {
  if (contract.is_deterministic_template) {
    // A comparison/stat/kinetic-text/diagram/timeline/map card draws text,
    // numbers, and simple shapes - it never contains a literal photo of the
    // subject. Judge it against the narration beat and the actual on-screen
    // text, never against visual_claim - that field may still describe
    // photographic proof this card cannot produce, and including it here
    // has been observed to override the "do not penalize" instruction
    // below and fail the scene anyway.
    return [
      contract.narration ? `Narration for this beat: "${contract.narration}"` : "",
      summarizeTemplateData(contract.template_name, contract.template_data),
      `This is a designed text/graphic card (${contract.template_name || contract.visual_proof_mode}), not a photo or video of the subject.`,
      "Judge only whether the on-screen text/numbers are legible and topically consistent with the narration above - do not penalize the absence of a photographic subject, action, or scene, and do not require any name/date/detail beyond what the on-screen text above actually states.",
    ].filter(Boolean).join(" ");
  }
  const parts = [
    contract.visual_claim,
    contract.global_subject ? `Macro subject: ${contract.global_subject}.` : "",
    contract.required_entities.length ? `Required visible entities: ${contract.required_entities.join(", ")}.` : "",
    contract.required_actions.length ? `Required visible actions/states: ${contract.required_actions.join(", ")}.` : "",
    contract.required_relationships.length ? `Required visible relationships: ${contract.required_relationships.join("; ")}.` : "",
  ];
  return parts.filter(Boolean).join(" ");
}

function passesSemanticGate(score, contract, min = {}) {
  const entityMin = Number(min.entity ?? 85);
  const actionMin = Number(min.action ?? 80);
  const relationshipMin = Number(min.relationship ?? 80);
  if (contract.required_entities.length && Number(score.entity_match || 0) < entityMin) return false;
  if (contract.required_actions.length && Number(score.action_match || 0) < actionMin) return false;
  if (contract.required_relationships.length && Number(score.relationship_match || 0) < relationshipMin) return false;
  return Number(score.semantic_match || score.relevance || 0) >= Number(min.semantic ?? 82);
}

module.exports = {
  buildVisualContract,
  buildScoringTarget,
  classifyProofMode,
  shouldPreferTemplate,
  passesSemanticGate,
  inferActions,
  inferEntities,
  inferRelationship,
  hasExplicitArray,
  DETERMINISTIC_TEMPLATE_PROOF_MODES,
};