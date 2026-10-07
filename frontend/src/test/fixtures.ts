import type { Connector, Health, RunSummary, Savings } from "../api/types";

export function connector(over: Partial<Connector> & Pick<Connector, "id" | "type" | "name">): Connector {
  return {
    role: "", slot: null, style: { color: null, logo: { type: "letters", text: over.name.slice(0, 2) } }, connection: {}, secret_ref: null,
    secret: null, mode: null, rate_limit_rpm: null, data_sent: "all", fallback: null, managed_by: "app",
    deletable: true, is_default: false, ...over,
  };
}

export const CONNECTORS: Connector[] = [
  connector({ id: "razorpay", type: "http", name: "Razorpay", role: "payments", mode: "test",
    connection: { base_url: "https://api.razorpay.com/v1" }, secret_ref: "env:RAZORPAY_KEY",
    secret: { ref: "env:RAZORPAY_KEY", status: "example" } }),
  connector({ id: "gemini", type: "llm", name: "Gemini", role: "reasoning",
    connection: { provider: "openai_compatible", base_url: "https://generativelanguage.googleapis.com/v1beta/openai/", model: "m" } }),
  connector({ id: "sirius", type: "local", name: "Sirius", role: "security scan", style: { color: "#0B7A70", logo: { type: "letters", text: "Si" } } }),
  connector({ id: "nim", type: "llm", name: "NVIDIA NIM", role: "free hosted models", is_default: true, deletable: false,
    connection: { provider: "openai_compatible", base_url: "https://integrate.api.nvidia.com/v1", model: "m" } }),
];

export const HEALTH: Health[] = [
  { id: "razorpay", name: "Razorpay", type: "http", status: "ok", label: "OK, 2 min ago", last_ok: "2026-10-07T10:00:00Z",
    last_failure: null, last_error: null, rate: { rpm: 60, used_last_minute: 2, left: 58 }, last_test: null },
  { id: "gemini", name: "Gemini", type: "llm", status: "missing_key", label: "Key missing", last_ok: null,
    last_failure: null, last_error: null, rate: null, last_test: null },
  { id: "sirius", name: "Sirius", type: "local", status: "failing", label: "Failed 5 min ago", last_ok: null,
    last_failure: "2026-10-07T10:00:00Z", last_error: "local 'sirius': exit code 2: scan crashed", rate: null, last_test: null },
  { id: "nim", name: "NVIDIA NIM", type: "llm", status: "idle", label: "Not used yet", last_ok: null, last_failure: null,
    last_error: null, rate: { rpm: 40, used_last_minute: 9, left: 31 }, last_test: null },
];

export const SAVINGS: Savings = { runs: 5, time_saved_ms: 9400, calls_skipped: 12, api_calls: 40, tokens: 4210, credits: 0 };

export function run(over: Partial<RunSummary> & Pick<RunSummary, "id" | "status">): RunSummary {
  return {
    plan: "Nightly finance check", workflow_id: "nightly", policy: "critical_path", started_at: "2026-10-07T09:12:00Z",
    finished_at: "2026-10-07T09:12:09Z", time_ms: 9200, api_calls: 6, cache_hits: 1, tokens: 1040, credits: 0,
    work_ms: 16000, failure_reason: null, connectors: ["sirius", "razorpay"], ...over,
  };
}
