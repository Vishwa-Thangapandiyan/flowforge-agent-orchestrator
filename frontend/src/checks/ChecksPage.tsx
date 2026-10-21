// The Checks page (D24, docs/design/checks-artboards): is everything the app depends on up, fast and safe to call?
// Problems first, each in plain words with its likely fix; one dependency's history beside it.
import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useApi } from "../api/client";
import type { CheckRecord, ConnectorType, NodeKind } from "../api/types";
import { BrandTile } from "../brand/BrandTile";
import { clock, when } from "../components/format";
import { Icons } from "../components/icons";
import { EmptyState, ErrorBox } from "../components/ui";
import { byProblem, CheckConfirm, countOf, countsText, Dot, isProblem, Squares, took, WORD } from "./Health";
import { useChecks, type LiveItem } from "./useChecks";

const TILE: Partial<Record<NodeKind, ConnectorType>> = { llm: "llm", api: "http", mcp: "mcp", local: "local" };
const KIND: Partial<Record<NodeKind, string>> = { llm: "LLM", api: "API", mcp: "MCP server", local: "Local program" };

function Tile({ item, size = 26 }: { item: LiveItem; size?: number }) {
  return <BrandTile c={{ id: item.catalog ?? item.id, type: TILE[item.kind] ?? "http", name: item.name }} size={size} />;
}

function History({ item }: { item: LiveItem }) {
  const history = useApi<CheckRecord[]>(`/checks/${encodeURIComponent(item.id)}`);
  const fix = history.data?.find((h) => h.fix)?.fix ?? item.fix;
  return (
    <section className="ck-side" aria-label={`${item.name} history`}>
      <header><b><Tile item={item} />{item.name}</b></header>
      {history.data && history.data.length === 0 && <p style={{ padding: "12px 16px", margin: 0, color: "var(--muted)" }}>Not checked yet.</p>}
      <ul className="ck-tl">
        {history.data?.map((h) => (
          <li key={`${h.run_id}-${h.at}`}>
            <Dot status={h.status} />
            <span><b>{h.summary}</b>{h.reason && <p>{h.reason}</p>}</span>
            <time dateTime={h.at}>{when(h.at)}</time>
          </li>
        ))}
      </ul>
      {fix && history.data?.[0]?.status !== "up" && <p className="hc-fix"><span>Likely fix</span>{fix}</p>}
    </section>
  );
}

export function ChecksPage() {
  const checks = useChecks();
  const [problems, setProblems] = useState(false);
  const [picked, setPicked] = useState<string | null>(null);
  const sorted = useMemo(() => byProblem(checks.items), [checks.items]);
  const problemCount = sorted.filter((i) => isProblem(i.status)).length;
  const rows = problems ? sorted.filter((i) => isProblem(i.status)) : sorted;
  const selected = sorted.find((i) => i.id === picked) ?? sorted.find((i) => isProblem(i.status)) ?? sorted[0];
  const view = checks.view;

  const head = (
    <div className="page-head">
      <div className="titles">
        <h1>Checks</h1>
        <p className="lede">{view?.example ? "Example results: nothing was sent anywhere." : "Is everything your app depends on up, fast and safe to call?"}</p>
      </div>
      {sorted.length > 0 && (
        <button className="btn primary" type="button" onClick={() => void checks.checkNow()} disabled={checks.running}>
          {Icons.activity(18)} {checks.running ? `Checking… ${checks.progress?.done ?? 0} of ${checks.progress?.total ?? 0}` : "Check now"}
        </button>
      )}
    </div>
  );
  if (checks.loadError) return <div className="ck">{head}<ErrorBox error={checks.loadError} what="the checks" /></div>;
  if (!view) return <div className="ck" aria-busy="true">{head}</div>;
  if (sorted.length === 0) {
    return (
      <div className="ck">{head}
        <EmptyState tone="teal" icon={Icons.activity(28)} title="Nothing to check yet"
          action={<Link className="btn primary" to="/">Scan a folder</Link>}>
          Checks need a map: scan a folder first, then check what it depends on.
        </EmptyState>
      </div>
    );
  }
  const statuses = sorted.map((i) => i.status);
  const n = (s: LiveItem["status"]) => countOf(statuses, s);
  return (
    <div className="ck">
      {head}
      {checks.asking && (
        <div style={{ borderRadius: "var(--r-lg)", overflow: "hidden", border: "1px solid var(--line)" }}>
          <CheckConfirm asking={checks.asking} onStart={checks.confirm} onWithout={checks.withoutStarts} onCancel={checks.cancel} />
        </div>
      )}
      {checks.error && <div className="notice" role="alert">{checks.error}</div>}
      <div className="ck-overview">
        <Squares statuses={statuses} size="big" label={countsText(statuses)} />
        <span className="ck-counts">
          {n("down") > 0 && <span><b style={{ color: "var(--coral)" }}>{n("down")}</b> down</span>}
          {n("warn") > 0 && <span><b style={{ color: "var(--amber)" }}>{n("warn")}</b> need{n("warn") === 1 ? "s" : ""} a look</span>}
          <span><b>{n("up")}</b> up</span>
        </span>
        <span className="ck-when">{view.checked_at
          ? `last check ${when(view.checked_at)}${view.took_ms ? `, took ${took(view.took_ms)}` : ""}` : "never checked"}</span>
      </div>
      <div className="ck-split">
        <div className="ck-table-wrap">
          <div className="ck-bar">
            <span className="seg" role="group" aria-label="Which dependencies">
              <button type="button" aria-pressed={!problems} onClick={() => setProblems(false)}>All {sorted.length}</button>
              <button type="button" aria-pressed={problems} onClick={() => setProblems(true)}>Problems {problemCount}</button>
            </span>
            <small>Problems first, then by name</small>
          </div>
          <table>
            <thead><tr><th scope="col">Dependency</th><th scope="col">Result</th><th scope="col" className="ck-lat">Latency</th><th scope="col">Last checks</th><th scope="col">Checked</th></tr></thead>
            <tbody>
              {rows.map((i) => (
                <tr key={i.id} className={i.id === selected?.id ? "sel" : undefined}>
                  <th scope="row">
                    <button className="ck-name" type="button" onClick={() => setPicked(i.id)} aria-pressed={i.id === selected?.id}>
                      <Dot status={i.status} /><Tile item={i} />
                      <span><b>{i.name}</b><small>{KIND[i.kind] ?? i.kind}</small></span>
                    </button>
                  </th>
                  <td className={`ck-res ${i.status}`}>{i.status === "down" ? `${WORD.down}: ${i.summary}` : i.summary}</td>
                  <td className={`ck-lat${i.latency_ms ? "" : " none"}`}>{took(i.latency_ms) || "–"}</td>
                  <td><Squares statuses={i.history} size="tall" label={`last ${i.history.length} checks: ${countsText(i.history)}`} /></td>
                  <td className={`ck-at${i.at ? "" : " none"}`}>{i.at ? clock(i.at) : "–"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {selected && <History key={selected.id} item={selected} />}
      </div>
      <div className="ck-foot">
        <span>Checks use no keys. Results stay on this computer.</span>
        <Link to="/runs">Workflow runs (advanced)</Link>
      </div>
    </div>
  );
}
