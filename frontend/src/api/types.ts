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

// --- the flow map (D17) -------------------------------------------------------------------------------

export type NodeKind = "start" | "end" | "llm" | "api" | "mcp" | "local" | "code" | "decision" | "fork" | "join" | "gate";
export type EdgeKind = "flow" | "branch" | "fallback" | "retry" | "unconfirmed";

export interface Evidence {
  type: "code" | "trace" | "policy" | "env_name" | "user" | "missing";
  ref: string | null;
  text: string | null;
  first_line: number | null;
  lines: string[];
  highlight: number | null;
}

export interface NodeStats {
  p50_ms: number | null;
  summary: string;
  history: { ms: number; ok: boolean }[];
}

export interface FlowNode {
  id: string;
  kind: NodeKind;
  title: string;
  what: string;
  connector: string | null;
  op: { model?: string | null; method?: string | null; path?: string | null; tool?: string | null; read_only?: boolean | null } | null;
  condition: string | null;
  estimate_ms: number | null;
  status: "confirmed" | "unconfirmed";
  added_by: "planner" | "policy" | "user";
  side_effect: boolean;
  evidence: Evidence[];
  // added by GET /flow
  yours: { id: number; op: string }[];
  on_critical_path: boolean;
  stats: NodeStats | null;
  tip: { connector: string; text: string } | null;
  planner_connector: string | null;
}

export interface FlowEdge {
  id: string;
  source: string;
  target: string;
  kind: EdgeKind;
  when: string | null;
  max: number | null;
  on: string | null;
  label: string | null;
  on_critical_path?: boolean;
}

export interface FlowView {
  available: true;
  version: number;
  created_at: string;
  layer: "mine" | "planner";
  fact_sheet_hash: string;
  nodes: FlowNode[];
  edges: FlowEdge[];
  hidden: { id: string; title: string; override: number }[];
  critical_path: { path: string[]; length_ms: number; bottleneck: string | null };
  positions: Record<string, [number, number]>;
  apps: Record<string, { name: string; type: ConnectorType; model: string | null }>;
  counts: { steps: number; unconfirmed: number; gates: number; edits: number };
  pending: number | null;
}

export type FlowResponse = FlowView | { available: false; message: string };

export interface TraceStep {
  node: string;
  start_ms: number;
  duration_ms: number;
  outcome: "ok" | "failed" | "cached" | "waiting";
  answered_by: string | null;
  note: string | null;
  attempts: number;
  tokens: number;
}

export interface Trace {
  label: string;
  steps: TraceStep[];
  branches: Record<string, string>;
  calls: number;
  cached: number;
}

export interface Analysis {
  stages: { title: string; done: string; doing: string; duration_ms: number }[];
  log: [number, string, string][];
  files: string[];
  calls: { app: string; count: number; meta: string; none?: boolean }[];
  dropped: { title: string; reason: string }[];
  notes: Record<string, string>;
  version: number;
  fact_sheet_hash: string;
}

export interface Change {
  id: string;
  type: "add" | "change" | "remove" | "conflict" | "kept";
  title: string;
  detail: string;
  nodes: string[];
  evidence: string;
  choices?: [string, string][];
}

export interface PendingVersion {
  version: number;
  base_version: number | null;
  created_at: string;
  fact_sheet_hash: string;
  changes: Change[];
  default_take: Record<string, boolean | string>;
  nodes: FlowNode[];
  edges: FlowEdge[];
}

export interface CatalogItem {
  id: string;
  name: string;
  category: string;
  type: ConnectorType;
  kind: string;
  live: boolean;
  description: string;
  meta: string;
  status: "on_map" | "connected" | "none";
  color?: string | null;
}

export interface Catalog {
  categories: Record<string, string>;
  items: CatalogItem[];
  own: CatalogItem[];
}

export interface MockTest {
  id: string;
  name: string;
  mock: boolean;
  mode: string;
  steps: { title: string; text: string }[];
  result: string;
  stats: string;
  learns: string[];
}
