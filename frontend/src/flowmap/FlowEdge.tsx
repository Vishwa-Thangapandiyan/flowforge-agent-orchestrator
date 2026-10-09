// A line on the map (D17): a curved bezier from the source block to the target, never boxy.
// Branch answers and fallbacks get a label; lines into an LLM get the redaction shield; running lines carry dots.
import { EdgeLabelRenderer, Position, useInternalNode, type Edge, type EdgeProps } from "@xyflow/react";
import type { FlowEdge } from "../api/types";
import { Icons } from "../components/icons";
import type { EdgeState } from "./replay";

export interface LineData extends Record<string, unknown> {
  edge: FlowEdge;
  state: EdgeState;
  cp: boolean;
  dim: boolean;
  guard: boolean;
}

export type LineEdge = Edge<LineData>;
type Pt = [number, number];

const clamp = (v: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, v));

export function curve(sx: number, sy: number, sp: Position, tx: number, ty: number, tp: Position, fallback = false): Pt[] {
  const dx = Math.max(36, Math.abs(tx - sx) * 0.5);
  const dy = Math.max(36, Math.abs(ty - sy) * 0.55);
  if (fallback && sp === Position.Top && tp === Position.Bottom) return [[sx, sy], [sx + 70, sy - dy], [tx + 70, ty + dy], [tx, ty]];
  if (fallback && sp === Position.Bottom && tp === Position.Top) return [[sx, sy], [sx + 70, sy + dy], [tx + 70, ty - dy], [tx, ty]];
  const c1: Pt = sp === Position.Right ? [sx + dx, sy] : sp === Position.Top ? [sx, sy - dy] : sp === Position.Bottom ? [sx, sy + dy] : [sx - dx, sy];
  const c2: Pt = tp === Position.Left ? [tx - dx, ty] : tp === Position.Top ? [tx, ty - dy] : tp === Position.Bottom ? [tx, ty + dy] : [tx + dx, ty];
  return [[sx, sy], c1, c2, [tx, ty]];
}

export function pathOf(p: Pt[]): string {
  const f = (v: number) => Math.round(v * 10) / 10;
  return `M ${f(p[0][0])} ${f(p[0][1])} C ${f(p[1][0])} ${f(p[1][1])}, ${f(p[2][0])} ${f(p[2][1])}, ${f(p[3][0])} ${f(p[3][1])}`;
}

export function pointAt(p: Pt[], t: number): Pt {
  const u = 1 - t;
  const at = (i: 0 | 1) => u * u * u * p[0][i] + 3 * u * u * t * p[1][i] + 3 * u * t * t * p[2][i] + t * t * t * p[3][i];
  return [at(0), at(1)];
}

function marker(d: LineData): string {
  if (d.state === "active") return "ffa-blue";
  if (d.state === "done") return "ffa-teal";
  if (d.edge.kind === "fallback") return "ffa-coral";
  if (d.edge.kind === "unconfirmed") return "ffa-faint";
  if (d.edge.kind === "retry") return "ffa-muted";
  if (d.cp) return "ffa-fg";
  return "ffa-edge";
}

export function FlowEdgeView({ source, target, sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition, data }: EdgeProps<LineEdge>) {
  const s = useInternalNode(source);
  const t = useInternalNode(target);
  if (!data) return null;
  const e = data.edge;
  let pts: Pt[];
  if (e.kind === "retry" && s) {
    // a loop over the block's top-right: out, up, back down into the block
    const x = s.internals.positionAbsolute.x;
    const y = s.internals.positionAbsolute.y;
    const w = s.measured?.width ?? 196;
    pts = [[x + w - 34, y], [x + w - 34, y - 46], [x + w - 96, y - 46], [x + w - 96, y - 1]];
  } else {
    let sy = sourceY;
    let ty = targetY;
    // fork/join bars: a line meets the bar level with the block on the other end
    if (s?.type === "bar" && sourcePosition === Position.Right) {
      const top = s.internals.positionAbsolute.y;
      sy = clamp(targetY, top + 14, top + (s.measured?.height ?? 260) - 14);
    }
    if (t?.type === "bar" && targetPosition === Position.Left) {
      const top = t.internals.positionAbsolute.y;
      ty = clamp(sy, top + 14, top + (t.measured?.height ?? 260) - 14);
    }
    pts = curve(sourceX, sy, sourcePosition, targetX, ty, targetPosition, e.kind === "fallback");
  }
  const d = pathOf(pts);
  const cls = ["ff-edge", e.kind === "fallback" && "fb", e.kind === "unconfirmed" && "unc", e.kind === "retry" && "loop",
    data.cp && data.state === "idle" && "cp", data.state !== "idle" && data.state, data.dim && "dim"].filter(Boolean).join(" ");
  const off = data.state === "skipped" || data.dim;
  const labels: { at: Pt; text: string; cls: string; shield?: boolean; title?: string }[] = [];
  const vertical = sourcePosition === Position.Top || sourcePosition === Position.Bottom;
  if (e.kind === "branch" && e.when) labels.push({ at: pointAt(pts, vertical ? 0.32 : 0.5), text: e.when, cls: "br" });
  if (e.kind === "fallback") labels.push({ at: pointAt(pts, 0.5), text: e.on || "fallback", cls: "fb" });
  if (e.kind === "unconfirmed") labels.push({ at: pointAt(pts, 0.5), text: "unconfirmed", cls: "unc" });
  if (data.guard) labels.push({ at: pointAt(pts, e.when ? 0.72 : 0.5), text: "", cls: "guard", shield: true,
    title: "Keys and personal data are removed before the LLM sees anything" });
  return (
    <>
      <g className={cls}>
        <path className="ff-under" d={d} />
        <path className="ff-line" d={d} markerEnd={`url(#${marker(data)})`} />
        {data.state === "active" && (
          <>
            <circle className="ff-dot-glow" r={8}><animateMotion dur="1.1s" repeatCount="indefinite" path={d} /></circle>
            <circle className="ff-dot" r={3.6}><animateMotion dur="1.1s" repeatCount="indefinite" path={d} /></circle>
            <circle className="ff-dot" r={3}><animateMotion dur="1.1s" begin="0.37s" repeatCount="indefinite" path={d} /></circle>
            <circle className="ff-dot" r={2.4}><animateMotion dur="1.1s" begin="0.74s" repeatCount="indefinite" path={d} /></circle>
          </>
        )}
      </g>
      {labels.length > 0 && (
        <EdgeLabelRenderer>
          {labels.map((l) => (
            <span key={l.cls + l.text} className={`ff-elabel ${l.cls}${off ? " off" : ""}`} title={l.title}
              style={{ transform: `translate(-50%, -50%) translate(${l.at[0]}px, ${l.at[1]}px)` }}>
              {l.shield ? Icons.shield(13) : l.text}
            </span>
          ))}
        </EdgeLabelRenderer>
      )}
    </>
  );
}

export const edgeTypes = { flow: FlowEdgeView };

/** The hidden arrowheads every line points with (one per colour, so heads match their line). */
export function Markers() {
  const heads: [string, string, number][] = [
    ["ffa-edge", "var(--edge)", 10], ["ffa-fg", "var(--fg)", 10], ["ffa-blue", "var(--blue)", 11], ["ffa-teal", "var(--teal)", 11],
    ["ffa-coral", "var(--coral)", 10], ["ffa-faint", "var(--faint)", 10], ["ffa-muted", "var(--muted)", 10],
  ];
  return (
    <svg width="0" height="0" aria-hidden="true" style={{ position: "absolute", width: 0, height: 0, overflow: "hidden" }}>
      <defs>
        {heads.map(([id, fill, size]) => (
          <marker key={id} id={id} viewBox="0 0 10 10" refX="8.6" refY="5" markerWidth={size} markerHeight={size}
            markerUnits="userSpaceOnUse" orient="auto">
            <path d="M1 1.4 L9.2 5 L1 8.6 Z" style={{ fill }} />
          </marker>
        ))}
      </defs>
    </svg>
  );
}
