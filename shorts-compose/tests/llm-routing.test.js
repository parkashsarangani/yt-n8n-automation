const test = require("node:test");
const assert = require("node:assert/strict");

const routing = require("../llmRouting");

test("detects vision payloads and chooses the vision route", () => {
  const body = {
    model: "gpt-5.6-luna",
    messages: [{ role: "user", content: [
      { type: "image_url", image_url: { url: "data:image/png;base64,AAAA" } },
      { type: "text", text: "judge this" },
    ] }],
  };
  assert.equal(routing.hasVisionPayload(body), true);
  assert.equal(routing.freeModelFor(body, "chat"), process.env.FREELLMAPI_VISION_MODEL || "auto:smart");
});

test("plain text uses the free text model", () => {
  const body = { model: "gpt-5.6-luna", messages: [{ role: "user", content: "write a script" }] };
  assert.equal(routing.hasVisionPayload(body), false);
  assert.equal(routing.freeModelFor(body, "chat"), process.env.FREELLMAPI_TEXT_MODEL || "auto:smart");
});

test("recognizes current OpenAI and Anthropic LLM endpoints", () => {
  assert.equal(routing.surfaceForUrl("https://api.openai.com/v1/chat/completions"), "chat");
  assert.equal(routing.surfaceForUrl("https://api.openai.com/v1/responses"), "responses");
  assert.equal(routing.surfaceForUrl("https://api.anthropic.com/v1/messages"), "messages");
  assert.equal(routing.surfaceForUrl("https://api.pexels.com/v1/search"), null);
});

test("free targets stay on the internal FreeLLMAPI service", () => {
  assert.match(routing.freeTarget("chat"), /^http:\/\/freellmapi:3001\/v1\/chat\/completions$/);
  assert.match(routing.freeTarget("responses"), /^http:\/\/freellmapi:3001\/v1\/responses$/);
  assert.match(routing.freeTarget("messages"), /^http:\/\/freellmapi:3001\/v1\/messages$/);
});

test("direct targets remain available as an emergency rollback path", () => {
  assert.equal(routing.directTarget("chat"), "https://api.openai.com/v1/chat/completions");
  assert.equal(routing.directTarget("responses"), "https://api.openai.com/v1/responses");
  assert.equal(routing.directTarget("messages"), "https://api.anthropic.com/v1/messages");
});
