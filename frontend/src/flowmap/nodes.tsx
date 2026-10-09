// The map's blocks (D17): app calls and code (cards), start/end (pills), decisions (diamonds),
// run-together / wait-for-all (bars) and gates. Drawn from the design tokens.
import { Handle, Position, type Node, type NodeProps } from "@xyflow/react";
import type { ReactNode } from "react";
import type { ConnectorType, FlowNode } from "../api/types";
import { BrandTile } from "../brand/BrandTile";
import { Icons } from "../components/icons";
import { sizeOf } from "./layout";
import type { NodeState } from "./replay";

export interface TileSource {
  id: string;
  type: ConnectorType;
  name: string;
}

export interface BlockData extends Record<string, unknown> {
  node: FlowNode;
  tile: TileSource | null;
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
    d.diff && !d.diffOff && `diff-${d.diff}`, d.diffOff && "diff-off",
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
  if (!evidence) return null;
  const first = d.node.evidence[0];
  if (!first || ["fork", "join"].includes(d.node.kind)) return null;
  const text = first.type === "code" && first.ref ? first.ref.split("/").pop()
    : first.type === "policy" ? "policy · D14" : first.type === "user" ? "added by you"
      : d.node.status === "unconfirmed" ? "no call found" : "";
  return text ? <span className="ff-cap">{text}</span> : null;
}

function Shell({ d, selected, children }: { d: BlockData; selected: boolean; children: ReactNode }) {
  const size = sizeOf(d.node.kind);
  const n = d.node;
  return (
    <div className={classes(d, selected)} style={{ width: size.w, height: size.h }}
      aria-label={`${n.title}, ${KIND_WORD[n.kind] ?? n.kind}${d.tile ? `, ${d.tile.name}` : ""}${n.status === "unconfirmed" ? ", unconfirmed" : ""}`}>
      <span className="ff-focus" />
      {children}
      {d.diffTag ? <span className={`ff-dtag ${d.diffOff ? "off" : d.diff}`}>{d.diffTag}</span>
        : n.yours.length > 0 && <span className="ff-flag yours">Yours</span>}
      {d.showTip && n.tip && n.yours.length === 0 && <span className="ff-flag tip">{Icons.spark(11)} Tip</span>}
      <Status d={d} />
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
  return (
    <Shell d={data} selected={selected}>
      <span className="ff-card">
        <Tile d={data} />
        <span className="ff-text"><span className="ff-title">{n.title}</span><span className="ff-sub">{subOf(data)}</span></span>
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

/** The grey line under a block's title: the model, endpoint or tool, from the map or the connector. */
export function subOf(d: BlockData): string {
  const n = d.node;
  const op = n.op ?? {};
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

export const nodeTypes = { card: CardNode, pill: PillNode, decision: DecisionNode, bar: BarNode };

export function typeFor(kind: FlowNode["kind"]): keyof typeof nodeTypes {
  if (kind === "start" || kind === "end") return "pill";
  if (kind === "decision") return "decision";
  if (kind === "fork" || kind === "join") return "bar";
  return "card";
}
