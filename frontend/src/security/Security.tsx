// Security (D31): what the map's scan found unsafe. Counts by level, then one card per finding: where, the masked
// lines, the fix, a prompt for a coding agent, and the block on the map.
import { useState } from "react";
import { Link } from "react-router-dom";
import { useApi } from "../api/client";
import { Icons } from "../components/icons";
import { CardSkeleton, EmptyState, ErrorBox } from "../components/ui";
import "./security.css";

export type Level = "high" | "medium" | "low";

export interface Finding {
  id: string;
  kind: string;
  level: Level;
  title: string;
  ref: string;
  line: number;
  dep_id: string | null;
  first_line: number | null;
  excerpt: string[];
  fix: string;
  prompt: string;
}

export interface SecurityResponse {
  repo: string | null;
  scanned: boolean;
  summary: Partial<Record<Level, number>>;
  findings: Finding[];
}

export const LEVELS: Level[] = ["high", "medium", "low"];
const KIND: Record<string, string> = {
  key_in_code: "Key in code", key_in_config: "Key in a config", plain_http: "Plain http",
  unpinned_server: "MCP server not pinned", broad_files: "Reads every file",
};

/** The worst level among a dependency's findings, for the map's badge. */
export function worst(findings: Finding[]): Level | undefined {
  return LEVELS.find((l) => findings.some((f) => f.level === l));
}

function Card({ f }: { f: Finding }) {
  const [said, setSaid] = useState<string>();
  const copy = () => {
    navigator.clipboard.writeText(f.prompt).then(() => setSaid("Copied"), () => setSaid("Couldn't copy"));
    window.setTimeout(() => setSaid(undefined), 2500);
  };
  return (
    <li className={`sec-card lv-${f.level}`} id={f.id}>
      <div className="sec-main">
        <span className={`sec-level lv-${f.level}`}>{f.level} · {KIND[f.kind] ?? f.kind}</span>
        <h3>{f.title}</h3>
        <span className="sec-ref">{f.ref}</span>
        {f.excerpt.length > 0 && (
          <pre className="sec-code" aria-label={`The code at ${f.ref}`}>
            {f.excerpt.map((text, i) => {
              const n = (f.first_line ?? f.line) + i;
              return <span key={n} className={n === f.line ? "hl" : undefined}><i>{n}</i>{text}{"\n"}</span>;
            })}
          </pre>
        )}
      </div>
      <div className="sec-side">
        <p className="sec-fix"><b>Fix</b>{f.fix}</p>
        <div className="sec-acts">
          <button className="btn" type="button" onClick={copy}>{Icons.copy(15)} Copy prompt for your agent</button>
          {f.dep_id && <Link className="btn" to={`/?focus=${encodeURIComponent(f.dep_id)}`}>{Icons.map(15)} Show on map</Link>}
          <span className="sec-said" aria-live="polite">{said}</span>
        </div>
      </div>
    </li>
  );
}

export function Security() {
  const data = useApi<SecurityResponse>("/security");
  if (data.error) return <ErrorBox error={data.error} what="the security findings" />;
  if (!data.data) return <CardSkeleton lines={6} />;
  const s = data.data;
  return (
    <>
      <header className="page-head">
        <div className="titles">
          <span className="eyebrow">From your code · nothing sent</span>
          <h1>Security</h1>
          <p className="lede">Catches known key formats and these patterns, not everything. Values are never shown.</p>
        </div>
      </header>
      {!s.scanned ? (
        <EmptyState tone="teal" icon={Icons.shield(30)} title="Scan a folder first">
          Findings come from the same scan as the map.
        </EmptyState>
      ) : (
        <>
          <div className="sec-counts" role="list" aria-label="Findings by level">
            {LEVELS.map((l) => (
              <div key={l} role="listitem" className={`sec-count lv-${l}`}>
                <span className={`sec-level lv-${l}`}>{l}</span>
                <b>{s.summary[l] ?? 0}</b>
              </div>
            ))}
          </div>
          {s.findings.length === 0 ? (
            <EmptyState tone="teal" icon={Icons.check(30)} title={`Nothing found in ${s.repo ?? "this folder"}`}>
              No known key formats, plain http or risky MCP servers.
            </EmptyState>
          ) : (
            <ul className="sec-list">{s.findings.map((f) => <Card key={f.id} f={f} />)}</ul>
          )}
        </>
      )}
    </>
  );
}
