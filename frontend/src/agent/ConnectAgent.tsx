// Connect your coding agent (D28, D29): one copy-ready set-up per agent, with this repo's paths filled in, the
// five read-only tools it gets, and the agent's last call as proof the connection works.
import { useState } from "react";
import { useApi } from "../api/client";
import { when } from "../components/format";
import { Icons } from "../components/icons";
import { CardSkeleton, ErrorBox } from "../components/ui";
import "./agent.css";

interface AgentSetup {
  name: string;
  how: "terminal" | "file";
  checked: boolean;
  text: string;
  file?: string;
  file_text?: string;
}

interface Connect {
  repo: string | null;
  command: string[];
  agents: Record<string, AgentSetup>;
  last_call: { tool: string; repo: string; at: string } | null;
}

const TOOLS: [string, string][] = [
  ["get_map", "every dependency, with file:line and health"],
  ["get_flow", "the order of calls and the critical path"],
  ["get_advice", "what could run together, with the change written out"],
  ["check_health", "checks now: why something is down, and the fix"],
  ["what_changed", "after an edit: what was added or removed"],
];

function CopyBox({ text, label }: { text: string; label: string }) {
  const [said, setSaid] = useState<string>();
  const copy = () => {
    navigator.clipboard.writeText(text).then(() => setSaid("Copied"), () => setSaid("Couldn't copy: select the text instead"));
    window.setTimeout(() => setSaid(undefined), 2500);
  };
  return (
    <div className="ca-box">
      <pre aria-label={label}>{text}</pre>
      <div className="ca-copy">
        <button className="btn" type="button" onClick={copy}>{Icons.copy(16)} Copy</button>
        <span className="ca-said" aria-live="polite">{said}</span>
      </div>
    </div>
  );
}

export function ConnectAgent() {
  const data = useApi<Connect>("/agent/connect", 5000);   // re-read, so the agent's first call shows up by itself
  const [tab, setTab] = useState("claude");
  if (data.error) return <ErrorBox error={data.error} what="the agent set-up" />;
  if (!data.data) return <CardSkeleton lines={6} />;
  const c = data.data;
  const agent = c.agents[tab];
  const last = c.last_call;

  return (
    <>
      <header className="page-head">
        <div className="titles">
          <span className="eyebrow">MCP server · read-only</span>
          <h1>Connect your coding agent</h1>
          <p className="lede">Your agent asks FlowForge about this app, then makes the change itself.</p>
        </div>
      </header>

      <div className={`ca-last${last ? " on" : ""}`} role="status">
        <i aria-hidden="true" />
        {last
          ? <span><b>Connected</b> · last call {when(last.at)} · <code>{last.tool}</code> on {last.repo}</span>
          : <span>No agent has called yet. Set one up below, then ask it something.</span>}
      </div>

      <section className="card ca-setup" aria-label="Set-up">
        <div className="seg ca-tabs" role="tablist" aria-label="Agent">
          {Object.entries(c.agents).map(([id, a]) => (
            <button key={id} type="button" role="tab" id={`ca-tab-${id}`} aria-selected={tab === id}
              aria-pressed={tab === id} aria-controls="ca-panel" onClick={() => setTab(id)}>{a.name}</button>
          ))}
        </div>
        <div role="tabpanel" id="ca-panel" aria-labelledby={`ca-tab-${tab}`} className="ca-panel">
          <ol className="ca-steps">
            <li><b>1</b>{agent.how === "terminal" ? "Paste this in a terminal" : <>Paste this into <code>{agent.file}</code></>}</li>
            <li><b>2</b>Restart {agent.name}</li>
            <li><b>3</b>Ask: <q>Ask FlowForge what slows this app down.</q></li>
          </ol>
          <CopyBox text={agent.text} label={`${agent.name} set-up`} />
          {agent.file_text && (
            <>
              <p className="ca-or">or add the same to <code>{agent.file}</code></p>
              <CopyBox text={agent.file_text} label={`${agent.name} config file`} />
            </>
          )}
          {!agent.checked && (
            <p className="ca-note">{Icons.question(15)} Where this file lives differs between versions of {agent.name}: open it from the menu named above.</p>
          )}
          <p className="ca-note">Repo: <code>{c.repo ?? "none yet: scan a folder first"}</code></p>
        </div>
      </section>

      <section className="card ca-tools" aria-label="What your agent can ask">
        <h2>What your agent can ask</h2>
        <ul>
          {TOOLS.map(([name, does]) => <li key={name}><code>{name}</code><span>{does}</span></li>)}
        </ul>
        <p className="ca-safe">{Icons.shield(16)} Read-only · key values never sent · never edits your code · MCP servers start only after your yes on Checks</p>
      </section>
    </>
  );
}
