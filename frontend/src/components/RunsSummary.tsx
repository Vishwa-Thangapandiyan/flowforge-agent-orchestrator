// Money and time, and tool health: what the old Overview showed, now at the top of Runs (D17).
import type { CSSProperties } from "react";
import { Link } from "react-router-dom";
import { useApi } from "../api/client";
import type { Connector, Health, Savings } from "../api/types";
import { BrandTile } from "../brand/BrandTile";
import { count, seconds } from "./format";
import { healthTone } from "./status";
import { CardSkeleton, CountUp, Stat } from "./ui";

export function RunsSummary() {
  const connectors = useApi<Connector[]>("/connectors", 8000);
  const health = useApi<Health[]>("/health/tools", 4000);
  const savings = useApi<Savings>("/stats/savings", 5000);
  const needs = (health.data ?? []).filter((h) => h.status === "missing_key" || h.status === "failing");

  return (
    <div className="grid" style={{ "--min": "320px" } as CSSProperties}>
      {savings.data ? (
        <section className="card rise rise-1" aria-labelledby="money-title">
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

      {health.data ? (
        <section className="card rise rise-2" aria-labelledby="health-title">
          <h2 id="health-title">App health</h2>
          <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
            {health.data.map((h) => (
              <li key={h.id} className="row" style={{ alignItems: "center" }}>
                <Link to={`/connectors/${h.id}`} style={{ display: "flex", gap: 10, alignItems: "center", color: "var(--fg)", textDecoration: "none" }}>
                  <BrandTile c={connectors.data?.find((c) => c.id === h.id) ?? { id: h.id, name: h.name, type: h.type }} size={26} />
                  {h.name}
                </Link>
                <span style={{ textAlign: "right" }}>
                  <b style={{ color: `var(--${healthTone(h.status)})` }}>{h.label}</b>
                  {h.rate && <span className="card-note" style={{ display: "block" }}>{h.rate.left} of {h.rate.rpm} calls left this minute</span>}
                </span>
              </li>
            ))}
          </ul>
          {needs.length > 0 && <span className="card-note">{needs.length} app{needs.length > 1 ? "s need" : " needs"} a key or a look. See api-connect.md.</span>}
        </section>
      ) : <CardSkeleton lines={5} />}
    </div>
  );
}
