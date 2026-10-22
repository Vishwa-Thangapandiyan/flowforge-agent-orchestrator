// The MCP Map drawn as one self-contained SVG (D26, docs/mcp-map.md): its own colours and fonts inside, so the file
// you download looks the same in a report, a slide or a browser. Light or dark paper.
import { forwardRef, type ReactNode } from "react";
import { type Block, type Lane, LANES, type McpMap, took } from "./layout";

const W = 1600, LEFT = 230, RIGHT = 70, TOP = 108, ROW = 62, PAD = 16, EMPTY = 34, SLOT = 210;

const STYLE = `
.mcp-map { --paper:#FFFFFF; --ink:#111A21; --muted:#55656F; --rule:#D9E1E6; --band:#F4F7F9; --llm:#6B46C1;
  --mcp:#1E7A4A; --api:#2457C5; --local:#4A5E6A; --control:#111A21; --up:#0B7A70; --warn:#E3A535; --down:#D2513E;
  font-family: Geist, ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif; }
.mcp-map.dark { --paper:#0E1519; --ink:#E6EEF2; --muted:#9AAEB9; --rule:#24343D; --band:#121D23; --llm:#B79CFF;
  --mcp:#5CD49A; --api:#7FA8FF; --local:#A9B8C2; --control:#E6EEF2; --up:#4FD1C0; --warn:#F2B84B; --down:#FF8C7A; }
.mcp-map .paper { fill: var(--paper); }
.mcp-map .mono { font-family: "Geist Mono", ui-monospace, Menlo, Consolas, monospace; }
.mcp-map .title { font-size: 26px; font-weight: 650; fill: var(--ink); letter-spacing: -.02em; }
.mcp-map .sub { font-size: 13px; font-weight: 500; fill: var(--muted); }
.mcp-map .lane { fill: var(--paper); } .mcp-map .lane.odd { fill: var(--band); }
.mcp-map .lane-label { font-size: 14px; font-weight: 600; fill: var(--ink); }
.mcp-map .lane-none { font-size: 12px; fill: var(--muted); }
.mcp-map .tick { stroke: var(--rule); stroke-width: 1; } .mcp-map .tick.minor { stroke-dasharray: 2 4; }
.mcp-map .tick-label { font-size: 11.5px; font-weight: 500; fill: var(--muted); }
.mcp-map .line { fill: none; stroke: var(--muted); stroke-width: 1.4; }
.mcp-map .line.cp { stroke: var(--ink); stroke-width: 3; } .mcp-map .line.via { stroke-dasharray: 5 4; }
.mcp-map .when { font-size: 10.5px; font-weight: 600; fill: var(--muted); }
.mcp-map .arrow { fill: var(--muted); } .mcp-map .arrow.cp { fill: var(--ink); }
.mcp-map .sym { fill: var(--paper); stroke: currentColor; stroke-width: 2.2; } .mcp-map .sym-in, .mcp-map .stop { fill: currentColor; }
.mcp-map .k-llm { color: var(--llm); } .mcp-map .k-mcp { color: var(--mcp); } .mcp-map .k-api { color: var(--api); }
.mcp-map .k-local, .mcp-map .k-code { color: var(--local); }
.mcp-map .k-decision, .mcp-map .k-end, .mcp-map .k-gate, .mcp-map .k-start { color: var(--control); }
.mcp-map .unconfirmed .sym { stroke-dasharray: 3 3; }
.mcp-map .bar { fill: currentColor; opacity: .22; } .mcp-map .bar.est { opacity: .12; stroke: currentColor; stroke-dasharray: 3 3; }
.mcp-map .cp .bar { opacity: .45; }
.mcp-map .name { font-size: 13px; font-weight: 600; fill: var(--ink); }
.mcp-map .note { font-size: 11px; font-weight: 500; fill: var(--muted); }
.mcp-map .hdot { stroke: var(--paper); stroke-width: 1.5; } .mcp-map .h-up { fill: var(--up); }
.mcp-map .h-warn { fill: var(--warn); } .mcp-map .h-down { fill: var(--down); }
.mcp-map .key-label { font-size: 12.5px; font-weight: 550; fill: var(--ink); }
.mcp-map .rule { stroke: var(--rule); stroke-width: 1; }
`;

/** One shape per kind, readable in black and white (rule 3). */
export function Shape({ kind, x, y, r = 13 }: { kind: string; x: number; y: number; r?: number }): ReactNode {
  if (kind === "llm") return <><circle cx={x} cy={y} r={r} className="sym" /><circle cx={x} cy={y} r={r * 0.38} className="sym-in" /></>;
  if (kind === "mcp") {
    const pts = [0, 1, 2, 3, 4, 5].map((i) => { const a = (Math.PI / 3) * i + Math.PI / 6; return `${x + r * Math.cos(a)},${y + r * Math.sin(a)}`; });
    return <polygon points={pts.join(" ")} className="sym" />;
  }
  if (kind === "api") return <rect x={x - r * 0.88} y={y - r * 0.88} width={r * 1.76} height={r * 1.76} rx={r * 0.3} className="sym" />;
  if (kind === "local" || kind === "code") return <polygon points={`${x},${y - r} ${x + r},${y + r * 0.8} ${x - r},${y + r * 0.8}`} className="sym" />;
  if (kind === "decision" || kind === "gate") {
    return <rect x={x - r * 0.7} y={y - r * 0.7} width={r * 1.4} height={r * 1.4} transform={`rotate(45 ${x} ${y})`} className="sym" />;
  }
  if (kind === "start") return <><circle cx={x} cy={y} r={r} className="sym" /><circle cx={x} cy={y} r={r * 0.62} className="sym" /></>;
  return <rect x={x - r * 0.7} y={y - r * 0.7} width={r * 1.4} height={r * 1.4} className="stop" />;
}

const KEY: [string, string][] = [["start", "Entry point"], ["llm", "LLM"], ["mcp", "MCP server"], ["api", "API"],
  ["local", "Local program"], ["decision", "Decision"], ["end", "Stop"]];

/** A tick every 1, 2, 5 × 10ⁿ ms: about eight across the drawing. */
function tickStep(span: number): number {
  const raw = span / 8;
  const base = 10 ** Math.floor(Math.log10(raw));
  return [1, 2, 5, 10].map((m) => m * base).find((s) => s >= raw) ?? raw;
}

interface Props {
  map: McpMap;
  app: string;
  sub: string;
  dark: boolean;
}

export const McpMapSvg = forwardRef<SVGSVGElement, Props>(function McpMapSvg({ map, app, sub, dark }, ref) {
  const width = map.timed ? W : Math.max(W, LEFT + RIGHT + map.span * SLOT);
  const plot = width - LEFT - RIGHT - (map.timed ? 150 : 0);   // a flow keeps room on the right for the last names
  const xAt = (t: number) => LEFT + 40 + (map.timed ? (t / map.span) * plot : t * SLOT);
  const laneTop = {} as Record<Lane, number>, laneH = {} as Record<Lane, number>;
  let y = TOP;
  for (const l of LANES) {
    laneTop[l.kind] = y;
    laneH[l.kind] = map.rows[l.kind] ? map.rows[l.kind] * ROW + PAD * 2 : EMPTY;
    y += laneH[l.kind];
  }
  const axisY = y;
  const keyY = axisY + (map.timed ? 64 : 30);
  const height = keyY + 96;

  const entries = map.blocks.filter((b) => !b.lane);
  const at: Record<string, { x: number; x2: number; y: number; b: Block }> = {};
  entries.forEach((b, i) => {
    const yy = TOP + ((axisY - TOP) * (i + 1)) / (entries.length + 1);
    at[b.id] = { x: LEFT - 22, x2: LEFT - 22, y: yy, b };
  });
  for (const b of map.blocks) {
    if (!b.lane) continue;
    const x = xAt(b.start);
    at[b.id] = { x, x2: map.timed ? xAt(b.end) : x, y: laneTop[b.lane] + PAD + ROW * b.row + ROW / 2 + 4, b };
  }
  const ticks: number[] = [];
  if (map.timed) for (let t = 0, step = tickStep(map.span); t <= map.span + step / 2; t += step) ticks.push(t);

  return (
    <svg ref={ref} xmlns="http://www.w3.org/2000/svg" viewBox={`0 0 ${width} ${height}`} width={width} height={height}
      className={`mcp-map${dark ? " dark" : ""}`} role="img" aria-label={`MCP map of ${app}`}>
      <title>{`MCP map of ${app}`}</title>
      <style>{STYLE}</style>
      <defs>
        {["", "cp"].map((c) => (
          <marker key={c} id={`mm-arrow${c}`} viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
            <path d="M0,0 L10,5 L0,10 z" className={`arrow ${c}`} />
          </marker>
        ))}
      </defs>
      <rect x={0} y={0} width={width} height={height} className="paper" />
      <text x={32} y={46} className="title">{app}</text>
      <text x={32} y={72} className="sub mono">{sub}</text>
      <text x={width - 32} y={46} className="sub" textAnchor="end">MCP Map · rules v1</text>
      <text x={width - 32} y={72} className="sub mono" textAnchor="end">drawn by FlowForge</text>

      {LANES.map((l, i) => (
        <g key={l.kind}>
          <rect x={0} y={laneTop[l.kind]} width={width} height={laneH[l.kind]} className={`lane${i % 2 ? " odd" : ""}`} />
          <text x={32} y={laneTop[l.kind] + laneH[l.kind] / 2 + 5} className="lane-label">{l.label}</text>
          {!map.rows[l.kind] && <text x={LEFT + 40} y={laneTop[l.kind] + laneH[l.kind] / 2 + 4} className="lane-none">none</text>}
        </g>
      ))}
      {ticks.map((t) => (
        <g key={t}>
          <line x1={xAt(t)} y1={TOP} x2={xAt(t)} y2={axisY + 6} className="tick" />
          <text x={xAt(t)} y={axisY + 24} className="tick-label mono" textAnchor="middle">{took(t)}</text>
        </g>
      ))}
      {map.timed && <text x={32} y={axisY + 24} className="tick-label">time from the start →</text>}

      {map.lines.map((l) => {
        const a = at[l.from], b = at[l.to];
        if (!a || !b) return null;
        const ax = a.b.kind === "start" ? a.x + 15 : a.x2 + (a.b.kind === "decision" ? 10 : 0);
        const bx = b.x - 15;
        const forward = bx > ax + 8;
        const k = Math.min(70, Math.max(24, (bx - ax) / 2));   // curves keep lines that start together apart
        const down = b.y > a.y ? 1 : -1;
        // a call that starts as its source ends drops straight into it (Wikipedia, through fetch)
        const below = !forward && Math.abs(b.x - a.x2) < 30;
        const d = forward ? `M${ax},${a.y} C${ax + k},${a.y} ${bx - k},${b.y} ${bx},${b.y}`
          : below ? `M${b.x},${a.y + down * 8} V${b.y - down * 16}`
          : `M${a.x},${a.y + down * 15} V${b.y} H${bx}`;
        const cls = ["line", l.critical && "cp", l.via && "via"].filter(Boolean).join(" ");
        return (
          <g key={`${l.from}>${l.to}`}>
            <path d={d} className={cls} markerEnd={`url(#mm-arrow${l.critical ? "cp" : ""})`} />
            {l.when && <text x={below ? b.x - 6 : bx - 4} y={below ? b.y - down * 22 : b.y - 7} className="when" textAnchor="end">{l.when}</text>}
          </g>
        );
      })}

      {Object.values(at).map(({ x, x2, y: yy, b }) => (
        <g key={b.id} className={[`k-${b.kind}`, b.critical && "cp", b.unconfirmed && "unconfirmed"].filter(Boolean).join(" ")}>
          {x2 - x > 2 && <rect x={x} y={yy - 5} width={x2 - x} height={10} rx={5} className={`bar${b.estimate ? " est" : ""}`} />}
          <Shape kind={b.kind} x={x} y={yy} />
          {b.lane ? (
            <>
              <text x={x + 20} y={yy - 13} className="name">{b.name}</text>
              {(b.note || b.writes || b.repeats) && (
                <text x={x + 20} y={yy + 25} className="note mono">
                  {[b.note, b.writes && "✎ writes", b.repeats && "↻ repeats"].filter(Boolean).join("  ")}
                </text>
              )}
            </>
          ) : (
            <text x={x} y={yy + 32} className="name" textAnchor="middle">{b.name}</text>
          )}
          {b.health && ["up", "warn", "down"].includes(b.health) && <circle cx={x + 11} cy={yy - 11} r={4} className={`hdot h-${b.health}`} />}
        </g>
      ))}

      <line x1={32} y1={keyY - 22} x2={width - 32} y2={keyY - 22} className="rule" />
      {KEY.map(([kind, label], i) => (
        <g key={kind} className={`k-${kind}`}>
          <Shape kind={kind} x={44 + i * 150} y={keyY + 4} r={10} />
          <text x={62 + i * 150} y={keyY + 9} className="key-label">{label}</text>
        </g>
      ))}
      <g>
        {map.timed && <>
          <path d={`M32,${keyY + 48} H76`} className="line cp" />
          <text x={86} y={keyY + 52} className="key-label">critical path: sets the total time</text>
        </>}
        <path d={`M344,${keyY + 48} H388`} className="line via" />
        <text x={398} y={keyY + 52} className="key-label">through another server</text>
        {map.timed && <>
          <rect x={604} y={keyY + 43} width={44} height={10} rx={5} className="bar est" style={{ color: "var(--muted)" }} />
          <text x={658} y={keyY + 52} className="key-label">estimate, not measured</text>
        </>}
        <circle cx={870} cy={keyY + 48} r={4} className="hdot h-up" />
        <circle cx={882} cy={keyY + 48} r={4} className="hdot h-warn" />
        <circle cx={894} cy={keyY + 48} r={4} className="hdot h-down" />
        <text x={906} y={keyY + 52} className="key-label">health: up · needs a look · down</text>
        <text x={1160} y={keyY + 52} className="key-label">✎ writes   ↻ repeats in a loop</text>
      </g>
    </svg>
  );
});
