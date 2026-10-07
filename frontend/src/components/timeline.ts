// Turns a run's outline + events (+ final result) into "who ran when" rows and an event log.
import type { OutlineStep, RunEvent, RunResult, StepState } from "../api/types";

export interface Row {
  id: string;
  n: number; // 1-based position in the plan
  title: string;
  type: string;
  connector: string | null;
  state: StepState;
  start: number | null; // seconds from run start
  end: number | null;
  /** where a step that hasn't started is expected to sit (dashed) */
  expectedStart: number | null;
  expectedEnd: number | null;
  cacheHit: boolean;
  critical: boolean;
  error: string | null;
  output: unknown;
}

export interface Timeline {
  rows: Row[];
  predictedMs: number | null;
  scaleS: number; // the axis length in seconds
  criticalPath: string[];
  tokens: number;
  calls: number;
  cacheHits: number;
}

function tokensOf(output: unknown): number {
  const usage = (output as { usage?: { prompt_tokens?: number; completion_tokens?: number } } | null)?.usage;
  return usage ? (usage.prompt_tokens ?? 0) + (usage.completion_tokens ?? 0) : 0;
}

export function buildTimeline(outline: OutlineStep[], events: RunEvent[], result: RunResult | null, nowS: number): Timeline {
  const rows = new Map<string, Row>(
    outline.map((s, i) => [s.id, {
      id: s.id, n: i + 1, title: s.title, type: s.type, connector: s.connector, state: "pending" as StepState,
      start: null, end: null, expectedStart: null, expectedEnd: null, cacheHit: false, critical: false, error: null,
      output: undefined,
    }]),
  );
  let predictedMs: number | null = null;
  let estimates: Record<string, number> = {};
  let criticalPath: string[] = [];

  for (const e of events) {
    if (e.type === "run" && e.state === "started") {
      predictedMs = e.predicted_critical_path_ms ?? null;
      criticalPath = e.predicted_critical_path ?? [];
      estimates = e.estimates ?? {};
    } else if (e.type === "run" && e.actual_critical_path) {
      criticalPath = e.actual_critical_path;
    } else if (e.type === "step") {
      const row = rows.get(e.step_id);
      if (!row) continue;
      row.state = e.state;
      if (e.state === "running") row.start = e.t;
      if (e.state === "succeeded" || e.state === "failed") {
        row.end = e.t;
        if (row.start === null) row.start = e.t;
        row.cacheHit = !!e.cache_hit;
        row.error = e.error ?? null;
        row.output = e.output;
      }
      if (e.state === "skipped") row.error = e.reason ?? null;
    }
  }

  // the final result is the source of truth once the run is over
  if (result) {
    criticalPath = result.actual_critical_path;
    for (const step of Object.values(result.steps)) {
      const row = rows.get(step.step_id);
      if (!row) continue;
      row.state = step.state;
      row.start = step.started_at;
      row.end = step.finished_at;
      row.cacheHit = step.cache_hit;
      row.error = step.error ?? row.error;
      row.output = step.output ?? row.output;
    }
  }

  // expected placement for steps not started yet: after their dependencies, for their estimate
  const finish = new Map<string, number>();
  for (const s of outline) {
    const row = rows.get(s.id)!;
    if (row.start !== null) {
      finish.set(s.id, row.end ?? Math.max(nowS, row.start));
      continue;
    }
    if (row.state === "skipped") continue;
    const after = Math.max(nowS, ...s.depends_on.map((d) => finish.get(d) ?? nowS));
    row.expectedStart = after;
    row.expectedEnd = after + (estimates[s.id] ?? 0) / 1000;
    finish.set(s.id, row.expectedEnd);
  }

  const critical = new Set(criticalPath);
  const list = [...rows.values()].map((r) => ({ ...r, critical: critical.has(r.id) }));
  const furthest = Math.max(
    nowS, (predictedMs ?? 0) / 1000,
    ...list.map((r) => Math.max(r.end ?? 0, r.expectedEnd ?? 0, r.start ?? 0)),
  );
  return {
    rows: list,
    predictedMs,
    scaleS: niceCeil(Math.max(furthest, 0.5)),
    criticalPath,
    tokens: list.filter((r) => !r.cacheHit).reduce((sum, r) => sum + tokensOf(r.output), 0),
    calls: list.filter((r) => (r.state === "succeeded" || r.state === "failed") && !r.cacheHit).length,
    cacheHits: list.filter((r) => r.cacheHit).length,
  };
}

/** Round the axis up to a tidy number of seconds. */
export function niceCeil(seconds: number): number {
  const steps = [0.5, 1, 2, 2.5, 5, 10, 15, 20, 30, 60, 90, 120, 180, 300, 600];
  return steps.find((s) => s >= seconds) ?? Math.ceil(seconds / 60) * 60;
}

/** Plain-words event log: "0.0s  1, 2, 3 started together". */
export function narrate(outline: OutlineStep[], events: RunEvent[]): { t: number; text: string; tone?: string }[] {
  const num = new Map(outline.map((s, i) => [s.id, i + 1]));
  const n = (id: string) => String(num.get(id) ?? id);
  const groups = new Map<string, { t: number; started: string[]; done: string[]; cached: string[]; other: { text: string; tone?: string }[] }>();
  const at = (t: number) => {
    const key = t.toFixed(1);
    if (!groups.has(key)) groups.set(key, { t, started: [], done: [], cached: [], other: [] });
    return groups.get(key)!;
  };
  for (const e of events) {
    if (e.type === "end") continue;
    const t = "t" in e && typeof e.t === "number" ? e.t : 0;
    if (e.type === "step") {
      if (e.state === "running") at(t).started.push(n(e.step_id));
      else if (e.state === "succeeded") (e.cache_hit ? at(t).cached : at(t).done).push(n(e.step_id));
      else if (e.state === "failed") at(t).other.push({ text: `${n(e.step_id)} failed: ${e.error ?? "unknown error"}`, tone: "coral" });
      else if (e.state === "skipped") at(t).other.push({ text: `${n(e.step_id)} skipped (an earlier step failed)`, tone: "slate" });
    } else if (e.type === "retry") {
      at(t).other.push({ text: `${n(e.step_id)} retrying in ${e.delay_s.toFixed(1)}s: ${e.error}`, tone: "amber" });
    } else if (e.type === "fallback") {
      at(t).other.push({ text: `${n(e.step_id)} switched from ${e.from} to ${e.to}`, tone: "violet" });
    } else if (e.type === "run" && e.state !== "started") {
      const words: Record<string, string> = { succeeded: "run finished", failed: "run finished with a failure", stopped: "stopped by you", interrupted: "interrupted", error: "the engine hit an error" };
      at(t).other.push({ text: words[e.state] ?? e.state, tone: e.state === "succeeded" ? "teal" : e.state === "failed" || e.state === "error" ? "coral" : "slate" });
    }
  }
  const list = (ids: string[]) => [...ids].sort((a, b) => Number(a) - Number(b) || a.localeCompare(b)).join(", ");
  const lines: { t: number; text: string; tone?: string }[] = [];
  for (const g of [...groups.values()].sort((a, b) => a.t - b.t)) {
    const parts: string[] = [];
    if (g.done.length) parts.push(`${list(g.done)} done`);
    if (g.cached.length) parts.push(`${list(g.cached)} answered from cache`);
    if (g.started.length) parts.push(g.started.length > 1 ? `${list(g.started)} started together` : `${g.started[0]} started`);
    if (parts.length) lines.push({ t: g.t, text: parts.join(" · ") });
    for (const o of g.other) lines.push({ t: g.t, ...o });
  }
  return lines;
}
