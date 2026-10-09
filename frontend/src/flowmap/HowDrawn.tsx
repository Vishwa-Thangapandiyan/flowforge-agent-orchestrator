// How the Planner drew the map (D17, docs/design/flow-map-artboards/Planner): its stages, a short log, the
// files it read, the calls it traced, and what it dropped. The engine behind the Planner is never named.
import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useApi } from "../api/client";
import type { Analysis, Connector, FlowResponse } from "../api/types";
import { BrandTile } from "../brand/BrandTile";
import { Icons } from "../components/icons";
import { CardSkeleton, EmptyState, ErrorBox, prefersReducedMotion } from "../components/ui";
import "./how.css";

export function HowDrawn() {
  const analysis = useApi<Analysis>("/flow/analysis");
  const flow = useApi<FlowResponse>("/flow?layer=planner");
  const connectors = useApi<Connector[]>("/connectors");
  const [t, setT] = useState(0);
  const [round, setRound] = useState(0);
  const total = useMemo(() => (analysis.data?.stages ?? []).reduce((a, s) => a + s.duration_ms, 0), [analysis.data]);

  useEffect(() => {
    if (!total) return;
    if (prefersReducedMotion()) { setT(total + 1); return; }
    const t0 = performance.now();
    let raf = 0;
    const step = (now: number) => {
      const next = now - t0;
      setT(next);
      if (next <= total) raf = requestAnimationFrame(step);
    };
    raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
  }, [total, round]);

  if (analysis.error) {
    return analysis.error.message.includes("hasn't drawn")
      ? <EmptyState tone="violet" icon={Icons.spark(28)} title="No map yet">The Planner maps your repo from Phase 5. Try <code>flowforge --example</code>.</EmptyState>
      : <ErrorBox error={analysis.error} what="how the map was drawn" />;
  }
  if (!analysis.data) return <CardSkeleton lines={8} />;
  const a = analysis.data;

  let acc = 0;
  let current = a.stages.length - 1;
  let p = 1;
  for (let i = 0; i < a.stages.length; i++) {
    const d = a.stages[i].duration_ms;
    if (d === 0 || t < acc + d) { current = i; p = d ? Math.min(1, Math.max(0, (t - acc) / d)) : 1; break; }
    acc += d;
  }
  const ready = current === a.stages.length - 1;
  const nodes = flow.data && flow.data.available ? flow.data.nodes : [];
  const shown = current > 3 ? nodes.length : current === 3 ? Math.round(nodes.length * p) : 0;
  const log = a.log.filter(([at]) => at <= t).slice(-10);
  const tileFor = (id: string) => connectors.data?.find((c) => c.id === id) ?? { id, type: "http" as const, name: id };

  return (
    <>
      <header className="page-head">
        <div className="titles">
          <span className="eyebrow">Map v{a.version} · {a.fact_sheet_hash}</span>
          <h1>{ready ? "How the Planner mapped your app" : "The Planner is mapping your app"}</h1>
          <p className="lede">It reads code and traces calls. It sees names, never key values.</p>
        </div>
        <div className="actions">
          <button className="btn" type="button" onClick={() => { setT(0); setRound((r) => r + 1); }}>{Icons.refresh(18)} Replay</button>
          <button className="btn" type="button" onClick={() => setT(total + 1)}>Skip to the end</button>
          <Link className="btn primary" to="/">Open the map</Link>
        </div>
      </header>

      <div className="how">
        <section className="how-stage card raised" aria-label="What the Planner is doing">
          {current === 0 && (
            <div className="how-files">
              {a.files.map((f, i) => (
                <span key={f} className={`how-file${p * a.files.length > i ? " lit" : ""}`}>{Icons.file(14)}{f}</span>
              ))}
            </div>
          )}
          {current === 1 && (
            <div className="how-box">
              <span className="eyebrow">Sandbox · test mode</span>
              <h2>Running the app on {Math.round(40 * p)} of 40 test orders</h2>
              <div className="fm-prog" style={{ width: "100%", height: 8 }}><span style={{ width: `${Math.round(p * 100)}%`, background: "var(--blue)" }} /></div>
              <p className="card-note">Payments in test mode · email goes to a local sink · no real customer data</p>
            </div>
          )}
          {current === 2 && (
            <div className="how-apps">
              {a.calls.map((c) => (
                <div key={c.app} className={`how-app${c.none ? " none" : ""}`}>
                  <BrandTile c={tileFor(c.app)} size={36} />
                  <b>{tileFor(c.app).name}</b>
                  <span className="n">{Math.round(c.count * Math.min(1, p * 1.3))}</span>
                  <span className="m">{c.meta}</span>
                </div>
              ))}
            </div>
          )}
          {current >= 3 && (
            <div className="how-draft">
              <div className="how-chips">
                {nodes.slice(0, shown).map((n) => (
                  <span key={n.id} className={`how-chip k-${n.kind}${n.status === "unconfirmed" && current >= 4 ? " unc" : ""}`}>{n.title}</span>
                ))}
                {current >= 4 && a.dropped.map((d) => <span key={d.title} className="how-chip dropped" title={d.reason}>{d.title}</span>)}
              </div>
              {current >= 4 && (
                <ul className="how-checks" aria-label="Checks">
                  <li className="ok"><i>✓</i>No loops</li>
                  <li className="ok"><i>✓</i>Every app it uses is connected</li>
                  {a.dropped.map((d) => <li key={d.title} className="drop"><i>×</i>Dropped “{d.title}”: {d.reason}</li>)}
                  {nodes.filter((n) => n.status === "unconfirmed").map((n) => <li key={n.id} className="unc"><i>?</i>“{n.title}” is unconfirmed</li>)}
                  <li className="gate"><i>!</i>A gate in front of every payment and message, added by code</li>
                </ul>
              )}
            </div>
          )}
          {ready && <div className="how-ready" role="status"><b>Map v{a.version} is ready</b><Link className="btn primary" to="/">Open the map</Link></div>}
        </section>

        <aside className="how-side">
          <section className="card">
            <span className="eyebrow">Steps</span>
            <ol className="how-steps">
              {a.stages.map((s, i) => {
                const done = i < current || (i === current && ready);
                const doing = i === current && !done;
                return (
                  <li key={s.title} className={done ? "done" : doing ? "doing" : "todo"}>
                    <span className="d">{done ? Icons.check(14) : doing ? Icons.refresh(14) : i + 1}</span>
                    <span><b>{s.title}</b><small>{done ? s.done : doing ? `${s.doing}…` : "waiting"}</small></span>
                  </li>
                );
              })}
            </ol>
          </section>
          <section className="card">
            <span className="eyebrow">Live log</span>
            <div className="how-log" role="log" aria-live="polite">
              {log.map(([at, kind, text]) => <div key={at} className={kind}><b>{kind}</b><span>{text}</span></div>)}
            </div>
            <p className="how-priv">{Icons.shield(16)} The Planner sees names, never values. Only apps your code calls go on the map, and gates are added by code.</p>
          </section>
        </aside>
      </div>
    </>
  );
}
