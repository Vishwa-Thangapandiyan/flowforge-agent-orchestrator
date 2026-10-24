// The Issues page (D37, docs/design/issues-keys): every issue with one button. Fix: FlowForge shows the change (the key
// masked), you approve, and it's made on a new branch. Send to agent: for what needs a judgment call.
import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { Icons } from "../components/icons";
import { EmptyState, ErrorBox } from "../components/ui";
import { useCounts } from "./counts";
import type { Finding, Level } from "./Security";
import "./security.css";

export interface Issue extends Finding {
  action: "fix" | "agent";
  state: "open" | "sent" | "fixed";
  branch: string | null;
}

export interface IssuesResponse {
  repo: string | null;
  example: boolean;
  summary: Partial<Record<Level, number>>;
  issues: Issue[];
}

interface Preview {
  id: string;
  file: string;
  name: string;
  lines: { kind: "ctx" | "del" | "add"; n: number; text: string }[];
  branch: string | null;
  can_apply: boolean;
  why_not: string | null;
}

const LEVEL_WORD: Record<Level, string> = { high: "high", medium: "medium", low: "low" };
const KEY_KINDS = new Set(["key_in_code", "key_in_config"]);

function useAction(onDone: () => void) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();
  const run = async <T,>(call: () => Promise<T>): Promise<T | undefined> => {
    setBusy(true);
    setError(undefined);
    try {
      const out = await call();
      onDone();
      return out;
    } catch (err) {
      setError(err instanceof Error ? err.message : "That didn't work");
      return undefined;
    } finally {
      setBusy(false);
    }
  };
  return { busy, error, run };
}

function Head({ issue, badge }: { issue: Issue; badge?: React.ReactNode }) {
  return (
    <div className="is-row">
      <i className={`sec-dot lv-${issue.level}`} aria-label={LEVEL_WORD[issue.level]} />
      <span className="is-what">
        <b>{issue.title}</b>
        <span className="is-meta"><code>{issue.ref}</code>{issue.action === "agent" && <span>{issue.fix}</span>}</span>
      </span>
      {badge}
    </div>
  );
}

function SendButton({ issue, onDone }: { issue: Issue; onDone: () => void }) {
  const send = useAction(onDone);
  return (
    <>
      <button type="button" className="btn sm agent" disabled={send.busy}
        onClick={() => void send.run(() => api.post(`/issues/${encodeURIComponent(issue.id)}/send`))}>
        {Icons.arrow(14)} Send to agent
      </button>
      {send.error && <span className="key-err" role="alert">{send.error}</span>}
    </>
  );
}

function Sent() {
  return <div className="is-sent">{Icons.arrow(14)} <b>Sent</b> · tell your agent: <i>"do the FlowForge fixes"</i></div>;
}

function FixCard({ issue, onDone }: { issue: Issue; onDone: () => void }) {
  const [preview, setPreview] = useState<Preview>();
  const load = useAction(() => {});
  const apply = useAction(onDone);
  const path = `/issues/${encodeURIComponent(issue.id)}`;
  if (issue.state === "fixed") {
    return (
      <li className="is-card">
        <Head issue={issue} badge={<span className="chip ok">{Icons.check(14)} Fixed</span>} />
        <div className="is-done"><b>{Icons.check(14)} On branch {issue.branch}</b><span>Merge it when you're ready.</span></div>
        {KEY_KINDS.has(issue.kind) && <p className="is-warn">Replace this key with the provider: older commits still hold it.</p>}
      </li>
    );
  }
  return (
    <li className="is-card">
      <Head issue={issue} badge={!preview && issue.state !== "sent" && (
        <button type="button" className="btn sm primary" disabled={load.busy}
          onClick={() => void load.run(() => api.post<Preview>(`${path}/preview`)).then((p) => p && setPreview(p))}>
          {Icons.bolt(14)} Fix
        </button>
      )} />
      {load.error && <p className="key-err" role="alert">{load.error}</p>}
      {issue.state === "sent" && <Sent />}
      {preview && (
        <div className="is-fix">
          <div className="is-diff" role="region" aria-label={`The change to ${preview.file}`}>
            <div className="is-file">{preview.file}</div>
            {preview.lines.map((l, i) => (
              <div key={i} className={`is-l ${l.kind}`}>
                <span className="is-n">{l.kind === "del" ? "-" : l.kind === "add" ? "+" : " "}{l.n}</span>{l.text}
              </div>
            ))}
          </div>
          <ul className="is-does">
            <li>Saves the key in <Link to="/keys">Keys</Link></li>
            {preview.branch && <li>Makes branch <code>{preview.branch}</code>: your branch isn't touched</li>}
            <li>Your app gets the key with <code>flowforge run</code></li>
          </ul>
          {preview.why_not && <p className="is-why" role="status">{preview.why_not}</p>}
          <div className="is-btns">
            <button type="button" className="btn primary" disabled={!preview.can_apply || apply.busy}
              onClick={() => void apply.run(() => api.post(`${path}/fix`)).then((d) => d && setPreview(undefined))}>
              {Icons.check(16)} Approve
            </button>
            <button type="button" className="btn quiet" onClick={() => setPreview(undefined)}>Cancel</button>
            {!preview.can_apply && preview.why_not && !preview.why_not.startsWith("Example") && <SendButton issue={issue} onDone={onDone} />}
          </div>
          {apply.error && <p className="key-err" role="alert">{apply.error}</p>}
        </div>
      )}
    </li>
  );
}

function AgentCard({ issue, onDone }: { issue: Issue; onDone: () => void }) {
  return (
    <li className="is-card">
      <Head issue={issue} badge={issue.state === "open" ? <SendButton issue={issue} onDone={onDone} /> : undefined} />
      {issue.state === "sent" && <Sent />}
    </li>
  );
}

export function IssuesPage() {
  const counts = useCounts();
  const data = counts.issuesData;
  const head = (
    <div className="page-head">
      <div className="titles">
        <h1>Issues</h1>
        <p className="lede">{data?.example ? "Example data: Fix shows the change but makes none." : "Every issue has one button."}</p>
      </div>
      {data && data.issues.length > 0 && (
        <span className="is-chips">
          {(["high", "medium", "low"] as Level[]).filter((l) => data.summary[l]).map((l) => (
            <span key={l} className={`chip lv-${l}`}>{data.summary[l]} {l}</span>
          ))}
        </span>
      )}
    </div>
  );
  if (counts.issuesError && !data) return <div className="sec-page">{head}<ErrorBox error={counts.issuesError} what="the issues" /></div>;
  if (!data) return <div className="sec-page" aria-busy="true">{head}</div>;
  if (data.issues.length === 0) {
    return (
      <div className="sec-page">{head}
        <EmptyState tone="teal" icon={Icons.shield(28)} title={data.repo ? "Nothing to fix" : "No folder mapped yet"}
          action={data.repo ? undefined : <Link className="btn primary" to="/">Scan a folder</Link>}>
          {data.repo ? "No keys in code, no plain http, no risky MCP servers." : "Issues come from the scan of a folder."}
        </EmptyState>
      </div>
    );
  }
  const fixes = data.issues.filter((i) => i.action === "fix");
  const agent = data.issues.filter((i) => i.action === "agent");
  return (
    <div className="sec-page">{head}
      {fixes.length > 0 && (
        <section aria-label="FlowForge fixes">
          <h2 className="is-group">{Icons.bolt(15)} FlowForge fixes <small>new branch · you approve · your branch isn't touched</small></h2>
          <ul className="is-list">{fixes.map((i) => <FixCard key={i.id} issue={i} onDone={counts.reload} />)}</ul>
        </section>
      )}
      {agent.length > 0 && (
        <section aria-label="For your agent">
          <h2 className="is-group">{Icons.code(15)} For your agent <small>needs a judgment call</small></h2>
          <ul className="is-list">{agent.map((i) => <AgentCard key={i.id} issue={i} onDone={counts.reload} />)}</ul>
          <p className="is-agentbox">Your agent reads these with <code>get_fix_requests</code>. Each one clears when the code no longer has it. <Link to="/connect">Connect your agent</Link></p>
        </section>
      )}
    </div>
  );
}
