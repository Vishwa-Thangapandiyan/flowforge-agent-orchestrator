// The Faster panel (D25, docs/design/flow-artboards/flow.html): the same calls twice, one after another as the code
// is written and as early as their inputs allow, then the advice that closes the gap. Pointing at advice lights
// up its blocks on the map.
import { useMemo } from "react";
import type { FlowNode, FlowView } from "../api/types";
import { took } from "../checks/Health";

/** What a call does, in the code's own words, else the service's name. */
const named = (n: FlowNode) => (n.what ? n.what.charAt(0).toUpperCase() + n.what.slice(1) : n.title);
const seconds = (ms: number) => `${(ms / 1000).toFixed(1)} s`;
const CALLS = new Set(["llm", "api", "mcp", "local"]);
const LANES = 4;

function line(n: FlowNode): number {
  return Number(n.evidence[0]?.ref?.split(":").pop() ?? 0);
}

/** Each call's earliest start: when every block it waits for is done (weights from the map). */
function earliest(flow: FlowView): Record<string, number> {
  const into: Record<string, string[]> = {};
  for (const e of flow.edges) (into[e.target] ||= []).push(e.source);
  const weight = Object.fromEntries(flow.nodes.map((n) => [n.id, n.estimate_ms ?? 0]));
  const start: Record<string, number> = {};
  const at = (id: string, seen = new Set<string>()): number => {
    if (id in start) return start[id];
    if (seen.has(id)) return 0;
    seen.add(id);
    start[id] = Math.max(0, ...(into[id] ?? []).map((p) => at(p, seen) + weight[p]));
    return start[id];
  };
  for (const n of flow.nodes) at(n.id);
  return start;
}

export function Faster({ flow, onPoint }: { flow: FlowView; onPoint: (ids: string[] | null) => void }) {
  const calls = useMemo(() => flow.nodes.filter((n) => CALLS.has(n.kind) && (n.estimate_ms ?? 0) > 0)
    .sort((a, b) => line(a) - line(b)), [flow.nodes]);
  const start = useMemo(() => earliest(flow), [flow]);
  const written = flow.written_ms ?? calls.reduce((t, n) => t + (n.estimate_ms ?? 0), 0);
  const could = flow.critical_path.length_ms;
  const scale = Math.max(written, could, 1);
  const pct = (ms: number) => `${(ms / scale) * 100}%`;
  // pack the "could be" bars into a few lanes, earliest first
  const lanes: { id: string; kind: string; from: number; ms: number; est: boolean }[][] = Array.from({ length: LANES }, () => []);
  const ends = Array(LANES).fill(0);
  for (const n of [...calls].sort((a, b) => start[a.id] - start[b.id])) {
    const from = start[n.id], ms = n.estimate_ms ?? 0;
    let lane = ends.findIndex((end) => end <= from + 1);
    if (lane < 0) lane = ends.indexOf(Math.min(...ends));
    ends[lane] = from + ms;
    lanes[lane].push({ id: n.id, kind: n.kind, from, ms, est: n.estimate_source === "estimate" });
  }
  let at = 0;
  const saved = written - could;
  const path = flow.critical_path.path.map((id) => flow.nodes.find((n) => n.id === id)).filter((n) => n && CALLS.has(n.kind));
  const slowest = flow.nodes.find((n) => n.id === flow.critical_path.bottleneck);
  return (
    <section className="sp fx" aria-label="Faster">
      <div className="sp-sec">
        <h2 className="fx-h">Faster<small>The same {calls.length} calls, as written and as your dependencies allow.</small></h2>
        <div className="fx-times">
          <span>As written<b>{took(written)}</b></span>
          <div className="fx-lane" role="img" aria-label={`as written: ${took(written)}`}>
            {calls.map((n) => {
              const left = at;
              at += n.estimate_ms ?? 0;
              return <i key={n.id} className={`fx-seg ${n.kind}${n.estimate_source === "estimate" ? " est" : ""}`}
                style={{ left: pct(left), width: pct(n.estimate_ms ?? 0) }} title={`${named(n)}: ${took(n.estimate_ms ?? 0)}`} />;
            })}
          </div>
          <span>Could be<b>{took(could)}</b></span>
          <div className="fx-lanes" role="img" aria-label={`could be: ${took(could)}`}>
            {lanes.filter((l) => l.length).map((l, i) => (
              <div key={i} className="fx-lane">
                {l.map((b) => <i key={b.id} className={`fx-seg ${b.kind}${b.est ? " est" : ""}`}
                  style={{ left: pct(b.from), width: pct(b.ms) }} />)}
              </div>
            ))}
          </div>
        </div>
        {saved > 0 && <p className="fx-saving"><b>{took(saved)}</b> faster if every call started as soon as it could</p>}
      </div>
      {(flow.advice ?? []).length > 0 && (
        <div className="sp-sec">
          <span className="sp-sh">Advice</span>
          {(flow.advice ?? []).map((a) => (
            <div key={a.nodes.join()} className="fx-advice">
              <button type="button" className="fx-card" onMouseEnter={() => onPoint(a.nodes)} onMouseLeave={() => onPoint(null)}
                onFocus={() => onPoint(a.nodes)} onBlur={() => onPoint(null)}
                aria-label={`Start these ${a.nodes.length} together, ${seconds(a.saved_ms)} faster`}>
                <span className="fx-title">Start these {a.nodes.length} together <em>−{seconds(a.saved_ms)}</em></span>
                <span className="fx-text">{a.text}</span>
                <span className="fx-chips">{a.nodes.map((id) => {
                  const n = flow.nodes.find((x) => x.id === id);
                  return <i key={id}>{n ? named(n) : id}</i>;
                })}</span>
                <span className="fx-refs">{a.refs.join(", ")}</span>
              </button>
              {a.caveat && <p className="fx-caveat">{a.caveat}</p>}
            </div>
          ))}
        </div>
      )}
      {path.length > 0 && (
        <div className="sp-sec">
          <span className="sp-sh">Critical path</span>
          <p className="fx-cp"><b>{path.map((n) => named(n!)).join(" → ")}</b>, {took(could)}.
            {slowest && <> Slowest: <b>{named(slowest)}</b> ({slowest.title}), {took(slowest.estimate_ms ?? 0)} ({slowest.estimate_source === "measured"
              ? "measured by the last check" : "an estimate"}).</>}
          </p>
        </div>
      )}
    </section>
  );
}
