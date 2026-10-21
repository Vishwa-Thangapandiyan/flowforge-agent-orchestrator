// The MCP Map (D26, docs/mcp-map.md): where each block sits. Lanes are kinds (rule 1); on a flow, time runs left to
// right and a bar is as long as the call (rule 2); a map of dependencies only has no time axis.
import type { FlowNode, FlowView, HealthStatus, NodeKind } from "../api/types";
import { earliest } from "../flowmap/Faster";

export type Lane = "decision" | "llm" | "mcp" | "api" | "local";

export const LANES: { kind: Lane; label: string }[] = [
  { kind: "decision", label: "Decisions" }, { kind: "llm", label: "LLMs" }, { kind: "mcp", label: "MCP servers" },
  { kind: "api", label: "APIs" }, { kind: "local", label: "Local programs" },
];

const SERVICE: Record<string, string> = { llm: "LLM", api: "API", mcp: "MCP server", local: "local program" };

export interface Block {
  id: string;
  kind: NodeKind;
  /** null: an entry point, drawn left of the lanes */
  lane: Lane | null;
  row: number;
  /** ms from the start (a flow), or the slot index (a dependency map) */
  start: number;
  end: number;
  name: string;
  /** the line under the name: the service, its time, what it marks */
  note: string;
  estimate: boolean;
  critical: boolean;
  writes: boolean;
  repeats: boolean;
  unconfirmed: boolean;
  /** the dependency's id on the Checks page: `api-nominatim-1` → `api-nominatim` */
  dep: string;
  health?: HealthStatus;
}

export interface Line {
  from: string;
  to: string;
  when: string | null;
  critical: boolean;
  /** reached through another server: dashed (rule 4) */
  via: boolean;
}

export interface McpMap {
  timed: boolean;
  blocks: Block[];
  lines: Line[];
  rows: Record<Lane, number>;
  /** a flow: the time at best (the critical path); a dependency map: the widest lane's slots */
  span: number;
  calls: number;
  decisions: number;
  /** the files the blocks were read from */
  files: string[];
}

/** "420 ms", "6.8 s": a report reads milliseconds better than "0.42 s". */
export function took(ms: number): string {
  if (ms < 1000) return `${Math.round(ms)} ms`;
  if (ms >= 60_000) return `${Math.floor(ms / 60_000)} min ${Math.round((ms % 60_000) / 1000)} s`;
  return `${(ms / 1000).toFixed(1)} s`;
}

const READS = new Set(["GET", "HEAD", "OPTIONS"]);

/** ✎ only when the code says so: a tool marked not read-only, or a write method. A block with no method waits at a
 * gate (D17), but a report shouldn't claim it writes. */
const writes = (n: FlowNode) =>
  n.op?.read_only === false || (!!n.op?.method && !READS.has(n.op.method.toUpperCase()));

const laneOf = (kind: NodeKind): Lane | null =>
  kind === "decision" || kind === "end" || kind === "gate" ? "decision"
    : kind === "llm" || kind === "mcp" || kind === "api" || kind === "local" ? kind
    : kind === "code" ? "local" : null;

/** How much room a name needs, as a share of the drawing: a short call still gets a readable label. */
export const NAME_ROOM = 0.13;

export function layoutMap(flow: FlowView, health: Record<string, HealthStatus> = {}): McpMap {
  const timed = flow.kind !== "dependencies";
  const code = flow.source === "code";
  const critical = new Set(flow.critical_path.path);
  const kindOf = Object.fromEntries(flow.nodes.map((n) => [n.id, n.kind]));
  const start = timed ? earliest(flow) : {};
  const order = timed ? [...flow.nodes].sort((a, b) => start[a.id] - start[b.id] || a.id.localeCompare(b.id))
    : [...flow.nodes].sort((a, b) => a.title.localeCompare(b.title));

  const blocks: Block[] = [];
  const slots: Record<string, number> = {};
  for (const n of order) {
    const lane = laneOf(n.kind);
    const ms = n.estimate_ms ?? 0;
    const through = n.what?.startsWith("through ");
    const named = code && SERVICE[n.kind] && n.what && !through;
    const name = n.kind === "end" ? "Stop" : named ? n.what.charAt(0).toUpperCase() + n.what.slice(1) : n.title;
    const estimate = n.kind === "llm" || n.estimate_source === "estimate";
    const note = [
      named ? n.title : through ? n.what : null,
      timed && ms > 0 && SERVICE[n.kind] ? `${took(ms)}${estimate ? " est." : ""}` : null,
      n.status === "unconfirmed" ? "unconfirmed" : null,
    ].filter(Boolean).join(" · ");
    const at = timed ? start[n.id] : lane ? (slots[lane] = (slots[lane] ?? -1) + 1) : 0;
    const dep = n.id.replace(/-\d+$/, "");
    blocks.push({
      id: n.id, kind: n.kind, lane, row: 0, start: at, end: timed && SERVICE[n.kind] ? at + ms : at, name, note,
      estimate, critical: critical.has(n.id), writes: writes(n), repeats: !!n.repeats,
      unconfirmed: n.status === "unconfirmed", dep, health: health[dep] ?? health[n.id],
    });
  }

  const span = timed ? Math.max(flow.critical_path.length_ms, ...blocks.map((b) => b.end), 1)
    : Math.max(1, ...Object.values(slots).map((s) => s + 1));
  // a block takes the first row of its lane that is free when it starts: names never sit on each other
  const rows = Object.fromEntries(LANES.map((l) => [l.kind, 0])) as Record<Lane, number>;
  const free: Record<string, number[]> = {};
  for (const b of blocks) {
    if (!b.lane) continue;
    const ends = (free[b.lane] ||= []);
    let row = ends.findIndex((end) => end <= b.start);
    if (row < 0) { row = ends.length; ends.push(0); }
    ends[row] = timed ? Math.max(b.end, b.start + span * NAME_ROOM) : b.start + 1;
    b.row = row;
    rows[b.lane] = Math.max(rows[b.lane], row + 1);
  }

  // through a server: on a flow the block says so ("through fetch"); on a dependency map a server's own lines (D21)
  const through = new Set(flow.nodes.filter((n) => n.what?.startsWith("through ")).map((n) => n.id));
  const lines: Line[] = flow.edges.filter((e) => kindOf[e.source] && kindOf[e.target]).map((e) => ({
    from: e.source, to: e.target, when: e.when,
    critical: critical.has(e.source) && critical.has(e.target),
    via: timed ? through.has(e.target) : kindOf[e.source] === "mcp" && kindOf[e.target] !== "mcp",
  }));
  const files = [...new Set(flow.nodes.flatMap((n) => n.evidence.map((ev) => ev.ref?.split(":")[0]).filter(Boolean)))] as string[];
  return {
    timed, blocks, lines, rows, span, files,
    calls: blocks.filter((b) => SERVICE[b.kind]).length,
    decisions: blocks.filter((b) => b.kind === "decision").length,
  };
}
