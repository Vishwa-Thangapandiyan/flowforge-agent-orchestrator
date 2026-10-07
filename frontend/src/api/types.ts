// Shapes returned by the FlowForge API (backend/flowforge/api/*). Secrets are never present:
// a connector only ever carries `secret: { ref, status }`.

export type ConnectorType = "llm" | "mcp" | "http" | "local";
export type Logo = { type: "letters"; text: string } | { type: "upload"; file: string } | { type: "none" };

export interface Connector {
  id: string;
  type: ConnectorType;
  name: string;
  role: string;
  slot: string | null;
  style: { color: string | null; logo: Logo };
  connection: Record<string, unknown>;
  secret_ref: string | null;
  secret: { ref: string; status: "set" | "missing" | "example" } | null;
  mode: "test" | "live" | null;
  rate_limit_rpm: number | null;
  data_sent: "all" | "redacted_only";
  fallback: string | null;
  managed_by: "app" | "file";
  deletable: boolean;
  is_default: boolean;
  logo_url?: string;
}

export interface Preset extends Partial<Omit<Connector, "secret" | "managed_by" | "deletable" | "is_default">> {
  preset: string;
  type: ConnectorType;
}

export interface Health {
  id: string;
  name: string;
  type: ConnectorType;
  status: "ok" | "failing" | "missing_key" | "idle";
  label: string;
  last_ok: string | null;
  last_failure: string | null;
  last_error: string | null;
  rate: { rpm: number; used_last_minute: number; left: number } | null;
  last_test: { ok: boolean; message: string; at: string } | null;
}

export interface Savings {
  runs: number;
  time_saved_ms: number;
  calls_skipped: number;
  api_calls: number;
  tokens: number;
  credits: number;
}

export interface Meta {
  project: string;
  example: boolean;
  version: string;
}

export type RunStatus = "running" | "succeeded" | "failed" | "stopped" | "interrupted" | "error";

export interface RunSummary {
  id: string;
  plan: string;
  workflow_id: string;
  status: RunStatus;
  policy: string;
  started_at: string;
  finished_at: string | null;
  time_ms: number | null;
  api_calls: number | null;
  cache_hits: number | null;
  tokens: number | null;
  credits: number | null;
  work_ms: number | null;
  failure_reason: string | null;
  connectors: string[];
}

export type StepState = "pending" | "ready" | "running" | "succeeded" | "failed" | "skipped";

export interface StepResult {
  step_id: string;
  state: StepState;
  output: unknown;
  error: string | null;
  attempts: number;
  cache_hit: boolean;
  started_at: number | null;
  finished_at: number | null;
  call_ms: number | null;
  answered_by: string | null;
}

export interface RunResult {
  workflow_id: string;
  policy: string;
  status: "succeeded" | "failed";
  makespan_ms: number;
  steps: Record<string, StepResult>;
  predicted_critical_path: string[];
  predicted_critical_path_ms: number;
  actual_critical_path: string[];
  actual_critical_path_ms: number;
  api_calls: number;
  cache_hits: number;
}

export interface OutlineStep {
  id: string;
  title: string;
  type: string;
  connector: string | null;
  depends_on: string[];
}

export interface RunDetail {
  status: RunStatus;
  error: string | null;
  result: RunResult | null;
  summary: RunSummary;
  /** the plan outline: no params (D16) */
  steps: OutlineStep[];
}

export type RunEvent =
  | { type: "run"; t?: number; state: string; workflow_id?: string; policy?: string; predicted_critical_path?: string[];
      predicted_critical_path_ms?: number; estimates?: Record<string, number>; makespan_ms?: number;
      actual_critical_path?: string[]; error?: string }
  | { type: "step"; t: number; step_id: string; state: StepState; cache_hit?: boolean; duration_ms?: number;
      error?: string; reason?: string; output?: unknown }
  | { type: "retry"; t: number; step_id: string; attempt: number; error: string; delay_s: number }
  | { type: "fallback"; t: number; step_id: string; from: string | null; to: string; error: string }
  | { type: "end" };

export interface WorkflowStep {
  id: string;
  type: string;
  connector?: string | null;
  depends_on?: string[];
  description?: string;
  estimated_ms?: number;
  params?: Record<string, unknown>;
}

export interface Workflow {
  id: string;
  name?: string;
  max_concurrency?: number;
  steps: WorkflowStep[];
}

export interface Activity {
  run_id: string;
  plan: string;
  step_id: string;
  title: string;
  state: StepState;
  error: string | null;
  cache_hit: boolean;
  attempts: number;
  duration_ms: number | null;
  at: string;
}

export interface Tool {
  name: string;
  description: string;
  input_schema: Record<string, unknown>;
}
