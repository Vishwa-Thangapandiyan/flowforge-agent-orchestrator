// A small flow map for tests: a webhook, an API read, a decision, an LLM with a fallback, a gate before an
// email, an unconfirmed SMS step, and a traced test order that falls back, waits at the gate and finishes.
import type { Catalog, CheckPlan, ChecksView, Evidence, FlowEdge, FlowNode, FlowView, PendingVersion, Trace } from "../api/types";

const code = (ref: string): Evidence => ({ type: "code", ref, text: null, first_line: 10, lines: ["def f():", "    call()"], highlight: 11 });

function node(id: string, kind: FlowNode["kind"], title: string, extra: Partial<FlowNode> = {}): FlowNode {
  return {
    id, kind, title, what: `${title}.`, connector: null, op: null, condition: null, estimate_ms: null, status: "confirmed",
    added_by: "planner", side_effect: false, evidence: [code(`app/${id}.py:11`)], yours: [], on_critical_path: false, stats: null,
    tip: null, planner_connector: null, ...extra,
  };
}

function edge(source: string, target: string, kind: FlowEdge["kind"] = "flow", extra: Partial<FlowEdge> = {}): FlowEdge {
  return { id: `${source}__${target}`, source, target, kind, when: null, max: null, on: null, label: null, ...extra };
}

export const NODES: FlowNode[] = [
  node("start", "start", "Payment captured", { connector: "razorpay" }),
  node("fetch", "api", "Fetch order", { connector: "razorpay", op: { method: "GET", path: "/v1/orders/{id}" }, on_critical_path: true }),
  node("risky", "decision", "Risky order?", { condition: "order.amount > 5000" }),
  node("score", "llm", "Score fraud risk", {
    connector: "gemini", planner_connector: "gemini", op: { model: "gemini-2.0-flash" }, estimate_ms: 2100, on_critical_path: true,
    tip: { connector: "nim", text: "NIM answered faster with the same verdict." },
    stats: { p50_ms: 2100, summary: "p50 2.1 s · 2 rate-limited in 40", history: [{ ms: 2000, ok: true }, { ms: 2600, ok: false }] },
  }),
  node("score_nim", "llm", "Score fraud risk", { connector: "nim", planner_connector: "nim", op: { model: "llama" } }),
  node("gate_send", "gate", "Send to customer", { evidence: [{ type: "policy", ref: null, text: "Side effects always wait for you.", first_line: null, lines: [], highlight: null }] }),
  node("send", "mcp", "Send email", { connector: "gmail", op: { tool: "send_message", read_only: false }, side_effect: true }),
  node("sms", "api", "SMS receipt", {
    connector: "twilio", status: "unconfirmed", side_effect: true,
    evidence: [{ type: "env_name", ref: ".env.example:7", text: "TWILIO_SID (name only)", first_line: null, lines: [], highlight: null }],
  }),
  node("end", "end", "Order done"),
];

export const EDGES: FlowEdge[] = [
  edge("start", "fetch"), edge("fetch", "risky"), edge("risky", "score", "branch", { when: "yes" }), edge("risky", "end", "branch", { when: "no" }),
  edge("score", "score_nim", "fallback", { on: "if Gemini fails" }), edge("score", "gate_send"), edge("score_nim", "gate_send"),
  edge("gate_send", "send"), edge("send", "end"), edge("fetch", "sms", "unconfirmed"),
];

export const FLOW: FlowView = {
  available: true, kind: "flow", version: 1, created_at: "2026-10-09T10:00:00Z", layer: "mine", fact_sheet_hash: "sha256:abc",
  nodes: NODES, edges: EDGES, hidden: [],
  critical_path: { path: ["start", "fetch", "risky", "score", "gate_send", "send", "end"], length_ms: 2700, bottleneck: "score" },
  positions: {}, counts: { steps: NODES.length, unconfirmed: 1, gates: 1, edits: 0 }, pending: null,
  apps: {
    razorpay: { name: "Razorpay", type: "http", model: null }, gemini: { name: "Gemini", type: "llm", model: "gemini-3.8-flash" },
    nim: { name: "NVIDIA NIM", type: "llm", model: "llama" }, gmail: { name: "Gmail", type: "mcp", model: null },
  },
};

export const TRACE: Trace = {
  label: "Test order #17", branches: { risky: "yes" }, calls: 6, cached: 0,
  steps: [
    { node: "start", start_ms: 0, duration_ms: 100, outcome: "ok", answered_by: null, note: null, attempts: 1, tokens: 0 },
    { node: "fetch", start_ms: 300, duration_ms: 200, outcome: "ok", answered_by: "razorpay", note: null, attempts: 1, tokens: 0 },
    { node: "risky", start_ms: 700, duration_ms: 50, outcome: "ok", answered_by: null, note: null, attempts: 1, tokens: 0 },
    { node: "score", start_ms: 1000, duration_ms: 1000, outcome: "failed", answered_by: "gemini", note: "429 rate-limited · 3 tries", attempts: 3, tokens: 0 },
    { node: "score_nim", start_ms: 2300, duration_ms: 600, outcome: "ok", answered_by: "nim", note: null, attempts: 1, tokens: 400 },
    { node: "gate_send", start_ms: 3200, duration_ms: 0, outcome: "waiting", answered_by: null, note: null, attempts: 1, tokens: 0 },
    { node: "send", start_ms: 3500, duration_ms: 500, outcome: "ok", answered_by: "gmail", note: null, attempts: 1, tokens: 0 },
    { node: "end", start_ms: 4300, duration_ms: 100, outcome: "ok", answered_by: null, note: null, attempts: 1, tokens: 0 },
  ],
};

export const CATALOG: Catalog = {
  categories: { llm: "LLMs", pay: "Payments", dev: "Dev tools", data: "Data and apps", media: "Media and AI services", custom: "Your own" },
  items: [
    { id: "gemini", name: "Google Gemini", category: "llm", type: "llm", kind: "LLM", live: true, description: "Quick model.", meta: "openai-compatible", status: "on_map" },
    { id: "ollama", name: "Ollama", category: "llm", type: "llm", kind: "LLM", live: true, description: "Local models.", meta: "local", status: "connected" },
    { id: "stripe", name: "Stripe", category: "pay", type: "http", kind: "HTTP API", live: false, description: "Global payments.", meta: "HTTP", status: "none" },
    { id: "higgsfield", name: "Higgsfield", category: "media", type: "http", kind: "HTTP API", live: false, description: "Images and video.", meta: "HTTP · demo", status: "none" },
  ],
  own: [{ id: "inventory", name: "Inventory API", category: "custom", type: "http", kind: "HTTP API", live: true, description: "Stock levels.", meta: "HTTP · yours", status: "connected", color: "#2F6FD6" }],
};

export const PENDING: PendingVersion = {
  version: 2, base_version: 1, created_at: "2026-10-09T11:00:00Z", fact_sheet_hash: "sha256:def",
  changes: [
    { id: "c1", type: "add", title: "New: Refund received", detail: "A new route.", nodes: ["r_start"], evidence: "api/webhooks.py:58" },
    { id: "c2", type: "conflict", title: "Score fraud risk: model changed", detail: "You moved this step.", nodes: ["score"], evidence: "config/llm.py:9",
      choices: [["mine", "Keep your edit"], ["planner", "Use the Planner's"]] },
    { id: "c3", type: "remove", title: 'Drop "SMS receipt"', detail: "Still no call site.", nodes: ["sms"], evidence: ".env.example:7" },
  ],
  default_take: { c1: true, c2: "mine", c3: true },
  nodes: [...NODES.filter((n) => n.id !== "sms"), node("r_start", "start", "Refund received", { connector: "razorpay" })],
  edges: EDGES.filter((e) => e.target !== "sms"),
};

// A dependency map from a scan (D21): the app, an LLM, two APIs (one reached through an MCP server), a coding-tool server.
export const DEPS: FlowView = {
  available: true, kind: "dependencies", version: 1, created_at: "2026-10-21T10:00:00Z", layer: "mine", fact_sheet_hash: "sha256:dep",
  nodes: [
    node("app", "start", "trip-planner", { evidence: [{ type: "code", ref: null, text: "11 files read.", first_line: null, lines: [], highlight: null }] }),
    node("tools", "start", "Your coding tools"),
    node("llm-ollama", "llm", "Ollama", { catalog: "ollama", op: { model: "llama3.1:8b" }, what: "localhost:11434" }),
    node("api-nominatim", "api", "Nominatim", { catalog: "nominatim", what: "https://nominatim.openstreetmap.org/search" }),
    node("mcp-fetch", "mcp", "fetch", { what: "uvx mcp-server-fetch" }),
    node("api-wikipedia", "api", "Wikipedia", { catalog: "wikipedia", what: "https://en.wikipedia.org/wiki/" }),
    node("api-www-mysite-test", "api", "www.mysite.test", { status: "unconfirmed", what: "https://www.mysite.test/about" }),
    node("mcp-github", "mcp", "github", { what: "npx github-mcp" }),
  ],
  edges: [edge("app", "llm-ollama"), edge("app", "api-nominatim"), edge("app", "mcp-fetch"), edge("mcp-fetch", "api-wikipedia"),
    edge("app", "api-www-mysite-test", "unconfirmed"), edge("tools", "mcp-github")],
  hidden: [], critical_path: { path: [], length_ms: 0, bottleneck: null }, positions: {}, apps: {},
  counts: { steps: 8, unconfirmed: 1, gates: 0, edits: 0 }, pending: null,
};

// Check results for DEPS (D24): Ollama down with a fix, fetch slow, the rest up, the unconfirmed link not checked.
export const CHECKS: ChecksView = {
  run_id: "chk1", checked_at: "2026-10-21T10:44:00Z", example: false,
  summary: { up: 3, warn: 1, down: 1, skipped: 0, unchecked: 0, unconfirmed: 1 },
  items: [
    { id: "llm-ollama", name: "Ollama", kind: "llm", catalog: "ollama", status: "down", latency_ms: null,
      summary: "Nothing answers at localhost:11434", reason: "[Errno 111] Connection refused",
      fix: "Start Ollama (`ollama serve`).", at: "2026-10-21T10:44:00Z", history: ["up", "up", "down"] },
    { id: "api-nominatim", name: "Nominatim", kind: "api", catalog: "nominatim", status: "up", latency_ms: 420,
      summary: "Up", at: "2026-10-21T10:44:00Z", history: ["up", "up", "up"] },
    { id: "mcp-fetch", name: "fetch", kind: "mcp", status: "warn", latency_ms: 6800,
      summary: "Up: 1 tool, but slow to start: 6.8 s", at: "2026-10-21T10:44:00Z", history: ["up", "warn"] },
    { id: "api-wikipedia", name: "Wikipedia", kind: "api", catalog: "wikipedia", status: "up", latency_ms: 310,
      summary: "Up", at: "2026-10-21T10:44:00Z", history: ["up"] },
    { id: "api-www-mysite-test", name: "www.mysite.test", kind: "api", status: "unconfirmed",
      summary: "Not checked: unconfirmed", history: [] },
    { id: "mcp-github", name: "github", kind: "mcp", status: "up", latency_ms: 2100, summary: "Up: 26 tools",
      at: "2026-10-21T10:44:00Z", history: ["up", "up"] },
  ],
};

export const PLAN: CheckPlan = {
  checks: 5, kinds: { llm: 1, api: 2, mcp: 2, local: 0 }, confirmed: false, example: false,
  starts: [
    { id: "mcp-fetch", name: "fetch", command: "uvx mcp-server-fetch", origin: "downloads from PyPI, any version", source: ".mcp.json:7" },
    { id: "mcp-github", name: "github", command: "npx github-mcp", origin: "downloads from npm, any version", source: ".cursor/mcp.json:3" },
  ],
};

// A flow read from code (D25): the city lookup, a check that stops early, two calls that could start together.
const step = (id: string, kind: "api" | "mcp" | "llm", title: string, what: string, ref: string, ms: number,
  source: "measured" | "estimate" = "measured"): FlowNode =>
  node(id, kind, title, { what, catalog: null, estimate_ms: ms, estimate_source: source, evidence: [code(ref)] });

export const CODEFLOW: FlowView = {
  available: true, kind: "flow", source: "code", version: 1, created_at: "2026-10-21T10:00:00Z", layer: "mine",
  fact_sheet_hash: "sha256:code",
  nodes: [
    node("start-plan", "start", "plan()", { evidence: [code("planner.py:48")] }),
    step("api-nominatim-1", "api", "Nominatim", "find the city", "planner.py:52", 420),
    node("if-1", "decision", "place is None?", { condition: "place is None", evidence: [code("planner.py:53")] }),
    node("stop-1", "end", "Stop", { evidence: [code("planner.py:55")] }),
    step("api-open-meteo-1", "api", "Open-Meteo", "today's weather", "planner.py:60", 180),
    step("mcp-fetch-1", "mcp", "fetch", "about the city", "planner.py:66", 6800),
    step("llm-ollama-1", "llm", "Ollama", "write the plan", "planner.py:88", 2000, "estimate"),
  ],
  edges: [edge("start-plan", "api-nominatim-1"), edge("api-nominatim-1", "if-1"),
    { ...edge("if-1", "stop-1", "branch"), when: "yes" }, { ...edge("if-1", "api-open-meteo-1", "branch"), when: "no" },
    { ...edge("if-1", "mcp-fetch-1", "branch"), when: "no" }, edge("api-open-meteo-1", "llm-ollama-1"),
    edge("mcp-fetch-1", "llm-ollama-1")],
  hidden: [], positions: {}, apps: {},
  critical_path: { path: ["start-plan", "api-nominatim-1", "if-1", "mcp-fetch-1", "llm-ollama-1"], length_ms: 9220, bottleneck: "mcp-fetch-1" },
  counts: { steps: 7, unconfirmed: 0, gates: 0, edits: 0 }, pending: null,
  written_ms: 9400,
  advice: [{ nodes: ["api-open-meteo-1", "mcp-fetch-1"], refs: ["planner.py:60", "planner.py:66"], saved_ms: 180,
    text: "None of these uses another's result: start them together with asyncio.gather.",
    caveat: "fetch only need what was known before the check at planner.py:53, so they could start even earlier, but when the code stops there, those calls are wasted." }],
};
