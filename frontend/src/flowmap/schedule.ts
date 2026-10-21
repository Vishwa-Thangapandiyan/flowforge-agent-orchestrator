// Watch it run (D26): the "could be" schedule of a flow read from code, as a trace the replay engine (D17) plays.
// Each call starts as early as its inputs allow and lasts its weight (D25). It is a schedule, not a recording.
import type { FlowView, Trace, TraceStep } from "../api/types";
import { earliest } from "./Faster";

export function scheduleTrace(flow: FlowView): Trace {
  const start = earliest(flow);
  const byId = Object.fromEntries(flow.nodes.map((n) => [n.id, n]));
  const branches: Record<string, string> = {};
  for (const n of flow.nodes) {
    if (n.kind !== "decision") continue;
    const out = flow.edges.filter((e) => e.source === n.id && e.kind === "branch" && e.when);
    // carry on to the work: the branch that doesn't stop, when one does
    const go = out.find((e) => byId[e.target]?.kind !== "end") ?? out[0];
    if (go && out.some((e) => byId[e.target]?.kind === "end")) branches[n.id] = go.when!;
  }
  const stopped = new Set(flow.nodes.filter((n) => n.kind === "end").map((n) => n.id));
  const steps: TraceStep[] = flow.nodes.filter((n) => !stopped.has(n.id)).map((n) => {
    const through = n.what.startsWith("through ") ? flow.edges.find((e) => e.target === n.id)?.source : undefined;
    const from = through ?? n.id;   // a block reached through a server runs during that server's call
    return {
      node: n.id, start_ms: start[from] ?? 0, duration_ms: byId[from]?.estimate_ms ?? 0, outcome: "ok", attempts: 1,
      tokens: 0, answered_by: null, note: null,
    };
  });
  return { label: "the could-be schedule, not a recording", steps, branches, calls: steps.length, cached: 0 };
}
