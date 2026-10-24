// The step panel (D17, D33): a warning if there is one, its health, then what it is. The code and your edits are
// folded away. Edits are saved on top of the map and never touch your code.
import { useEffect, useState, type FormEvent, type ReactNode } from "react";
import { useApi } from "../api/client";
import type { CheckRecord, Connector, Evidence, FlowNode, FlowView } from "../api/types";
import { BrandTile } from "../brand/BrandTile";
import { Dot, InternetWorks, took, WORD } from "../checks/Health";
import { type Finding } from "../security/Security";
import { type KeyInfo, KeyList } from "../security/Keys";
import { Link } from "../projects/links";
import "../security/security.css";
import type { LiveItem } from "../checks/useChecks";
import { when } from "../components/format";
import { Icons } from "../components/icons";
import type { TileSource } from "./nodes";
import type { NodeState } from "./replay";

const KIND_LABEL: Record<string, string> = {
  start: "Start", end: "End", api: "API call", mcp: "MCP tool", llm: "LLM call", local: "Local command", code: "Your code",
  decision: "Decision", fork: "Run together", join: "Wait for all", gate: "You approve",
};
const CALLS = new Set(["llm", "api", "mcp", "local"]);
const TYPE_FOR: Record<string, Connector["type"]> = { llm: "llm", api: "http", mcp: "mcp", local: "local" };

const RUN_TEXT: Partial<Record<NodeState, string>> = {
  running: "Running now", retry: "Server error. Trying again", waiting: "Waiting for you to approve",
  cached: "Answered from cache", skipped: "Not taken in this run",
};

export interface PanelActions {
  close: () => void;
  approve: () => void;
  reject: () => void;
  edit: (body: Record<string, unknown>) => Promise<void>;
  reset: (nodeId: string) => Promise<void>;
  dismissTip: (nodeId: string) => void;
}

interface Props {
  node: FlowNode;
  flow: FlowView;
  tile: TileSource | null;
  state: NodeState;
  cap: string;
  waiting: boolean;
  connectors: Connector[];
  tipShown: boolean;
  layer: "mine" | "planner";
  actions: PanelActions;
  /** a dependency's latest check (D24) */
  health?: LiveItem;
  /** how many other dependencies answered in the last check: a down one then isn't your connection */
  othersUp?: number;
  example?: boolean;
  checking?: boolean;
  onCheck?: (id: string) => void;
  /** its security findings (D31) */
  findings?: Finding[];
  /** the keys it reads, and whether FlowForge has them (D36) */
  keys?: KeyInfo[];
  onKeySaved?: () => void;
}

const HISTORY_BARS = 8;

/** The verdict first, in the dependency's own words, then a likely fix and the last checks (D24). */
function Health({ item, othersUp, example, checking, onCheck }: { item: LiveItem; othersUp?: number; example?: boolean;
  checking?: boolean; onCheck?: (id: string) => void }) {
  const checked = !["unchecked", "unconfirmed", "checking"].includes(item.status);
  const history = useApi<CheckRecord[]>(checked ? `/checks/${encodeURIComponent(item.id)}?limit=${HISTORY_BARS}` : null);
  const bars = [...(history.data ?? [])].reverse();
  const max = Math.max(1, ...bars.map((b) => b.latency_ms ?? 0));
  const verdict = item.status === "down" ? `${WORD.down}: ${item.summary}` : item.summary;
  return (
    <div className="sp-sec">
      <span className="sp-sh">Health</span>
      <div className="sp-verdict"><Dot status={item.status} style={{ width: 12, height: 12 }} />
        <span>{verdict}
          {checked && <small>{[example ? "example result" : null, item.at ? `checked ${when(item.at)}` : null,
            item.latency_ms ? `took ${took(item.latency_ms)}` : null].filter(Boolean).join(" · ")}</small>}
        </span>
      </div>
      {item.reason && <p className={`sp-reason ${item.status}`}>{item.reason}</p>}
      <InternetWorks item={item} othersUp={othersUp} />
      {item.fix && <p className="hc-fix"><span>Likely fix</span>{item.fix}</p>}
      {bars.length > 1 && (
        <div className="sp-bars" role="img" aria-label={`last ${bars.length} checks`}>
          {bars.map((b) => <i key={`${b.run_id}-${b.at}`} className={b.status}
            style={{ height: b.latency_ms ? `${Math.max(14, (b.latency_ms / max) * 100)}%` : undefined }} title={`${b.summary} · ${when(b.at)}`} />)}
        </div>
      )}
      {onCheck && item.status !== "unconfirmed" && (
        <div className="sp-row">
          <button className="btn" type="button" onClick={() => onCheck(item.id)} disabled={checking}>
            {Icons.activity(16)} {item.status === "checking" ? "Checking…" : "Check this one"}
          </button>
        </div>
      )}
    </div>
  );
}

function EvidenceItem({ ev }: { ev: Evidence }) {
  if (ev.type === "code") {
    const first = ev.first_line ?? 1;
    return (
      <div className="sp-ev">
        <div className="sp-evh">{Icons.file(14)}<span>{ev.ref}</span><em>found in your code</em></div>
        {ev.lines.length > 0 && (
          <div className="sp-code">
            {ev.lines.map((line, i) => (
              <div key={i} className={`sp-cl${first + i === ev.highlight ? " hl" : ""}`}><b>{first + i}</b><span>{line}</span></div>
            ))}
          </div>
        )}
      </div>
    );
  }
  const icon: Record<string, ReactNode> = {
    trace: Icons.activity(15), policy: Icons.shield(15), env_name: Icons.key(15), missing: Icons.question(15), user: Icons.pencil(15),
  };
  return (
    <div className={`sp-evl ${ev.type}`}>
      {icon[ev.type]}
      <span>{ev.ref && ev.type === "env_name" ? <><code>{ev.ref}</code> · </> : null}{ev.text}</span>
    </div>
  );
}

export function StepPanel({ node, flow, tile, state, cap, waiting, connectors, tipShown, layer, actions, health, othersUp,
  example, checking, onCheck, findings, keys, onKeySaved }: Props) {
  const [name, setName] = useState(node.title);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();
  useEffect(() => { setName(node.title); setError(undefined); }, [node.id, node.title]);

  const run = async (body: Record<string, unknown> | null, reset = false) => {
    setBusy(true);
    setError(undefined);
    try {
      if (reset) await actions.reset(node.id);
      else if (body) await actions.edit(body);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };
  const rename = (e: FormEvent) => {
    e.preventDefault();
    if (name.trim() && name.trim() !== node.title) run({ op: "rename", node: node.id, title: name.trim() });
  };

  const mine = layer === "mine";
  // a scanned dependency (D21): its line is where a check will go, and it needs no app connected (D23)
  const deps = flow.kind === "dependencies";
  const code = flow.source === "code";   // read from the app's code (D25): no connected app to show
  const isUser = node.added_by === "user";
  const isCall = CALLS.has(node.kind);
  const fixed = ["gate", "start", "end"].includes(node.kind) || node.added_by === "policy";
  const swaps = isCall ? connectors.filter((c) => c.type === TYPE_FOR[node.kind]) : [];
  const app = node.connector ? flow.apps[node.connector] : undefined;
  const after = flow.edges.find((e) => e.target === node.id && e.id.startsWith("user_"))?.source ?? "";
  const runText = state === "ok" ? `Done${cap ? ` · ${cap}` : ""}` : state === "failed" ? `Failed${cap ? `: ${cap}` : ""}` : RUN_TEXT[state];
  const kindCls = node.kind === "llm" ? "llm" : node.kind === "gate" ? "gate" : "";
  const max = Math.max(1, ...(node.stats?.history ?? []).map((h) => h.ms));

  return (
    <aside className="sp" aria-label={`Step: ${node.title}`} onKeyDown={(e) => e.key === "Escape" && actions.close()}>
      <div className="sp-head">
        {node.kind === "gate" ? <span className="ff-icon lock" style={{ width: 44, height: 44, borderRadius: 12 }}>{Icons.lock(22)}</span>
          : tile ? <BrandTile c={tile} size={44} />
            : <span className="ff-icon code" style={{ width: 44, height: 44, borderRadius: 12 }}>{node.kind === "end" ? Icons.flag(22) : Icons.code(22)}</span>}
        <div style={{ flex: 1, minWidth: 0 }}>
          <span className={`sp-kind ${kindCls}`}>{KIND_LABEL[node.kind] ?? node.kind}</span>
          <h2>{node.title}</h2>
          {node.what && node.kind !== "decision" && <p className="sp-what">{node.what}</p>}
        </div>
        <button className="fm-ib" type="button" aria-label="Close details" onClick={actions.close}>{Icons.close(18)}</button>
      </div>
      {runText && state !== "idle" && <div className={`sp-run ${state}`} role="status">{runText}</div>}
      {findings && findings.length > 0 && (
        <div className="sp-sec sp-security" role="region" aria-label="To fix">
          <ul>
            {findings.map((f) => (
              <li key={f.id}>
                <span className={`sec-level lv-${f.level}`}>{f.level}</span>
                <span><b>{f.title}</b> <code>{f.ref}</code>
                  <Link className="btn sm" to="/issues">{Icons.bolt(14)} Fix it</Link>
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
      {keys && keys.length > 0 && (() => {
        const missing = keys.find((k) => k.status === "missing" || k.status === "unreadable");
        return (
          <div className="sp-sec sp-keys" role="region" aria-label="Keys">
            {missing && (
              <Link className="sp-addkey" to={`/keys?key=${encodeURIComponent(missing.name)}`}>
                {Icons.key(16)} Add the key {Icons.arrow(16)}
              </Link>
            )}
            <KeyList keys={keys} onSaved={() => onKeySaved?.()} />
          </div>
        );
      })()}
      {health && <Health item={health} othersUp={othersUp} example={example} checking={checking} onCheck={onCheck} />}
      {(node.side_effect || node.repeats || (code && node.estimate_ms)) && (
        <div className="sp-chips sp-sec">
          {code && node.estimate_ms != null && node.estimate_ms > 0 && (
            <span className="sp-chip">{took(node.estimate_ms)} · {node.estimate_source === "measured" ? "measured" : "estimate"}</span>
          )}
          {node.repeats && <span className="sp-chip">{Icons.refresh(12)} Repeats in a loop</span>}
          {node.side_effect && <span className="sp-chip side">{code ? "Writes something" : "Side effect · behind a gate"}</span>}
        </div>
      )}

      {node.kind === "gate" && (
        <div className="sp-sec">
          <div className="sp-lock">{Icons.lock(18)}<span>Always gated. Money and messages never move without you. The Planner can add gates but never remove them.</span></div>
          {waiting && (
            <div className="sp-row">
              <button className="btn warn" type="button" onClick={actions.approve}>Approve</button>
              <button className="btn" type="button" onClick={actions.reject}>Reject</button>
            </div>
          )}
        </div>
      )}

      {node.status === "unconfirmed" && (
        <div className="sp-sec">
          <div className="sp-unc">{Icons.question(18)}<span>{deps
            ? "Unconfirmed: the code only mentions it, and no call was found. It isn't checked until you confirm it."
            : "Unconfirmed. It never runs until you confirm it or the Planner finds code that calls it."}</span></div>
          {mine && (
            <div className="sp-row">
              <button className="btn" type="button" disabled={busy} onClick={() => run({ op: "confirm", node: node.id })}>
                {deps ? "Keep it" : "Keep as my step"}
              </button>
              <button className="btn danger" type="button" disabled={busy} onClick={() => run({ op: "hide", node: node.id })}>Hide it</button>
            </div>
          )}
        </div>
      )}

      {node.kind === "decision" && (
        <div className="sp-sec">
          <span className="sp-sh">Condition, from the code</span>
          {node.condition && <div className="sp-cond">{node.condition}</div>}
          {flow.edges.filter((e) => e.source === node.id && e.kind === "branch").map((e) => (
            <div key={e.id} className="sp-br"><code>{e.when}</code><span>{flow.nodes.find((n) => n.id === e.target)?.title ?? e.target}</span></div>
          ))}
        </div>
      )}

      {isCall && (!(deps || code) || node.connector) && (
        <div className="sp-sec">
          <span className="sp-sh">App</span>
          <div className="sp-conn">
            {tile && <BrandTile c={tile} size={36} />}
            <span><b>{app?.name ?? node.connector}</b>
              <small>{app ? <><span className="chip-dot" style={{ background: "var(--teal)", width: 7, height: 7 }} />{app.model ?? app.type}</> : "not connected"}</small>
            </span>
          </div>
          {mine && swaps.length > 1 && (
            <label className="field">Use another app for this step
              <select value={node.connector ?? ""} disabled={busy}
                onChange={(e) => run({ op: "set_connector", node: node.id, connector: e.target.value })}>
                {swaps.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
              </select>
            </label>
          )}
        </div>
      )}

      {tipShown && node.tip && mine && (
        <div className="sp-sec">
          <div className="sp-tip">
            <span className="h">{Icons.spark(15)} Better fit, found in the test run</span>
            <p>{node.tip.text}</p>
            <div className="sp-row">
              <button className="btn" type="button" disabled={busy}
                onClick={() => run({ op: "set_connector", node: node.id, connector: node.tip!.connector })}>
                Use {flow.apps[node.tip.connector]?.name ?? connectors.find((c) => c.id === node.tip!.connector)?.name ?? node.tip.connector}
              </button>
              <button className="btn" type="button" onClick={() => actions.dismissTip(node.id)}>Keep it as it is</button>
            </div>
          </div>
        </div>
      )}

      {node.evidence.length > 0 && (
        <details className="sp-sec sp-fold">
          <summary>{Icons.file(14)} Code · {node.evidence.find((e) => e.ref)?.ref ?? `${node.evidence.length} places`}</summary>
          {node.evidence.map((ev, i) => <EvidenceItem key={i} ev={ev} />)}
        </details>
      )}

      {node.stats && node.stats.history.length > 0 && (
        <div className="sp-sec">
          <span className="sp-sh">Last {node.stats.history.length} runs</span>
          <div className="sp-bars" aria-hidden="true">
            {node.stats.history.map((h, i) => <span key={i} className={h.ok ? "" : "fail"} style={{ height: `${Math.max(12, (h.ms / max) * 100)}%` }} />)}
          </div>
          <span className="sp-note">{node.stats.summary}</span>
        </div>
      )}

      {mine && (
        <details className="sp-sec sp-fold">
          <summary>{Icons.pencil(14)} Edit</summary>
          {!fixed && (
            <form onSubmit={rename} className="sp-row" style={{ alignItems: "flex-end" }}>
              <label className="field" style={{ flex: "1 1 200px" }}>Name
                <input value={name} maxLength={80} onChange={(e) => setName(e.target.value)} />
              </label>
              <button className="btn" type="submit" disabled={busy || !name.trim() || name.trim() === node.title}>Rename</button>
            </form>
          )}
          {isUser && (
            <label className="field">Runs after
              <select value={after} disabled={busy} onChange={(e) => e.target.value && run({ op: "add_edge", node: node.id, source: e.target.value })}>
                <option value="">Pick a step</option>
                {flow.nodes.filter((n) => n.id !== node.id && n.kind !== "end").map((n) => <option key={n.id} value={n.id}>{n.title}</option>)}
              </select>
            </label>
          )}
          <div className="sp-row">
            {node.yours.length > 0 && !isUser && (
              <button className="btn" type="button" disabled={busy} onClick={() => run(null, true)}>Back to the Planner's version</button>
            )}
            {isUser ? (
              <button className="btn danger" type="button" disabled={busy} onClick={() => run(null, true)}>Delete this step</button>
            ) : (
              <button className="btn danger" type="button" disabled={busy || fixed} onClick={() => run({ op: "hide", node: node.id })}
                title={fixed ? "Gates, starts and ends always stay" : undefined}>
                {node.kind === "gate" ? "Gates can't be removed" : fixed ? "Can't be hidden" : "Hide from my map"}
              </button>
            )}
          </div>
          {error && <p className="sp-note" role="alert" style={{ color: "var(--coral)" }}>{error}</p>}
          <p className="sp-note">{isUser ? "Your own step: no code calls it." : "Edits change the map, never your code."}</p>
        </details>
      )}
    </aside>
  );
}
