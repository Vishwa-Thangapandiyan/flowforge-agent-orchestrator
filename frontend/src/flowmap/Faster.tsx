// The Faster panel (D25, D33): the two times first, as written and as early as inputs allow, then one card per piece
// of advice. The why, the critical path and the limits wait behind an ⓘ. Pointing at advice lights up its blocks.
import { useMemo, useState } from "react";
import type { Advice, FlowNode, FlowView } from "../api/types";
import { Icons } from "../components/icons";
import { took } from "../checks/Health";
import { actionName, CALL_KINDS, earliest } from "./kinds";

const seconds = (ms: number) => `${(ms / 1000).toFixed(1)} s`;
const LANES = 4;

function line(n: FlowNode): number {
  return Number(n.evidence[0]?.ref?.split(":").pop() ?? 0);
}


const LANGUAGE_NAMES: Record<string, string> = { dart: "Dart", javascript: "JavaScript", typescript: "TypeScript" };
const languageName = (l: string) => LANGUAGE_NAMES[l] ?? l;

export function Faster({ flow, onPoint, onWatch, watching = false, canWatch = false }: {
  flow: FlowView; onPoint: (ids: string[] | null) => void; onWatch?: () => void; watching?: boolean; canWatch?: boolean;
}) {
  // several entry points are separate actions: show the slowest one, the one the critical path runs through (D32)
  const entries = flow.nodes.filter((n) => n.kind === "start");
  const entry = entries.length > 1 ? flow.nodes.find((n) => n.id === flow.critical_path.path[0]) : undefined;
  const calls = useMemo(() => {
    let keep: Set<string> | null = null;
    if (entry) {
      keep = new Set([entry.id]);
      for (let grew = true; grew;) {
        grew = false;
        for (const e of flow.edges) if (keep.has(e.source) && !keep.has(e.target)) { keep.add(e.target); grew = true; }
      }
    }
    return flow.nodes.filter((n) => CALL_KINDS.has(n.kind) && (n.estimate_ms ?? 0) > 0 && (!keep || keep.has(n.id)))
      .sort((a, b) => line(a) - line(b));
  }, [flow.nodes, flow.edges, entry]);
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
  const path = flow.critical_path.path.map((id) => flow.nodes.find((n) => n.id === id)).filter((n) => n && CALL_KINDS.has(n.kind));
  const slowest = flow.nodes.find((n) => n.id === flow.critical_path.bottleneck);
  return (
    <section className="sp fx" aria-label="Faster">
      <div className="sp-sec">
        <h2 className="fx-h">Faster</h2>
        <p className="fx-big" aria-label={`${took(written)} as written, ${took(could)} at best`}>
          <b>{took(written)}</b><span aria-hidden="true">→</span><b className="could">{took(could)}</b>
        </p>
        <small className="fx-sub">{entry ? <>The slowest of {entries.length} actions, <b>{entry.title}</b>: its {calls.length} calls, </>
          : <>The same {calls.length} calls, </>}as written and as your dependencies allow.</small>
        <div className="fx-times">
          <span>As written</span>
          <div className="fx-lane" role="img" aria-label={`as written: ${took(written)}`}>
            {calls.map((n) => {
              const left = at;
              at += n.estimate_ms ?? 0;
              return <i key={n.id} className={`fx-seg ${n.kind}${n.estimate_source === "estimate" ? " est" : ""}`}
                style={{ left: pct(left), width: pct(n.estimate_ms ?? 0) }} title={`${actionName(n)}: ${took(n.estimate_ms ?? 0)}`} />;
            })}
          </div>
          <span>Could be</span>
          <div className="fx-lanes" role="img" aria-label={`could be: ${took(could)}`}>
            {lanes.filter((l) => l.length).map((l, i) => (
              <div key={i} className="fx-lane">
                {l.map((b) => <i key={b.id} className={`fx-seg ${b.kind}${b.est ? " est" : ""}`}
                  style={{ left: pct(b.from), width: pct(b.ms) }} />)}
              </div>
            ))}
          </div>
        </div>
        {onWatch && (
          <button type="button" className="btn fx-watch" onClick={onWatch} disabled={!canWatch || watching}>
            {Icons.play(16)} {watching ? "Playing…" : "Watch it run"}
          </button>
        )}
      </div>
      {(flow.advice ?? []).length > 0 && (
        <div className="sp-sec">
          <span className="sp-sh">Advice</span>
          {(flow.advice ?? []).map((a) => (
            <AdviceCard key={a.nodes.join()} a={a} flow={flow} onPoint={onPoint} />
          ))}
        </div>
      )}
      <details className="fx-more">
        <summary>{Icons.question(15)} About these numbers</summary>
        {saved > 0 && <p className="fx-cp"><b>{took(saved)}</b> faster if every call started as soon as it could.</p>}
        {path.length > 0 && (
          <p className="fx-cp">Critical path: <b>{path.map((n) => actionName(n!)).join(" → ")}</b>, {took(could)}.
            {slowest && <> Slowest: <b>{actionName(slowest)}</b> ({slowest.title}), {took(slowest.estimate_ms ?? 0)} ({slowest.estimate_source === "measured"
              ? "measured by the last check" : "an estimate"}).</>}
          </p>
        )}
        {(flow.patterns ?? []).length > 0 && (
          <p className="fx-limits">{flow.patterns!.map(languageName).join(", ")} read by patterns: less exact than Python.</p>
        )}
        <p className="fx-limits">Can't see: calls passed around as values, callbacks, or chosen at run time.</p>
      </details>
    </section>
  );
}

/** One piece of advice (D25), and how to act on it (D27): the change written out, and a prompt for a coding agent.
 * Both are text to copy; FlowForge never edits your code. */
function AdviceCard({ a, flow, onPoint }: { a: Advice; flow: FlowView; onPoint: (ids: string[] | null) => void }) {
  const [open, setOpen] = useState(false);
  const [said, setSaid] = useState<string>();
  const copy = (text: string) => {
    navigator.clipboard.writeText(text).then(() => setSaid("Copied"), () => setSaid("Couldn't copy: select the text instead"));
    window.setTimeout(() => setSaid(undefined), 2500);
  };
  const c = a.change;
  const last = c ? c.first_line + c.before.length - 1 : 0;
  return (
            <div className="fx-advice">
              <button type="button" className="fx-card" onMouseEnter={() => onPoint(a.nodes)} onMouseLeave={() => onPoint(null)}
                onFocus={() => onPoint(a.nodes)} onBlur={() => onPoint(null)}
                aria-label={`Start these ${a.nodes.length} together, ${seconds(a.saved_ms)} faster`}>
                <span className="fx-title">Start these {a.nodes.length} together <em>−{seconds(a.saved_ms)}</em></span>
                <span className="fx-chips">{a.nodes.map((id) => {
                  const n = flow.nodes.find((x) => x.id === id);
                  return <i key={id}>{n ? actionName(n) : id}</i>;
                })}</span>
              </button>
              <details className="fx-why">
                <summary>Why{a.caveat ? " · one catch" : ""}</summary>
                <p className="fx-text">{a.text}</p>
                {a.caveat && <p className="fx-caveat">{a.caveat}</p>}
                <p className="fx-refs">{a.refs.join(", ")}</p>
              </details>
              <div className="fx-do">
                <button type="button" className="fx-btn" aria-expanded={open} onClick={() => setOpen((v) => !v)}>
                  {Icons.code(15)} {open ? "Hide the change" : "Show the change"}
                </button>
                {a.prompt && (
                  <button type="button" className="fx-btn" onClick={() => copy(a.prompt!)} title="A prompt for your coding agent">
                    {Icons.copy(15)} Copy prompt
                  </button>
                )}
                <span className="fx-said" aria-live="polite">{said}</span>
              </div>
              {open && (
                <section className="fx-change" aria-label="The change">
                  {c ? (
                    <>
                      <div className="fx-ch-head">
                        <span>{c.path} · line{c.before.length > 1 ? `s ${c.first_line}–${last}` : ` ${c.first_line}`}</span>
                        {c.saved_ms < a.saved_ms && <em>−{seconds(c.saved_ms)} on its own</em>}
                      </div>
                      <span className="fx-ch-label">Now</span>
                      <pre className="fx-code now">{c.before.map((l, i) => (
                        <span key={i}><b>{c.first_line + i}</b>{l || " "}</span>
                      ))}</pre>
                      <span className="fx-ch-label">Could be</span>
                      <pre className="fx-code could">{c.after.map((l, i) => <span key={i}>{l || " "}</span>)}</pre>
                      <button type="button" className="fx-btn" onClick={() => copy(c.after.join("\n"))}>
                        {Icons.copy(15)} Copy the new code
                      </button>
                      {(c.import_text || c.needs_import) && (
                        <p className="fx-note">Add <code>{c.import_text ?? "import asyncio"}</code> at the top of {c.path}.</p>
                      )}
                      {c.by_hand.length > 0 && (
                        <div className="fx-note">
                          <b>Move by hand</b> (or copy the prompt):
                          <ul>{c.by_hand.map((h) => <li key={h}>{h}</li>)}</ul>
                        </div>
                      )}
                    </>
                  ) : (
                    <p className="fx-note">No safe change to write out here: the calls sit in different places, or code between them uses a result. Copy the prompt for your coding agent instead.</p>
                  )}
                  <p className="fx-note">FlowForge never edits your code: copy it, check it, run your tests.</p>
                </section>
              )}
            </div>
  );
}
