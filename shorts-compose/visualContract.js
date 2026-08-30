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
  if (contract.template_name === "comparison") return "comparison";
  if (contract.template_name === "stat_reveal") return "number_visualization";
  if (contract.template_name === "kinetic_text") return "kinetic_text";
  if (["diagram", "timeline", "map"].includes(contract.template_name)) return contract.template_name;
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

  const requiredEntities = (entitiesSpecified
    ? explicitEntities
    : inferEntities({ subject, description: visualClaim || description, narration, query: input.query })).slice(0, 6);
  const requiredActions = (actionsSpecified
    ? explicitActions
    : (legacyActionsSpecified ? legacyActions : inferActions(visualClaim || description))).slice(0, 5);
  const requiredRelationships = (relationshipsSpecified
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
  };
  contract.visual_proof_mode = normalizeText(input.visual_proof_mode) || classifyProofMode(contract);
  return contract;
}

function shouldPreferTemplate(contract) {
  return DETERMINISTIC_TEMPLATE_PROOF_MODES.has(contract.visual_proof_mode);
}

function buildScoringTarget(contract) {
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