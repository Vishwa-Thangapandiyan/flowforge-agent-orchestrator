// The test-run replay (D17): a traced test order played back on the map. Pure functions, no timers.
import type { FlowEdge, FlowNode, Trace, TraceStep } from "../api/types";

export type NodeState = "idle" | "running" | "retry" | "ok" | "failed" | "cached" | "waiting" | "skipped";
export type EdgeState = "idle" | "active" | "done" | "skipped";

export interface Replay {
  steps: Map<string, TraceStep>;
  /** when a block that never ran counts as "not taken": the moment the last way into it was decided */
  skipAt: Map<string, number>;
  gate: TraceStep | null;
  end: number;
  nodes: FlowNode[];
  edges: FlowEdge[];
  branches: Record<string, string>;
}

const CALL_KINDS = new Set(["llm", "api", "mcp", "local"]);
const endOf = (s: TraceStep) => s.start_ms + s.duration_ms;

export function buildReplay(nodes: FlowNode[], edges: FlowEdge[], trace: Trace): Replay {
  const ids = new Set(nodes.map((n) => n.id));
  const steps = new Map(trace.steps.filter((s) => ids.has(s.node)).map((s) => [s.node, s]));
  const end = Math.max(0, ...[...steps.values()].map(endOf));
  const gate = [...steps.values()].find((s) => s.outcome === "waiting") ?? null;
  const skipAt = new Map<string, number>();
  // a block with no trace step is decided once every block feeding it has finished or been skipped
  for (let pass = 0; pass < nodes.length; pass++) {
    let changed = false;
    for (const n of nodes) {
      if (steps.has(n.id) || skipAt.has(n.id)) continue;
      const ins = edges.filter((e) => e.target === n.id && e.kind !== "retry");
      const times = ins.map((e) => (steps.has(e.source) ? endOf(steps.get(e.source)!) : skipAt.get(e.source)));
      if (ins.length === 0) skipAt.set(n.id, 0);
      else if (times.every((t) => t !== undefined)) skipAt.set(n.id, Math.max(...(times as number[])));
      else continue;
      changed = true;
    }
    if (!changed) break;
  }
  for (const n of nodes) if (!steps.has(n.id) && !skipAt.has(n.id)) skipAt.set(n.id, end);
  return { steps, skipAt, gate, end, nodes, edges, branches: trace.branches };
}

/** Whether a line carried data in this trace. */
export function taken(r: Replay, e: FlowEdge): boolean {
  const a = r.steps.get(e.source);
  const b = r.steps.get(e.target);
  if (!a || !b || e.kind === "unconfirmed" || e.kind === "retry") return false;
  if (e.kind === "fallback") return a.outcome === "failed";
  if (a.outcome === "failed") return false;
  if (e.kind === "branch") return r.branches[e.source] === e.when;
  return b.start_ms >= endOf(a) - 1;
}

export interface Frame {
  t: number;
  nodes: Record<string, NodeState>;
  edges: Record<string, EdgeState>;
  caps: Record<string, string>;
  waiting: string | null;
  done: boolean;
  calls: number;
  cached: number;
  tokens: number;
}

const secs = (ms: number) => `${(ms / 1000).toFixed(1)} s`;

/** The map at time `t`. The clock stops at a gate until `approved`; `rejected` skips everything after it. */
export function frameAt(r: Replay, t: number, approved = false, rejected = false): Frame {
  const gateAt = r.gate ? r.gate.start_ms : Infinity;
  const paused = r.gate !== null && !approved && !rejected && t >= gateAt;
  const now = paused ? gateAt : t;
  const nodes: Record<string, NodeState> = {};
  const caps: Record<string, string> = {};
  let calls = 0;
  let cached = 0;
  let tokens = 0;
  const kind = new Map(r.nodes.map((n) => [n.id, n.kind]));

  for (const n of r.nodes) {
    const s = r.steps.get(n.id);
    const afterRejectedGate = rejected && r.gate !== null && s !== undefined && s.start_ms > gateAt;
    if (!s || afterRejectedGate) {
      const at = afterRejectedGate ? gateAt : r.skipAt.get(n.id) ?? r.end;
      const heldByGate = r.gate !== null && !approved && !rejected && at >= gateAt;  // decided only after the gate
      nodes[n.id] = !heldByGate && now >= at && (at > 0 || now > 0) ? "skipped" : "idle";
      if (nodes[n.id] === "skipped") caps[n.id] = n.status === "unconfirmed" ? "not run · unconfirmed" : "not taken";
      continue;
    }
    if (s.outcome === "waiting") {
      if (now < s.start_ms) nodes[n.id] = "idle";
      else if (rejected) { nodes[n.id] = "failed"; caps[n.id] = "rejected by you"; }
      else if (approved) { nodes[n.id] = "ok"; caps[n.id] = "approved"; }
      else { nodes[n.id] = "waiting"; caps[n.id] = "waiting for you"; }
      continue;
    }
    if (now < s.start_ms) { nodes[n.id] = "idle"; continue; }
    if (now < endOf(s)) {
      const p = s.duration_ms ? (now - s.start_ms) / s.duration_ms : 1;
      nodes[n.id] = s.attempts > 1 && p > 0.35 && p < 0.6 ? "retry" : "running";
      caps[n.id] = nodes[n.id] === "retry" ? s.note ?? "retrying" : "running…";
      continue;
    }
    nodes[n.id] = s.outcome === "cached" ? "cached" : s.outcome === "failed" ? "failed" : "ok";
    const timing = kind.get(n.id) === "decision" || kind.get(n.id) === "fork" || kind.get(n.id) === "join" ? "" : secs(s.duration_ms);
    caps[n.id] = [s.outcome === "cached" ? "from cache" : timing, s.outcome === "failed" ? s.note : null].filter(Boolean).join(" · ");
    if (CALL_KINDS.has(kind.get(n.id) ?? "") && s.outcome !== "cached") calls += s.attempts;
    if (s.outcome === "cached") cached += 1;
    tokens += s.tokens;
  }

  const edges: Record<string, EdgeState> = {};
  for (const e of r.edges) {
    const a = r.steps.get(e.source);
    const b = r.steps.get(e.target);
    if (e.kind === "retry") {
      const p = a && a.duration_ms ? (now - a.start_ms) / a.duration_ms : -1;
      edges[e.id] = a && a.attempts > 1 && p > 0.35 && p < 0.6 ? "active" : a && now >= endOf(a) && a.attempts > 1 ? "done" : "idle";
      continue;
    }
    if (rejected && b && b.start_ms > gateAt) { edges[e.id] = now >= gateAt ? "skipped" : "idle"; continue; }
    if (taken(r, e) && a && b) {
      const from = a.outcome === "waiting" ? a.start_ms : endOf(a);
      if (a.outcome === "waiting" && !approved) edges[e.id] = "idle";
      else edges[e.id] = now < from ? "idle" : now < b.start_ms ? "active" : "done";
    } else {
      const decided = a ? (a.outcome === "waiting" ? (approved || rejected ? a.start_ms : Infinity) : endOf(a)) : r.skipAt.get(e.source) ?? r.end;
      edges[e.id] = now >= decided && (decided > 0 || now > 0) ? "skipped" : "idle";
    }
  }

  const done = !paused && now >= r.end;
  return { t: now, nodes, edges, caps, waiting: paused && r.gate ? r.gate.node : null, done, calls, cached, tokens };
}
