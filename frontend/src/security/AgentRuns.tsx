// Your agent's app runs (D43): the agent asks FlowForge to start your app with its keys; a new command waits for your
// Allow. Commands show as the agent wrote them (ffkey:// masks), keys by name, output masked: never a value.
import { useState } from "react";
import { api, useApi } from "../api/client";
import { when } from "../components/format";
import { Icons } from "../components/icons";

export interface RunRequest { id: string; argv: string[]; keys: string[]; at: number; state: string }
export interface AppRunInfo { id: string; argv: string[]; keys: string[]; status: string; code: number | null; started: number }
export interface AppsResponse { requests: RunRequest[]; runs: AppRunInfo[]; approve_runs: boolean }

const POLL_MS = 3000;

export function commandText(argv: string[]): string {
  return argv.map((a) => (/[\s"']/.test(a) ? JSON.stringify(a) : a)).join(" ");
}

/** On every page of a project: a card per command your agent is waiting to run. */
export function RunPrompt() {
  const apps = useApi<AppsResponse>("/apps", POLL_MS);
  const [busy, setBusy] = useState<string>();
  const [error, setError] = useState<string>();
  const waiting = apps.data?.requests ?? [];
  if (waiting.length === 0) return null;
  const decide = async (id: string, how: "allow" | "deny") => {
    setBusy(id);
    setError(undefined);
    try { await api.post(`/apps/requests/${encodeURIComponent(id)}/${how}`); apps.reload(); }
    catch (err) { setError(err instanceof Error ? err.message : "Couldn't answer"); }
    finally { setBusy(undefined); }
  };
  return (
    <div className="run-asks">
      {waiting.map((r) => (
        <section key={r.id} className="run-ask" role="alertdialog" aria-label="Your agent wants to run">
          <h2>{Icons.play(15)} Your agent wants to run</h2>
          <code className="run-cmd">{commandText(r.argv)}</code>
          <p className="run-keys">{Icons.key(13)} with {r.keys.length ? r.keys.join(", ") : "no keys"} <span>(masked: it never sees a value)</span></p>
          <div className="run-btns">
            <button type="button" className="btn sm" disabled={busy === r.id} onClick={() => void decide(r.id, "deny")}>Deny</button>
            <button type="button" className="btn sm primary" disabled={busy === r.id} onClick={() => void decide(r.id, "allow")}>
              {Icons.check(14)} Allow
            </button>
          </div>
          <p className="run-note">Allow once: the same command won't ask again.</p>
        </section>
      ))}
      {error && <p className="key-err" role="alert">{error}</p>}
    </div>
  );
}

function RunRow({ run, onChanged }: { run: AppRunInfo; onChanged: () => void }) {
  const [lines, setLines] = useState<[number, string][]>();
  const show = async (open: boolean) => {
    if (!open) return;
    try { setLines((await api.get<{ lines: [number, string][] }>(`/apps/runs/${encodeURIComponent(run.id)}/output`)).lines); }
    catch { setLines([]); }
  };
  const stop = async () => { await api.post(`/apps/runs/${encodeURIComponent(run.id)}/stop`).catch(() => {}); onChanged(); };
  const word = run.status === "exited" ? `exited (${run.code ?? "?"})` : run.status;
  return (
    <li className="run-row">
      <span className={`run-st st-${run.status}`}>{word}</span>
      <span className="run-what"><code>{commandText(run.argv)}</code>
        <small>{run.keys.length ? `keys: ${run.keys.join(", ")}` : "no keys"} · started {when(new Date(run.started * 1000).toISOString())}</small></span>
      {run.status === "running" && <button type="button" className="btn sm" onClick={() => void stop()}>{Icons.stop(13)} Stop</button>}
      <details className="run-out" onToggle={(e) => void show((e.target as HTMLDetailsElement).open)}>
        <summary>Output</summary>
        <pre aria-label="Output (masked)">{lines === undefined ? "…" : lines.map(([, l]) => l).join("\n") || "(nothing yet)"}</pre>
      </details>
    </li>
  );
}

/** On the Keys page: what your agent ran with your keys, and Stop. */
export function AgentRuns() {
  const apps = useApi<AppsResponse>("/apps", POLL_MS);
  const runs = apps.data?.runs ?? [];
  if (runs.length === 0) return null;
  return (
    <section className="run-list" aria-label="Agent runs">
      <h2>{Icons.play(15)} Your agent's runs</h2>
      <ul>{runs.map((r) => <RunRow key={r.id} run={r} onChanged={apps.reload} />)}</ul>
    </section>
  );
}
