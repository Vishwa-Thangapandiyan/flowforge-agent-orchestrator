// Graph themes (D26, docs/design/flow-artboards/themes.html): how the map looks, picked per viewer. Every theme keeps
// the same meanings: health colours, the critical path as the thickest line, measured versus estimated weights.
import type { Node } from "@xyflow/react";
import type { FlowView, NodeKind } from "../api/types";
import { CALL_KINDS, earliest, isThrough } from "./kinds";
import { sizeOf, type Sizer } from "./layout";

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
    const asked = new URLSearchParams(window.location.search).get("style");   // a link to one style: ?style=boxed
    if (THEMES.some((t) => t.id === asked)) return asked as GraphTheme;
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
const COLUMN = 340, ROW_GAP = 52;

const isThroughId = (flow: FlowView, id: string) => { const n = flow.nodes.find((x) => x.id === id); return !!n && isThrough(n); };

export function timeColumns(flow: FlowView, placed: Record<string, [number, number]>,
  size: Sizer = sizeOf): Record<string, [number, number]> {
  const start = earliest(flow);
  const through = new Map(flow.edges.filter((e) => isThroughId(flow, e.target))
    .map((e) => [e.target, e.source]));
  const key = (id: string): number => {
    const n = flow.nodes.find((x) => x.id === id)!;
    if (n.kind === "start") return -1;
    if (through.has(id)) return key(through.get(id)!) + 0.01;   // its own narrow column, right of its server
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
  const kind = (id: string) => flow.nodes.find((x) => x.id === id)!.kind;
  [...columns.keys()].sort((a, b) => a - b).forEach((k, col) => {
    const ids = columns.get(k)!.sort((a, b) => (placed[a]?.[1] ?? 0) - (placed[b]?.[1] ?? 0));
    // stack by each block's own height, with room for its file:line underneath and the box's title above
    const total = ids.reduce((t, id) => t + size(kind(id)).h, 0) + ROW_GAP * (ids.length - 1);
    let y = -total / 2;
    for (const id of ids) {
      out[id] = [col * COLUMN, through.has(id) ? NaN : y];
      y += size(kind(id)).h + ROW_GAP;
    }
  });
  for (const [id, server] of through) if (out[id] && out[server]) out[id][1] = out[server][1];   // level with its server
  return out;
}

/** Boxed on a dependency map (D38): one lane per kind, side by side: LLMs · MCP servers · APIs · Local programs. MCP
 * servers and APIs sit next to each other, so a line from a server to an API it reaches only crosses the gap. The
 * start blocks (your app, your coding tools) stand on the left. Laid out by code, never saved. */
export const LANE_ORDER: NodeKind[] = ["llm", "mcp", "api", "local"];
const LANE_X0 = 300, LANE_GAP = 70, LANE_PAD = 22, LANE_TOP = 90, ROW = 18;

export function kindLanes(flow: FlowView, size: Sizer = sizeOf): Record<string, [number, number]> {
  const out: Record<string, [number, number]> = {};
  const name = (id: string) => flow.nodes.find((n) => n.id === id)?.title.toLowerCase() ?? id;
  let x = LANE_X0;
  let tallest = 0;
  for (const kind of LANE_ORDER) {
    const ids = flow.nodes.filter((n) => n.kind === kind).map((n) => n.id).sort((a, b) => name(a).localeCompare(name(b)));
    if (!ids.length) continue;
    const box = size(kind);
    ids.forEach((id, i) => { out[id] = [x, LANE_TOP + i * (box.h + ROW)]; });
    tallest = Math.max(tallest, ids.length * (box.h + ROW));
    x += box.w + 2 * LANE_PAD + LANE_GAP;
  }
  const starts = flow.nodes.filter((n) => !(n.id in out));
  starts.forEach((n, i) => {
    const box = size(n.kind);
    out[n.id] = [0, LANE_TOP + Math.max(0, tallest / 2 - box.h / 2) + i * (box.h + 40)];
  });
  return out;
}

/** The one line from each start block into the top of each lane it uses (D38): it runs above the lanes, so it never
 * crosses a block. Returns SVG paths in map coordinates, for the Boxed layer. */
export function busPaths(flow: FlowView, placed: Node[], rects: BoxRect[]): { key: string; d: string }[] {
  const at = Object.fromEntries(placed.map((n) => [n.id, n]));
  const kind = Object.fromEntries(flow.nodes.map((n) => [n.id, n.kind]));
  const laneOf = (k: NodeKind) => rects.find((r) => r.label === KIND_LANE[k]);
  const out: { key: string; d: string }[] = [];
  const starts = [...new Set(flow.edges.filter((e) => kind[e.source] === "start").map((e) => e.source))];
  starts.forEach((s, i) => {
    const from = at[s];
    if (!from) return;
    const lanes = [...new Set(flow.edges.filter((e) => e.source === s).map((e) => laneOf(kind[e.target])))]
      .filter((r): r is BoxRect => !!r);
    if (!lanes.length) return;
    const top = Math.min(...lanes.map((r) => r.y));
    const busY = top - 26 - i * 14;
    const sx = from.position.x + (from.width ?? 196);
    const sy = from.position.y + (from.height ?? 64) / 2;
    for (const r of lanes) {
      const lx = r.x + 30 + i * 10;
      out.push({ key: `${s}-${r.key}`, d: `M${sx} ${sy} C${sx + 40} ${sy} ${sx + 40} ${busY} ${sx + 80} ${busY} L${lx} ${busY} L${lx} ${r.y}` });
    }
  });
  return out;
}

/** On lanes the start blocks' own lines are replaced by the bus (D38); every other line stays. */
export function laneEdge(flow: FlowView, e: { source: string }): boolean {
  return flow.nodes.find((n) => n.id === e.source)?.kind !== "start";
}
