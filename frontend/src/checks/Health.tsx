// The pieces of health (D24) shared by the map, the step panel and the Checks page: one square per check,
// the plain-words counts, and the yes before MCP servers start.
import type { CSSProperties } from "react";
import type { HealthStatus } from "../api/types";
import { Icons } from "../components/icons";
import type { Asking, LiveStatus } from "./useChecks";
import "./checks.css";

export function took(ms: number | null | undefined): string {
  if (ms === null || ms === undefined) return "";
  return ms < 1000 ? `${Math.round(ms)} ms` : `${(ms / 1000).toFixed(1)} s`;
}

export const WORD: Record<LiveStatus, string> = {
  up: "Up", warn: "Needs a look", down: "Down", skipped: "Not checked", unchecked: "Not checked yet",
  unconfirmed: "Not checked", checking: "Checking",
};

/** "3 up, 1 needs a look, 1 down": the counts that matter, in plain words. */
export function countsText(statuses: LiveStatus[]): string {
  const n = (s: LiveStatus) => statuses.filter((x) => x === s).length;
  const parts = [`${n("up")} up`];
  if (n("warn")) parts.push(`${n("warn")} need${n("warn") === 1 ? "s" : ""} a look`);
  if (n("down")) parts.push(`${n("down")} down`);
  return parts.join(", ");
}

const RANK: Record<LiveStatus, number> = { down: 0, warn: 1, checking: 2, skipped: 3, unchecked: 4, up: 5, unconfirmed: 6 };

/** Problems first (down, then needs a look), then by name. */
export function byProblem<T extends { status: LiveStatus; name: string }>(items: T[]): T[] {
  return [...items].sort((a, b) => RANK[a.status] - RANK[b.status] || a.name.localeCompare(b.name));
}

export function Squares({ statuses, label, size }: { statuses: LiveStatus[]; label: string; size?: "big" | "tall" }) {
  return (
    <span className={`hsq-strip${size ? ` ${size}` : ""}`} role="img" aria-label={label}>
      {statuses.map((s, i) => <i key={i} className={`sq ${s}`} />)}
    </span>
  );
}

export function Dot({ status, style }: { status: LiveStatus; style?: CSSProperties }) {
  return <span className={`hdot ${status}`} style={style} aria-hidden="true" />;
}

/** Under a block on the map: its latency, or a few words when there is none. */
export function caption(status: LiveStatus, summary: string, latency: number | null | undefined): string {
  if (status === "checking") return "checking…";
  if (status === "unchecked" || status === "unconfirmed" || status === "skipped") return "";
  const ms = took(latency);
  // the warning without a repeat of the latency already shown ("slow to start: 6.8 s" → "slow to start")
  const warning = (summary.split(", but ")[1] ?? "").replace(/: [\d.]+ m?s$/, "");
  const note = summary.includes("needs a key") ? "needs a key" : status === "warn" ? warning : "";
  if (status === "down") return summary.toLowerCase();
  return [ms, note].filter(Boolean).join(" · ");
}

/** The first Check now that would start MCP servers: what starts, from where, and a yes (D24). */
export function CheckConfirm({ asking, others, onStart, onWithout, onCancel }: {
  asking: Asking; others: number; onStart: () => void; onWithout: () => void; onCancel: () => void;
}) {
  const n = asking.plan.starts.length;
  return (
    <section className="hc-confirm" aria-label="Before checking">
      <h3>Checking starts {n} MCP server{n === 1 ? "" : "s"} on this computer</h3>
      <p>Each one starts in the repo folder, lists its tools, and stops. They get none of your environment variables or keys.</p>
      <div className="hc-cmds" role="list">
        {asking.plan.starts.map((s) => (
          <div key={s.id} className="hc-cmd" role="listitem">
            <b>{s.name}</b>
            <code>{s.command}</code>
            <span className={`hc-from${s.origin.includes("this repo") ? " repo" : ""}`}>{s.origin}</span>
            {s.source && <span className="hc-src">{s.source}</span>}
          </div>
        ))}
      </div>
      <ul className="hc-promise">
        {others > 0 && <li>{Icons.check(16)}{others} other{others === 1 ? "" : "s"} get one request each, or are only looked for, without keys</li>}
        <li>{Icons.check(16)}No code or key leaves this computer</li>
      </ul>
      <div className="hc-actions">
        <button className="btn primary" type="button" onClick={onStart}>Start them and check</button>
        <button className="btn" type="button" onClick={onWithout}>Check without them</button>
        <button className="btn ghost" type="button" onClick={onCancel}>Cancel</button>
      </div>
    </section>
  );
}

export type { HealthStatus };
