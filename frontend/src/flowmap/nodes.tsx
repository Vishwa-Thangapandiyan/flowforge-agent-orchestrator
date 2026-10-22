// The map's blocks (D17): app calls and code (cards), start/end (pills), decisions (diamonds),
// run-together / wait-for-all (bars) and gates. On a dependency map (D21) the cards are dependencies and the
// pills are your app and your coding tools. Drawn from the design tokens.
import { Handle, Position, type Node, type NodeProps } from "@xyflow/react";
import type { ReactNode } from "react";
import type { ConnectorType, FlowNode } from "../api/types";
import { BrandTile } from "../brand/BrandTile";
import { caption as healthCaption } from "../checks/Health";
import type { LiveStatus } from "../checks/useChecks";
import { Icons } from "../components/icons";
import { sizeOf } from "./layout";
import type { NodeState } from "./replay";
import type { GraphTheme } from "./themes";
import { actionName, isThrough, SERVICE_WORD } from "./kinds";

export interface TileSource {
  id: string;
  type: ConnectorType;
  name: string;
}

export interface BlockData extends Record<string, unknown> {
  node: FlowNode;
  tile: TileSource | null;
  /** on a dependency map (D21) */
  deps?: boolean;
  /** on a flow read from code (D25): blocks lead with what they do */
  code?: boolean;
  /** how the map looks (D26); Metro draws a call as a station on its line */
  theme?: GraphTheme;
  /** its latest health check, or "checking" while one runs (D24) */
  health?: { status: LiveStatus; summary: string; latency_ms?: number | null };
  /** the worst level of its security findings (D31) */
  risk?: "high" | "medium" | "low";
  state: NodeState;
  cap: string;
  search: "hit" | "miss" | null;
  cp: boolean;
  showTip: boolean;
  showEvidence: boolean;
  /** a retry loop on this block: its attempt limit */
  retryMax: number | null;
  /** the re-check diff view: what changed here, its tag, and whether the user skipped it */
  diff?: "add" | "change" | "remove" | "conflict" | "kept";
  diffTag?: string;
  diffOff?: boolean;
}

export type BlockNode = Node<BlockData>;

const TAG: Record<string, string> = { llm: "LLM", api: "API", mcp: "MCP", local: "Local", code: "Code", gate: "Gate" };
const KIND_WORD: Record<string, string> = {
  start: "Start", end: "End", llm: "LLM call", api: "API call", mcp: "MCP tool", local: "Local command", code: "Your code",
  decision: "Decision", fork: "Run together", join: "Wait for all", gate: "You approve",
};

/** Hidden connection points: lines leave on the right (or top/bottom) and arrive on the left (or top/bottom). */
function Handles() {
  return (
    <>
      <Handle className="ff-handle" type="target" position={Position.Left} id="tl" isConnectable={false} />
      <Handle className="ff-handle" type="target" position={Position.Top} id="tt" isConnectable={false} />
      <Handle className="ff-handle" type="target" position={Position.Bottom} id="tb" isConnectable={false} />
      <Handle className="ff-handle" type="source" position={Position.Right} id="sr" isConnectable={false} />
      <Handle className="ff-handle" type="source" position={Position.Top} id="st" isConnectable={false} />
      <Handle className="ff-handle" type="source" position={Position.Bottom} id="sb" isConnectable={false} />
    </>
  );
}

function classes(d: BlockData, selected: boolean): string {
  const n = d.node;
  return [
    "ff-block", `kind-${n.kind}`, d.state !== "idle" && `st-${d.state}`, selected && "selected",
    n.status === "unconfirmed" && "unconf", d.search, d.cp && d.state === "idle" && "cp",
    d.diff && !d.diffOff && `diff-${d.diff}`, d.diffOff && "diff-off", d.health && `h-${d.health.status}`,
  ].filter(Boolean).join(" ");
}

function Status({ d }: { d: BlockData }) {
  const s = d.state;
  if (s === "ok" && !["decision", "fork", "join"].includes(d.node.kind)) return <span className="ff-st ok">{Icons.check(12)}</span>;
  if (s === "cached") return <span className="ff-st cached">cached</span>;
  if (s === "failed") return <span className="ff-st failed">!</span>;
  if (s === "waiting") return <span className="ff-st waiting">you</span>;
  if (s === "retry") return <span className="ff-st retry">retry</span>;
  return null;
}

function Caption({ d, evidence }: { d: BlockData; evidence: boolean }) {
  if (d.cap) return <span className={`ff-cap ${d.state}`}>{d.cap}</span>;
  const h = d.health ? healthCaption(d.health.status, d.health.summary, d.health.latency_ms) : "";
  if (!evidence) return h ? <span className="ff-cap"><em className={`ff-h ${d.health?.status}`}>{h}</em></span> : null;
  const first = d.node.evidence[0];
  if (!first || ["fork", "join"].includes(d.node.kind)) return null;
  const text = first.type === "code" && first.ref ? first.ref.split("/").pop()
    : first.type === "policy" ? "policy · D14" : first.type === "user" ? "added by you"
      : d.node.status === "unconfirmed" ? "no call found" : "";
  if (!text && !h) return null;
  return <span className="ff-cap">{text}{h && <em className={`ff-h ${d.health?.status}`}>{h}</em>}</span>;
}

function Shell({ d, selected, children }: { d: BlockData; selected: boolean; children: ReactNode }) {
  const size = sizeOf(d.node.kind);
  const n = d.node;
  return (
    <div className={classes(d, selected)} style={{ width: size.w, height: size.h }}
      aria-label={`${n.title}, ${KIND_WORD[n.kind] ?? n.kind}${d.tile ? `, ${d.tile.name}` : ""}${n.status === "unconfirmed" ? ", unconfirmed" : ""}${d.risk ? `, ${d.risk} security finding` : ""}`}>
      <span className="ff-focus" />
      {children}
      {d.diffTag ? <span className={`ff-dtag ${d.diffOff ? "off" : d.diff}`}>{d.diffTag}</span>
        : n.yours.length > 0 && <span className="ff-flag yours">Yours</span>}
      {d.showTip && n.tip && n.yours.length === 0 && <span className="ff-flag tip">{Icons.spark(11)} Tip</span>}
      <Status d={d} />
      {d.health && n.kind !== "start" && <span className={`hdot ff-hdot ${d.health.status}`} aria-hidden="true" />}
      {d.risk && <span className={`ff-risk lv-${d.risk}`} aria-hidden="true">!</span>}
      <Handles />
    </div>
  );
}

function Tile({ d }: { d: BlockData }) {
  const k = d.node.kind;
  if (k === "gate") return <span className="ff-icon lock">{Icons.lock(18)}</span>;
  if (k === "end") return <span className="ff-icon flag">{Icons.flag(18)}</span>;
  if (!d.tile) return <span className="ff-icon code">{Icons.code(18)}</span>;
  return <span className="brand-slot"><BrandTile c={d.tile} size={k === "start" ? 34 : 36} /></span>;
}

export function CardNode({ data, selected }: NodeProps<BlockNode>) {
  const n = data.node;
  if (data.theme === "metro") {   // a station: the line runs through it, its name above, what it is below
    return (
      <Shell d={data} selected={selected}>
        <span className="ff-metro">
          <span className="ff-title">{titleOf(data)}</span>
          <span className="ff-track"><i className="ff-station" /></span>
          <span className="ff-sub">{subOf(data)}</span>
        </span>
        <Caption d={data} evidence={data.showEvidence} />
      </Shell>
    );
  }
  return (
    <Shell d={data} selected={selected}>
      <span className="ff-card">
        <Tile d={data} />
        <span className="ff-text"><span className="ff-title">{titleOf(data)}</span><span className="ff-sub">{subOf(data)}</span></span>
      </span>
      <span className={`ff-tag ${n.kind === "llm" ? "llm" : n.kind === "gate" ? "gate" : ""}`}>{TAG[n.kind] ?? n.kind}</span>
      {data.retryMax && data.state === "idle" && <span className="ff-retry">{Icons.refresh(10)} {data.retryMax}×</span>}
      <Caption d={data} evidence={data.showEvidence} />
    </Shell>
  );
}

export function PillNode({ data, selected }: NodeProps<BlockNode>) {
  const n = data.node;
  return (
    <Shell d={data} selected={selected}>
      <span className="ff-pill">
        <Tile d={data} />
        <span className="ff-text"><span className="ff-title">{n.title}</span><span className="ff-sub">{subOf(data)}</span></span>
      </span>
      <Caption d={data} evidence={data.showEvidence} />
    </Shell>
  );
}

export function DecisionNode({ data, selected }: NodeProps<BlockNode>) {
  return (
    <Shell d={data} selected={selected}>
      <span className="ff-dia" />
      <span className="ff-dia-in" />
      <span className="ff-dtext">{data.node.title}</span>
      <Caption d={data} evidence={data.showEvidence} />
    </Shell>
  );
}

export function BarNode({ data, selected }: NodeProps<BlockNode>) {
  return (
    <Shell d={data} selected={selected}>
      <span className="ff-bar" />
      <span className="ff-barlabel">{data.node.title}</span>
    </Shell>
  );
}


/** A block's name: on a flow read from code, what the call does in the code's own words ("Today's weather"). */
export function titleOf(d: BlockData): string {
  const n = d.node;
  // a block reached through another server keeps its own name; "through fetch" goes underneath
  return d.code && SERVICE_WORD[n.kind] ? actionName(n) : n.title;
}

/** The grey line under a block's title: the model, endpoint or tool, from the map or the connector. */
export function subOf(d: BlockData): string {
  const n = d.node;
  const op = n.op ?? {};
  if (d.deps) return depSub(n);
  if (d.code) {   // the service under the action: "Open-Meteo · API"
    if (SERVICE_WORD[n.kind] && isThrough(n)) return `${SERVICE_WORD[n.kind]}, ${n.what}`;
    if (SERVICE_WORD[n.kind]) return n.what ? `${n.title} · ${SERVICE_WORD[n.kind]}` : SERVICE_WORD[n.kind];
    if (n.kind === "start") return "where it starts";
    if (n.kind === "end") return "the code stops";
  }
  if (n.kind === "gate") return n.added_by === "policy" ? "added by code · always" : "you approve · always";
  if (n.kind === "start") return d.tile ? `${d.tile.name} webhook` : "start";
  if (n.kind === "end") return "end";
  if (n.kind === "code") return n.added_by === "user" ? "your step" : "your code";
  if (n.kind === "llm") return [n.planner_connector && n.connector !== n.planner_connector ? "yours" : null, op.model ?? d.tile?.name]
    .filter(Boolean).join(" · ") || "LLM";
  if (n.kind === "mcp") return [d.tile?.name, op.tool].filter(Boolean).join(" · ");
  if (n.kind === "api") return [op.method, op.path].filter(Boolean).join(" ") || d.tile?.name || "API";
  return d.tile?.name ?? "";
}

/** host and path, without the scheme: "nominatim.openstreetmap.org/search" */
function shortTarget(what: string): string {
  return what.replace(/^https?:\/\//, "").replace(/\/$/, "");
}

function depSub(n: FlowNode): string {
  if (n.kind === "start") return n.id === "tools" ? "coding tools" : "your app";
  if (n.kind === "llm") return [n.op?.model, shortTarget(n.what)].filter(Boolean).join(" · ") || "LLM";
  if (n.added_by === "user") return "added by you";
  return shortTarget(n.what);
}

export const nodeTypes = { card: CardNode, pill: PillNode, decision: DecisionNode, bar: BarNode };

export function typeFor(kind: FlowNode["kind"]): keyof typeof nodeTypes {
  if (kind === "start" || kind === "end") return "pill";
  if (kind === "decision") return "decision";
  if (kind === "fork" || kind === "join") return "bar";
  return "card";
}
