// One action of a code flow at a time (D33): the picker and the view of what one entry point reaches.
import type { FlowAction, FlowView } from "../api/types";
import { took } from "../checks/Health";

/** One action of a code flow (D33): what its start reaches, with its own times, critical path and advice. Laid out
 * fresh: the saved layout is for the whole flow. */
export function only(flow: FlowView, a: FlowAction): FlowView {
  // steps you added stay in view, so you can connect and edit them (they reach nothing yet)
  const keep = new Set([a.id, ...flow.nodes.filter((n) => n.added_by === "user").map((n) => n.id)]);
  for (let grew = true; grew;) {
    grew = false;
    for (const e of flow.edges) if (keep.has(e.source) && !keep.has(e.target)) { keep.add(e.target); grew = true; }
  }
  const onPath = new Set(a.path);
  const pathEdges = new Set(a.path.slice(1).map((id, i) => `${a.path[i]}>${id}`));
  const nodes = flow.nodes.filter((n) => keep.has(n.id)).map((n) => ({ ...n, on_critical_path: onPath.has(n.id) }));
  const slowest = nodes.filter((n) => onPath.has(n.id)).sort((x, y) => (y.estimate_ms ?? 0) - (x.estimate_ms ?? 0))[0];
  return {
    ...flow, nodes, positions: {},
    edges: flow.edges.filter((e) => keep.has(e.source) && keep.has(e.target))
      .map((e) => ({ ...e, on_critical_path: pathEdges.has(`${e.source}>${e.target}`) })),
    critical_path: { path: a.path, length_ms: a.could_ms, bottleneck: slowest?.id ?? null },
    written_ms: a.written_ms, advice: (flow.advice ?? []).filter((x) => x.nodes.every((id) => keep.has(id))),
  };
}

/** Which action the flow shows: every entry point, slowest first, with its time (D33). */
export function ActionPicker({ actions, value, onChange }: { actions: FlowAction[]; value: string | null; onChange: (id: string) => void }) {
  return (
    <label className="fm-action">
      <span>Action</span>
      <select value={value ?? ""} onChange={(e) => onChange(e.target.value)}>
        {actions.map((a) => <option key={a.id} value={a.id}>{a.title} · {took(a.written_ms)}</option>)}
      </select>
    </label>
  );
}
