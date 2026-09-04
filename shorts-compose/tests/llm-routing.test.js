const test = require("node:test");
const assert = require("node:assert/strict");
const axios = require("axios");

// Configure deterministic test-only credentials/models before llmRouting is
// loaded because its runtime policy is intentionally read once at process boot.
process.env.FREELLMAPI_API_KEY = "freellmapi-test-key";
process.env.FREELLMAPI_TEXT_MODEL = "auto:fast";
process.env.FREELLMAPI_VISION_MODEL = "auto:smart";
process.env.OPENAI_KEY = "paid-openai-test-key";
process.env.ANTHROPIC_KEY = "paid-anthropic-test-key";

const routing = require("../llmRouting");

test("detects vision payloads and chooses the configured free vision route", () => {
  const body = {
    model: "gpt-5.6-luna",
    messages: [{ role: "user", content: [
      { type: "image_url", image_url: { url: "data:image/png;base64,AAAA" } },
      { type: "text", text: "judge this" },
    ] }],
  };
  assert.equal(routing.hasVisionPayload(body), true);
  assert.equal(routing.freeModelFor(body, "chat"), "auto:smart");
});

test("plain text uses the configured free text model", () => {
  const body = { model: "gpt-5.6-luna", messages: [{ role: "user", content: "write a script" }] };
  assert.equal(routing.hasVisionPayload(body), false);
  assert.equal(routing.freeModelFor(body, "chat"), "auto:fast");
});

test("recognizes current OpenAI and Anthropic LLM endpoints", () => {
  assert.equal(routing.surfaceForUrl("https://api.openai.com/v1/chat/completions"), "chat");
  assert.equal(routing.surfaceForUrl("https://api.openai.com/v1/responses"), "responses");
  assert.equal(routing.surfaceForUrl("https://api.anthropic.com/v1/messages"), "messages");
  assert.equal(routing.surfaceForUrl("https://api.pexels.com/v1/search"), null);
});

test("free targets stay on the internal FreeLLMAPI service", () => {
  assert.equal(routing.freeTarget("chat"), "http://freellmapi:3001/v1/chat/completions");
  assert.equal(routing.freeTarget("responses"), "http://freellmapi:3001/v1/responses");
  assert.equal(routing.freeTarget("messages"), "http://freellmapi:3001/v1/messages");
});

test("direct targets remain available as an emergency rollback path", () => {
  assert.equal(routing.directTarget("chat"), "https://api.openai.com/v1/chat/completions");
  assert.equal(routing.directTarget("responses"), "https://api.openai.com/v1/responses");
  assert.equal(routing.directTarget("messages"), "https://api.anthropic.com/v1/messages");

  const direct = routing.makeDirectRequest("chat", {
    model: "gpt-original-paid-model",
    messages: [{ role: "user", content: "hello" }],
  });
  assert.equal(direct.data.model, "gpt-original-paid-model");
  assert.equal(direct.url, "https://api.openai.com/v1/chat/completions");
  assert.equal(direct.headers.Authorization, "Bearer paid-openai-test-key");
});

test("free request replaces the paid model but preserves the request payload", () => {
  const original = {
    model: "gpt-paid-model",
    response_format: { type: "json_object" },
    messages: [{ role: "user", content: "return JSON" }],
  };
  const free = routing.makeFreeRequest("chat", original);
  assert.equal(free.url, "http://freellmapi:3001/v1/chat/completions");
  assert.equal(free.data.model, "auto:fast");
  assert.deepEqual(free.data.response_format, original.response_format);
  assert.deepEqual(free.data.messages, original.messages);
  assert.equal(free.headers.Authorization, "Bearer freellmapi-test-key");
});

test("preloaded axios interceptor really rewrites an existing direct OpenAI call", async () => {
  const originalAdapter = axios.defaults.adapter;
  let observed = null;
  axios.defaults.adapter = async (config) => {
    observed = config;
    return {
      data: { choices: [{ message: { content: "ok" } }] },
      status: 200,
      statusText: "OK",
      headers: {},
      config,
    };
  };

  try {
    await axios.post(
      "https://api.openai.com/v1/chat/completions",
      { model: "gpt-paid-model", messages: [{ role: "user", content: "hello" }] },
      { headers: { Authorization: "Bearer should-be-replaced", "content-type": "application/json" } },
    );
  } finally {
    axios.defaults.adapter = originalAdapter;
  }

  assert.ok(observed);
  assert.equal(observed.url, "http://freellmapi:3001/v1/chat/completions");
  const body = routing.parseBody(observed.data);
  assert.equal(body.model, "auto:fast");
  const authorization = typeof observed.headers?.get === "function"
    ? observed.headers.get("Authorization")
    : observed.headers?.Authorization;
  assert.equal(authorization, "Bearer freellmapi-test-key");
});
