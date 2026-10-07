import { expect, test } from "vitest";
import type { OutlineStep, RunEvent } from "../api/types";
import { buildTimeline, narrate, niceCeil } from "./timeline";

const OUTLINE: OutlineStep[] = [
  { id: "scan", title: "Scan code", type: "local", connector: "sirius", depends_on: [] },
  { id: "pay", title: "Fetch payments", type: "http", connector: "razorpay", depends_on: [] },
  { id: "sum", title: "Write summary", type: "llm", connector: "gemini", depends_on: ["scan", "pay"] },
];

const STARTED: RunEvent = {
  type: "run", t: 0, state: "started", predicted_critical_path: ["scan", "sum"], predicted_critical_path_ms: 9000,
  ...({ estimates: { scan: 6000, pay: 1000, sum: 3000 } } as object),
} as RunEvent;

test("a live run: done, running and expected bars, with the critical path marked", () => {
  const events: RunEvent[] = [
    STARTED,
    { type: "step", t: 0, step_id: "scan", state: "running" },
    { type: "step", t: 0, step_id: "pay", state: "running" },
    { type: "step", t: 1, step_id: "pay", state: "succeeded", cache_hit: false,
      ...({ output: { usage: { prompt_tokens: 10, completion_tokens: 5 } } } as object) } as RunEvent,
  ];
  const tl = buildTimeline(OUTLINE, events, null, 2);
  const [scan, pay, sum] = tl.rows;
  expect(scan).toMatchObject({ state: "running", start: 0, end: null, critical: true });
  expect(pay).toMatchObject({ state: "succeeded", start: 0, end: 1, critical: false });
  // "sum" waits for scan, which is still running: expected after now, for its 3 s estimate
  expect(sum).toMatchObject({ state: "pending", expectedStart: 2, expectedEnd: 5, critical: true });
  expect(tl.predictedMs).toBe(9000);
  expect(tl.scaleS).toBe(10);
  expect(tl.tokens).toBe(15);
  expect(tl.calls).toBe(1);
});

test("the final result wins, and the actual critical path replaces the predicted one", () => {
  const result = {
    workflow_id: "w", policy: "critical_path", status: "succeeded" as const, makespan_ms: 4000, api_calls: 3, cache_hits: 1,
    predicted_critical_path: ["scan", "sum"], predicted_critical_path_ms: 9000,
    actual_critical_path: ["pay", "sum"], actual_critical_path_ms: 4000,
    steps: {
      scan: { step_id: "scan", state: "succeeded" as const, output: null, error: null, attempts: 1, cache_hit: false, started_at: 0, finished_at: 1, call_ms: 1, answered_by: "sirius" },
      pay: { step_id: "pay", state: "succeeded" as const, output: null, error: null, attempts: 1, cache_hit: true, started_at: 0, finished_at: 3, call_ms: 3, answered_by: "razorpay" },
      sum: { step_id: "sum", state: "succeeded" as const, output: null, error: null, attempts: 1, cache_hit: false, started_at: 3, finished_at: 4, call_ms: 1, answered_by: "gemini" },
    },
  };
  const tl = buildTimeline(OUTLINE, [STARTED], result, 4);
  expect(tl.rows.map((r) => r.critical)).toEqual([false, true, true]);
  expect(tl.rows[1]).toMatchObject({ cacheHit: true, end: 3 });
  expect(tl.cacheHits).toBe(1);
});

test("event log in plain words", () => {
  const events: RunEvent[] = [
    STARTED,
    { type: "step", t: 0, step_id: "scan", state: "running" },
    { type: "step", t: 0, step_id: "pay", state: "running" },
    { type: "retry", t: 0.5, step_id: "pay", attempt: 1, error: "HTTP 503", delay_s: 1.2 },
    { type: "step", t: 2, step_id: "pay", state: "succeeded", cache_hit: true },
    { type: "step", t: 6, step_id: "scan", state: "failed", error: "exit code 2" },
    { type: "step", t: 6, step_id: "sum", state: "skipped", reason: "upstream 'scan' failed" },
    { type: "run", t: 6, state: "failed" },
    { type: "end" },
  ];
  expect(narrate(OUTLINE, events).map((l) => `${l.t.toFixed(1)}s ${l.text}`)).toEqual([
    "0.0s 1, 2 started together",
    "0.5s 2 retrying in 1.2s: HTTP 503",
    "2.0s 2 answered from cache",
    "6.0s 1 failed: exit code 2",
    "6.0s 3 skipped (an earlier step failed)",
    "6.0s run finished with a failure",
  ]);
});

test("axis rounds up to tidy seconds", () => {
  expect([niceCeil(0.3), niceCeil(7), niceCeil(9.2), niceCeil(11), niceCeil(700)]).toEqual([0.5, 10, 10, 15, 720]);
});
