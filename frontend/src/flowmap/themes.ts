// Graph themes (D26, docs/design/flow-artboards/themes.html): how the map looks, picked per viewer. Every theme keeps
// the same meanings: health colours, the critical path as the thickest line, measured versus estimated weights.
import type { Node } from "@xyflow/react";
import type { FlowView, NodeKind } from "../api/types";
import { CALL_KINDS, earliest, isThrough } from "./kinds";

export type GraphTheme = "studio" | "boxed" | "blueprint" | "metro" | "soft";

export const THEMES: { id: GraphTheme; name: string; note: string }[] = [
  { id: "studio", name: "Studio", note: "cards, the familiar look" },
  { id: "boxed", name: "Boxed", note: "boxes of what runs together" },
  { id: "blueprint", name: "Blueprint", note: "an engineering drawing" },
  { id: "metro", name: "Metro", note: "a transit map" },
  { id: "soft", name: "Soft", note: "calm colour fields" },
];

const KEY = "flowforge.graphTheme";   // a viewer convenience: kept in this browser only (D26)

export function readTheme(): GraphTheme {
  try {
    const saved = localStorage.getItem(KEY);
    return THEMES.some((t) => t.id === saved) ? (saved as GraphTheme) : "studio";
  } catch {
    return "studio";
  }
}

export function saveTheme(theme: GraphTheme): void {
  try { localStorage.setItem(KEY, theme); } catch { /* not remembered */ }
}

const KIND_LANE: Partial<Record<NodeKind, string>> = { llm: "LLMs", mcp: "MCP servers", api: "APIs", local: "Local programs" };

/** A Boxed container (D26), in map coordinates. */
export interface BoxRect {
  key: string;
  label: string;
  note: string;
  x: number;
  y: number;
  w: number;
  h: number;
}

/** Boxed (D26): containers drawn behind the blocks. On a flow, the calls that start at the same moment; on a
 * dependency map, one box per kind. Each box wraps its blocks where they sit now. */
export function boxes(flow: FlowView, placed: Node[]): BoxRect[] {
  const at = Object.fromEntries(placed.map((n) => [n.id, n]));
  const groups = new Map<string, { label: string; note: string; ids: string[] }>();
  if (flow.kind === "dependencies") {
    for (const n of flow.nodes) {
      const lane = KIND_LANE[n.kind];
      if (!lane) continue;
      const g = groups.get(lane) ?? { label: lane, note: "", ids: [] };
      g.ids.push(n.id);
      groups.set(lane, g);
    }
    for (const g of groups.values()) g.note = `${g.ids.length}`;
  } else {
    const start = earliest(flow);
    for (const n of flow.nodes) {
      if (!CALL_KINDS.has(n.kind) || isThrough(n)) continue;   // reached through a server: not a call
      const key = (start[n.id] ?? 0).toFixed(0);
      const g = groups.get(key) ?? { label: "Start together", note: `at ${((start[n.id] ?? 0) / 1000).toFixed(1)} s`, ids: [] };
      g.ids.push(n.id);
      groups.set(key, g);
    }
    for (const [key, g] of groups) if (g.ids.length < 2) groups.delete(key);
  }
  const out: BoxRect[] = [];
  let i = 0;
  for (const g of groups.values()) {
    const members = g.ids.map((id) => at[id]).filter(Boolean);
    if (!members.length) continue;
    const left = Math.min(...members.map((m) => m.position.x)) - 22;
    const top = Math.min(...members.map((m) => m.position.y)) - 46;
    const right = Math.max(...members.map((m) => m.position.x + (m.width ?? 196))) + 22;
    const bottom = Math.max(...members.map((m) => m.position.y + (m.height ?? 64))) + 30;
    out.push({ key: `box-${i++}`, label: g.label, note: g.note, x: left, y: top, w: right - left, h: bottom - top });
  }
  return out;
}

/** Boxed on a flow (D26): one column per moment in time, so a box holds exactly the calls that start together.
 * Decisions (and where they stop) sit just before the calls that wait on them; a block reached through a server
 * stays with that server; within a column the usual layout's top-to-bottom order is kept. */
const isThroughId = (flow: FlowView, id: string) => { const n = flow.nodes.find((x) => x.id === id); return !!n && isThrough(n); };

export function timeColumns(flow: FlowView, placed: Record<string, [number, number]>): Record<string, [number, number]> {
  const start = earliest(flow);
  const through = new Map(flow.edges.filter((e) => isThroughId(flow, e.target))
    .map((e) => [e.target, e.source]));
  const key = (id: string): number => {
    const n = flow.nodes.find((x) => x.id === id)!;
    if (n.kind === "start") return -1;
    if (through.has(id)) return key(through.get(id)!);
    if (n.kind === "decision" || n.kind === "end") {
      const gate = flow.edges.find((e) => e.target === id && flow.nodes.find((x) => x.id === e.source)?.kind === "decision");
      return n.kind === "end" && gate ? key(gate.source) : (start[id] ?? 0) - 0.5;
    }
    return start[id] ?? 0;
  };
  const columns = new Map<number, string[]>();
  for (const n of flow.nodes) {
    const k = key(n.id);
    columns.set(k, [...(columns.get(k) ?? []), n.id]);
  }
  const out: Record<string, [number, number]> = {};
  [...columns.keys()].sort((a, b) => a - b).forEach((k, col) => {
    const ids = columns.get(k)!.sort((a, b) => (placed[a]?.[1] ?? 0) - (placed[b]?.[1] ?? 0));
    const top = -((ids.length - 1) * 104) / 2;
    ids.forEach((id, row) => { out[id] = [col * 280, top + row * 104]; });
  });
  return out;
}
