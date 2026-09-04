const express = require("express");
const { requestViaRouter, routingStatus } = require("./llmRouting");

const app = express();
const port = Number(process.env.LLM_GATEWAY_PORT || 3100);

app.use(express.json({ limit: process.env.LLM_GATEWAY_BODY_LIMIT || "20mb" }));

app.get("/health", (_req, res) => {
  res.json({ ok: true, ...routingStatus() });
});

async function proxy(surface, req, res) {
  try {
    const result = await requestViaRouter(surface, req.body || {}, {
      timeout: Number(req.get("x-llm-timeout-ms") || process.env.LLM_ROUTER_TIMEOUT_MS || 120000),
      headers: { "content-type": "application/json" },
    });
    const upstream = result.response;
    res.set("X-LLM-Route", result.route);
    res.set("X-LLM-Fallback", result.fallback ? "direct" : "none");
    const routedVia = upstream?.headers?.["x-routed-via"];
    const attempts = upstream?.headers?.["x-fallback-attempts"];
    if (routedVia) res.set("X-Routed-Via", String(routedVia));
    if (attempts) res.set("X-Fallback-Attempts", String(attempts));
    res.status(Number(upstream?.status || 200)).json(upstream?.data ?? {});
  } catch (error) {
    const status = Number(error?.response?.status || 502);
    const data = error?.response?.data;
    res.status(status >= 400 && status < 600 ? status : 502).json({
      error: {
        message: String(data?.error?.message || data?.message || error?.message || error).slice(0, 1000),
        type: "llm_gateway_error",
        router: routingStatus(),
      },
    });
  }
}

app.post("/v1/chat/completions", (req, res) => proxy("chat", req, res));
app.post("/v1/responses", (req, res) => proxy("responses", req, res));
app.post("/v1/messages", (req, res) => proxy("messages", req, res));

app.listen(port, "0.0.0.0", () => {
  console.log(`[llm-gateway] listening on :${port} mode=${routingStatus().mode}`);
});
