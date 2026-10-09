// A small flow map for tests: a webhook, an API read, a decision, an LLM with a fallback, a gate before an
// email, an unconfirmed SMS step, and a traced test order that falls back, waits at the gate and finishes.
import type { Catalog, Evidence, FlowEdge, FlowNode, FlowView, PendingVersion, Trace } from "../api/types";

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
  available: true, version: 1, created_at: "2026-10-09T10:00:00Z", layer: "mine", fact_sheet_hash: "sha256:abc",
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
