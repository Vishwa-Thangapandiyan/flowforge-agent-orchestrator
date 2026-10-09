// Block sizes and the dagre auto-layout (D18): used for blocks that have no saved position, and by Re-tidy.
import dagre from "@dagrejs/dagre";
import type { FlowEdge, FlowNode, NodeKind } from "../api/types";

export interface Size {
  w: number;
  h: number;
}

const SIZES: Partial<Record<NodeKind, Size>> = {
  start: { w: 176, h: 48 },
  end: { w: 148, h: 48 },
  decision: { w: 144, h: 88 },
  fork: { w: 12, h: 260 },
  join: { w: 12, h: 260 },
};
const CARD: Size = { w: 196, h: 64 };

export function sizeOf(kind: NodeKind): Size {
  return SIZES[kind] ?? CARD;
}

/** Left-to-right layered layout. Returns each block's top-left corner. Retry loops are left out. */
export function autoLayout(nodes: Pick<FlowNode, "id" | "kind">[], edges: Pick<FlowEdge, "source" | "target" | "kind">[]) {
  const g = new dagre.graphlib.Graph();
  g.setGraph({ rankdir: "LR", nodesep: 40, ranksep: 70, marginx: 32, marginy: 32 });
  g.setDefaultEdgeLabel(() => ({}));
  for (const n of nodes) {
    const s = sizeOf(n.kind);
    g.setNode(n.id, { width: s.w, height: s.h });
  }
  for (const e of edges) {
    if (e.kind !== "retry" && g.hasNode(e.source) && g.hasNode(e.target)) g.setEdge(e.source, e.target);
  }
  dagre.layout(g);
  const out: Record<string, [number, number]> = {};
  for (const n of nodes) {
    const p = g.node(n.id);
    const s = sizeOf(n.kind);
    out[n.id] = [Math.round(p.x - s.w / 2), Math.round(p.y - s.h / 2)];
  }
  return out;
}

/** Saved positions first; anything missing comes from the auto-layout, so a new block never lands on (0, 0). */
export function placeAll(nodes: FlowNode[], edges: FlowEdge[], saved: Record<string, [number, number]>) {
  const missing = nodes.some((n) => !saved[n.id]);
  const auto = missing ? autoLayout(nodes, edges) : {};
  const out: Record<string, [number, number]> = {};
  for (const n of nodes) out[n.id] = saved[n.id] ?? auto[n.id] ?? [0, 0];
  return out;
}

function centre(p: [number, number], kind: NodeKind): [number, number] {
  const s = sizeOf(kind);
  return [p[0] + s.w / 2, p[1] + s.h / 2];
}

/** Which side a line leaves and arrives on, from where the two blocks sit (handle ids from nodes.tsx). */
export function handlesFor(e: Pick<FlowEdge, "source" | "target" | "kind">, kinds: Record<string, NodeKind>,
  pos: Record<string, [number, number]>): { s: string; t: string } {
  if (e.kind === "retry") return { s: "st", t: "tt" };
  const a = pos[e.source] ? centre(pos[e.source], kinds[e.source]) : [0, 0];
  const b = pos[e.target] ? centre(pos[e.target], kinds[e.target]) : [0, 0];
  const up = b[1] < a[1] - 40;
  const down = b[1] > a[1] + 40;
  if (e.kind === "fallback" && Math.abs(b[0] - a[0]) < 120) return up ? { s: "st", t: "tb" } : down ? { s: "sb", t: "tt" } : { s: "sr", t: "tl" };
  const s = kinds[e.source] === "decision" && e.kind === "branch" ? (up ? "st" : down ? "sb" : "sr") : "sr";
  const t = kinds[e.target] === "decision" && b[1] - a[1] > 60 && Math.abs(b[0] - a[0]) < 260 ? "tt" : "tl";
  return { s, t };
}
