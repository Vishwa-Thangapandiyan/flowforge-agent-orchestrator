import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, useApi } from "../api/client";
import type { RunSummary } from "../api/types";
import { BrandTile } from "../brand/BrandTile";
import { count, seconds, shortId, when } from "../components/format";
import { Icons } from "../components/icons";
import { useMeta } from "../components/Shell";
import { runTone } from "../components/status";
import { RunsSummary } from "../components/RunsSummary";
import { CardSkeleton, Chip, EmptyState, ErrorBox } from "../components/ui";
import type { Connector } from "../api/types";

type Filter = "all" | "succeeded" | "failed" | "waiting";
const FILTERS: { id: Filter; label: string; soon?: string }[] = [
  { id: "all", label: "All" },
  { id: "succeeded", label: "Succeeded" },
  { id: "failed", label: "Failed" },
  { id: "waiting", label: "Waiting for you", soon: "Approval gates arrive in Phase 5" },
];
const PAGE = 25;

export function RunHistory() {
  const meta = useMeta();
  const [filter, setFilter] = useState<Filter>("all");
  const query = `/runs?limit=${PAGE}${filter === "all" ? "" : `&status=${filter}`}`;
  const runs = useApi<RunSummary[]>(query, 3000);
  const connectors = useApi<Connector[]>("/connectors");
  const [older, setOlder] = useState<RunSummary[]>([]);
  const [exhausted, setExhausted] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  useEffect(() => {
    setOlder([]);
    setExhausted(false);
  }, [filter]);

  const list = [...(runs.data ?? []), ...older.filter((o) => !runs.data?.some((r) => r.id === o.id))];
  const failed = list.find((r) => r.status === "failed" || r.status === "error" || r.status === "interrupted");
  const byId = Object.fromEntries((connectors.data ?? []).map((c) => [c.id, c]));

  async function more() {
    const last = list[list.length - 1];
    if (!last) return;
    setLoadingMore(true);
    try {
      const next = await api.get<RunSummary[]>(`${query}&before=${encodeURIComponent(last.started_at)}`);
      setOlder((o) => [...o, ...next]);
      if (next.length < PAGE) setExhausted(true);
    } finally {
      setLoadingMore(false);
    }
  }

  return (
    <>
      <header className="page-head">
        <div className="titles">
          <span className="eyebrow">{meta.project}</span>
          <h1>Runs</h1>
        </div>
        <Link to="/live" className="btn primary">{Icons.play(18)} Start a run</Link>
      </header>

      <RunsSummary />

      <header className="page-head">
        <h2>History</h2>
        <div className="actions" role="group" aria-label="Show runs">
          {FILTERS.map((f) => (
            <button key={f.id} type="button" className="filter" aria-pressed={filter === f.id} disabled={!!f.soon}
              title={f.soon} onClick={() => setFilter(f.id)}>
              {f.label}
            </button>
          ))}
        </div>
      </header>

      {runs.error ? <ErrorBox error={runs.error} what="run history" /> : !runs.data ? <CardSkeleton lines={6} /> : list.length === 0 ? (
        <EmptyState icon={Icons.history(30)} title={filter === "all" ? "No runs yet" : `No ${filter} runs`}
          action={<Link to="/live" className="btn primary">{Icons.play(18)} Start a run</Link>}>
          Every run is stored with its events, after keys are removed, so you can look back at what happened.
        </EmptyState>
      ) : (
        <section className="card raised" style={{ padding: "8px 20px 20px" }}>
          <div className="table-wrap">
            <table className="data" style={{ minWidth: 820 }}>
              <thead>
                <tr>
                  <th scope="col">Run</th><th scope="col">Plan</th><th scope="col">Status</th>
                  <th scope="col">Time</th><th scope="col">Skipped by cache</th><th scope="col">Tokens</th>
                </tr>
              </thead>
              <tbody>
                {list.map((r) => {
                  const [tone, word] = runTone(r.status);
                  return (
                    <tr key={r.id}>
                      <td>
                        <Link to={`/runs/${r.id}`} className="mono" style={{ fontSize: 14 }}>{shortId(r.id)}</Link>
                        <div className="card-note">{when(r.started_at)}</div>
                      </td>
                      <td>
                        <div>{r.plan}</div>
                        <div style={{ display: "flex", gap: 4, marginTop: 6 }} aria-label="Apps used">
                          {r.connectors.slice(0, 6).map((id) => (
                            <span key={id} title={byId[id]?.name ?? id}>
                              <BrandTile c={byId[id] ?? { id, name: id, type: "local" }} size={20} />
                            </span>
                          ))}
                        </div>
                      </td>
                      <td><Chip tone={tone} dot pulse={r.status === "running"}>{word}</Chip></td>
                      <td className="num">{r.status === "running" ? "running…" : seconds(r.time_ms)}</td>
                      <td className="num">{count(r.cache_hits)}</td>
                      <td className="num">{count(r.tokens)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          {!exhausted && list.length >= PAGE && (
            <button type="button" className="btn" style={{ alignSelf: "flex-start" }} onClick={more} disabled={loadingMore}>
              {loadingMore ? "Loading…" : "Show older runs"}
            </button>
          )}
        </section>
      )}

      {failed?.failure_reason && (
        <section className="card" style={{ background: "var(--coral-bg)", borderColor: "transparent" }} aria-label="Why it failed">
          <b style={{ color: "var(--coral)" }}>Why run <Link to={`/runs/${failed.id}`}>{shortId(failed.id)}</Link> {failed.status === "interrupted" ? "was interrupted" : "failed"}</b>
          <span>{failed.failure_reason}</span>
          <span className="card-note">Failures show the real reason in plain words, and skip only the steps that depended on it.</span>
        </section>
      )}
      <p className="card-note">
        {meta.example ? "Example data. " : ""}Every run is stored with its redacted events, so nothing here contains a key.
      </p>
    </>
  );
}
