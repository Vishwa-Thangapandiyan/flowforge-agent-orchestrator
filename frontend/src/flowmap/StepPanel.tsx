// The step panel (D17): what a block does, its app, the Planner's tip, the evidence, recent runs and your edits.
// Edits are saved on top of the Planner's version and never touch your code.
import { useEffect, useState, type FormEvent, type ReactNode } from "react";
import type { Connector, Evidence, FlowNode, FlowView } from "../api/types";
import { BrandTile } from "../brand/BrandTile";
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

export function StepPanel({ node, flow, tile, state, cap, waiting, connectors, tipShown, layer, actions }: Props) {
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
        </div>
        <button className="fm-ib" type="button" aria-label="Close details" onClick={actions.close}>{Icons.close(18)}</button>
      </div>
      {runText && state !== "idle" && <div className={`sp-run ${state}`} role="status">{runText}</div>}

      <div className="sp-sec">
        <span className="sp-sh">What it does</span>
        <p className="sp-what">{node.what || "No description from the Planner."}</p>
        <div className="sp-chips">
          {node.on_critical_path && <span className="sp-chip cp">{Icons.route(12)} On the critical path</span>}
          {node.side_effect && <span className="sp-chip side">Side effect · behind a gate</span>}
          {node.kind === "llm" && <span className="sp-chip">{Icons.shield(12)} Keys and personal data removed first</span>}
          {node.yours.length > 0 && <span className="sp-chip yours">Your edit</span>}
        </div>
      </div>

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
          <div className="sp-unc">{Icons.question(18)}<span>Unconfirmed. It never runs until you confirm it or the Planner finds code that calls it.</span></div>
          {mine && (
            <div className="sp-row">
              <button className="btn" type="button" disabled={busy} onClick={() => run({ op: "confirm", node: node.id })}>Keep as my step</button>
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

      {isCall && (
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

      <div className="sp-sec">
        <span className="sp-sh">Evidence</span>
        {node.evidence.length ? node.evidence.map((ev, i) => <EvidenceItem key={i} ev={ev} />)
          : <p className="sp-note">Structure only: this block's meaning comes from the lines around it.</p>}
      </div>

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
        <div className="sp-sec">
          <span className="sp-sh">Edit</span>
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
          <p className="sp-note">{isUser ? "Your own step. Your code has no call for it, so test-run replays skip it."
            : "Edits change how FlowForge maps and tests this flow, never your code."}</p>
        </div>
      )}
    </aside>
  );
}
