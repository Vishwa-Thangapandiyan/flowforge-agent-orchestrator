import { expect, test } from "vitest";
import { EDGES, NODES, TRACE } from "../test/flowFixture";
import { buildReplay, frameAt, taken } from "./replay";

const r = buildReplay(NODES, EDGES, TRACE);
const edge = (id: string) => EDGES.find((e) => e.id === id)!;

test("lines carry data only where the trace went", () => {
  expect(taken(r, edge("risky__score"))).toBe(true);            // the yes branch
  expect(taken(r, edge("score__score_nim"))).toBe(true);        // Gemini failed, so the fallback ran
  expect(taken(r, edge("score__gate_send"))).toBe(false);       // a failed call passes nothing on
  expect(taken(r, edge("fetch__sms"))).toBe(false);             // unconfirmed lines never run
  expect(taken(r, edge("risky__end"))).toBe(false);             // the no branch wasn't taken
});

test("blocks light up in order: running, failed with its note, then the fallback", () => {
  expect(frameAt(r, 1200).nodes.score).toBe("running");
  expect(frameAt(r, 1500).nodes.score).toBe("retry");            // its 3 tries show as a retry
  const f = frameAt(r, 2100);
  expect(f.nodes.score).toBe("failed");
  expect(f.caps.score).toContain("429");
  expect(f.edges.score__score_nim).toBe("active");
  expect(frameAt(r, 2500).nodes.score_nim).toBe("running");
  expect(frameAt(r, 600).nodes.sms).toBe("skipped");            // decided once fetch finished
});

test("the clock stops at a gate until you approve", () => {
  const waiting = frameAt(r, 9999);
  expect(waiting.waiting).toBe("gate_send");
  expect(waiting.nodes.gate_send).toBe("waiting");
  expect(waiting.nodes.send).toBe("idle");
  expect(waiting.done).toBe(false);
  const approved = frameAt(r, 9999, true);
  expect(approved.nodes.gate_send).toBe("ok");
  expect(approved.nodes.send).toBe("ok");
  expect(approved.done).toBe(true);
  expect(approved.calls).toBe(6);                                // 1 fetch + 3 tries + 1 fallback + 1 send
  expect(approved.tokens).toBe(400);
});

test("rejecting a gate skips everything after it", () => {
  const f = frameAt(r, 9999, false, true);
  expect(f.nodes.gate_send).toBe("failed");
  expect(f.nodes.send).toBe("skipped");
  expect(f.edges.send__end).toBe("skipped");
  expect(f.done).toBe(true);
});

test("a retried call shows its retry and loop", () => {
  const nodes = [...NODES, { ...NODES[1], id: "stock", title: "Check stock" }];
  const edges = [...EDGES, { id: "stock__stock", source: "stock", target: "stock", kind: "retry" as const, when: null, max: 3, on: "5xx", label: null }];
  const trace = { ...TRACE, steps: [...TRACE.steps, { node: "stock", start_ms: 0, duration_ms: 1000, outcome: "ok" as const, answered_by: null, note: "500 · retried once", attempts: 2, tokens: 0 }] };
  const rr = buildReplay(nodes, edges, trace);
  const f = frameAt(rr, 450);
  expect(f.nodes.stock).toBe("retry");
  expect(f.edges.stock__stock).toBe("active");
});
