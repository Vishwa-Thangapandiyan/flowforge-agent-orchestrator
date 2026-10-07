import type { CSSProperties } from "react";
import { Link } from "react-router-dom";
import { useApi } from "../api/client";
import type { Connector, Health, RunSummary, Savings } from "../api/types";
import { BrandTile } from "../brand/BrandTile";
import { count, seconds } from "../components/format";
import { HubMap } from "../components/HubMap";
import { Icons } from "../components/icons";
import { useMeta } from "../components/Shell";
import { healthTone, runTone } from "../components/status";
import { CardSkeleton, Chip, CountUp, ErrorBox, Stat } from "../components/ui";

export function Overview() {
  const meta = useMeta();
  const connectors = useApi<Connector[]>("/connectors", 8000);
  const health = useApi<Health[]>("/health/tools", 4000);
  const runs = useApi<RunSummary[]>("/runs?limit=20", 3000);
  const savings = useApi<Savings>("/stats/savings", 5000);

  const healthById = Object.fromEntries((health.data ?? []).map((h) => [h.id, h]));
  const running = (runs.data ?? []).filter((r) => r.status === "running");
  const active = new Set(running.flatMap((r) => r.connectors));
  const last = (runs.data ?? []).find((r) => r.status !== "running");
  const needs = (health.data ?? []).filter((h) => h.status === "missing_key" || h.status === "failing");

  return (
    <>
      <header className="page-head">
        <div className="titles">
          <span className="eyebrow">Project</span>
          <h1>{meta.project}</h1>
        </div>
        <div className="actions">
          {running.length > 0 ? (
            <Link to={`/runs/${running[0].id}`} className="chip tone-blue" style={{ minHeight: 32 }}>
              <span className="dot heartbeat" aria-hidden="true" /> {running[0].plan} is running
            </Link>
          ) : last ? (
            <Chip tone={runTone(last.status)[0]} dot>
              Last run {runTone(last.status)[1]} · {seconds(last.time_ms)}
            </Chip>
          ) : null}
          <Link to="/plans" className="btn">Review next plan</Link>
          <Link to="/live" className="btn primary">{Icons.play(18)} Start a run</Link>
        </div>
      </header>

      <section className="card raised rise">
        <div className="card-head">
          <h2>Connected apps</h2>
          <span className="card-note">Click a box to look inside. Every line goes through FlowForge.</span>
        </div>
        {connectors.error ? <ErrorBox error={connectors.error} what="your apps" /> : connectors.data ? (
          <HubMap project={meta.project} connectors={connectors.data} health={healthById} active={active} />
        ) : (
          <div className="skeleton" style={{ height: 300 }} />
        )}
      </section>

      <div className="grid" style={{ "--min": "300px" } as CSSProperties}>
        {health.data ? (
          <section className="card rise rise-1" aria-labelledby="health-title">
            <h2 id="health-title">Tool health</h2>
            <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
              {health.data.map((h) => (
                <li key={h.id} className="row" style={{ alignItems: "center" }}>
                  <span style={{ display: "flex", gap: 10, alignItems: "center", color: "var(--fg)" }}>
                    <BrandTile c={connectors.data?.find((c) => c.id === h.id) ?? { id: h.id, name: h.name, type: h.type }} size={26} />
                    {h.name}
                  </span>
                  <span style={{ textAlign: "right" }}>
                    <b style={{ color: `var(--${healthTone(h.status)})` }}>{h.label}</b>
                    {h.rate && <span className="card-note" style={{ display: "block" }}>{h.rate.left} of {h.rate.rpm} calls left this minute</span>}
                  </span>
                </li>
              ))}
            </ul>
          </section>
        ) : <CardSkeleton lines={5} />}

        {savings.data ? (
          <section className="card rise rise-2" aria-labelledby="money-title">
            <h2 id="money-title">Money and time</h2>
            <div className="stats" style={{ gridTemplateColumns: "repeat(2, minmax(0, 1fr))" }}>
              <Stat tone="teal" value={<CountUp value={savings.data.time_saved_ms} format={(v) => seconds(v)} />} label="saved vs one at a time" />
              <Stat tone="blue" value={<CountUp value={savings.data.calls_skipped} format={count} />} label="calls skipped by cache" />
              <Stat tone="violet" value={<CountUp value={savings.data.tokens} format={count} />} label="tokens used" />
              <Stat tone="amber" value={<CountUp value={savings.data.credits} format={count} />} label="credits used" />
            </div>
            <span className="card-note">Across {count(savings.data.runs)} finished run{savings.data.runs === 1 ? "" : "s"}.</span>
          </section>
        ) : <CardSkeleton lines={4} />}

        <section className="card rise rise-3" aria-labelledby="needs-title">
          <h2 id="needs-title">Needs you</h2>
          {needs.map((h) => (
            <Link key={h.id} to={`/connectors/${h.id}`} className="needs-item"
              style={{ background: h.status === "failing" ? "var(--coral-bg)" : "var(--amber-bg)" }}>
              <b>{h.status === "failing" ? `${h.name} is failing` : `${h.name} has no key yet`}</b>
              <span>{h.status === "failing" ? h.last_error ?? h.label : "Add it to .env, then restart FlowForge. See api-connect.md."}</span>
            </Link>
          ))}
          {needs.length === 0 && health.data && (
            <p className="card-note" style={{ display: "flex", gap: 8, alignItems: "center" }}>
              <span style={{ color: "var(--teal)" }}>{Icons.check(18)}</span> Nothing needs you right now.
            </p>
          )}
          <p className="card-note">Payments and code changes will wait for your approval here once approval gates arrive in Phase 4.</p>
        </section>
      </div>
      {meta.example && <p className="card-note">Example data. Real numbers come from your own runs.</p>}
    </>
  );
}
