// Connect your coding agent (D29, D30): set-up on the left; on the right, what the agent gets from this repo and,
// once it has called, what it asked.
import { useState, type ReactNode } from "react";
import { useApi } from "../api/client";
import { BrandTile } from "../brand/BrandTile";
import { clock, when } from "../components/format";
import { Icons } from "../components/icons";
import { CardSkeleton, ErrorBox } from "../components/ui";
import "./agent.css";

export interface AgentSetup {
  name: string;
  how: "terminal" | "file";
  checked: boolean;
  text: string;
  file?: string;
  file_text?: string;
}

export interface Call { tool: string; repo: string; at: string; got?: string | null }

interface Connect {
  repo: string | null;
  command: string[];
  agents: Record<string, AgentSetup>;
  last_call: Call | null;
  calls?: Call[];
}

interface Card { tool: string; headline: string | null; sub: string | null; tone: "ok" | "warn" | "bad" | "plain" }

/** The question each tool answers, and its icon (D30). */
const TOOLS: Record<string, { ask: string; icon: (s?: number) => ReactNode }> = {
  get_map: { ask: "What does it call?", icon: Icons.map },
  check_health: { ask: "Is anything down?", icon: Icons.activity },
  get_security_findings: { ask: "Is anything unsafe?", icon: Icons.shield },
  get_keys: { ask: "Which keys are missing?", icon: Icons.key },
  get_fix_requests: { ask: "What did I send it to fix?", icon: Icons.check },
  get_flow: { ask: "What waits for what?", icon: Icons.route },
  get_advice: { ask: "What could run together?", icon: Icons.bolt },
  what_changed: { ask: "What did the edit change?", icon: Icons.refresh },
  run_app: { ask: "Run the app with its keys", icon: Icons.play },
  app_output: { ask: "What did the app print?", icon: Icons.list },
  stop_app: { ask: "Stop the app", icon: Icons.stop },
};

/** Tiles: Claude Code has its own mark; simple-icons has none for the others, so they get monograms (D15). */
const TILE: Record<string, { id: string; letters?: string }> = {
  claude: { id: "claudecode" }, codex: { id: "codex", letters: "Cx" }, antigravity: { id: "antigravity", letters: "AG" },
};

function useCopy(): [string | undefined, (text: string) => void] {
  const [said, setSaid] = useState<string>();
  const copy = (text: string) => {
    navigator.clipboard.writeText(text).then(() => setSaid("Copied"), () => setSaid("Couldn't copy: select the text instead"));
    window.setTimeout(() => setSaid(undefined), 2500);
  };
  return [said, copy];
}

/** One agent's set-up: pick the agent, copy one line, and see whether it has asked anything yet. */
export function Setup({ c, title = "Set up" }: { c: Pick<Connect, "agents" | "last_call">; title?: string }) {
  const [tab, setTab] = useState("claude");
  const [said, copy] = useCopy();
  const agent = c.agents[tab];
  const last = c.last_call;
  return (
    <section className="card ca-setup" aria-label={title}>
      <h2 className="ca-label">{title}</h2>
      <div className="ca-agents" role="tablist" aria-label="Agent" aria-orientation="vertical">
        {Object.entries(c.agents).map(([id, a]) => (
          <button key={id} type="button" role="tab" id={`ca-tab-${id}`} aria-selected={tab === id} aria-controls="ca-panel"
            className="ca-agent" onClick={() => setTab(id)}>
            <BrandTile size={36} c={{ id: TILE[id]?.id ?? id, type: "local", name: a.name,
              style: TILE[id]?.letters ? { color: null, logo: { type: "letters", text: TILE[id].letters! } } : undefined }} />
            <span><b>{a.name}</b><small>{a.how === "terminal" ? "a terminal command" : "a config file"}</small></span>
            {tab === id && <i className="ca-tick" aria-hidden="true">{Icons.check(14)}</i>}
          </button>
        ))}
      </div>
      <div role="tabpanel" id="ca-panel" aria-labelledby={`ca-tab-${tab}`} className="ca-panel">
        <button className="btn primary ca-copy" type="button" onClick={() => copy(agent.text)}>
          {Icons.copy(16)} {agent.how === "terminal" ? "Copy set-up command" : "Copy config"}
        </button>
        <span className="ca-said" aria-live="polite">{said}</span>
        <details className="ca-show">
          <summary>Show {agent.how === "terminal" ? "the command" : "the config"}</summary>
          <pre aria-label={`${agent.name} set-up`}>{agent.text}</pre>
          {agent.file_text && (
            <>
              <p className="ca-or">or add the same to <code>{agent.file}</code></p>
              <pre aria-label={`${agent.name} config file`}>{agent.file_text}</pre>
              <button className="btn" type="button" onClick={() => copy(agent.file_text!)}>{Icons.copy(14)} Copy</button>
            </>
          )}
        </details>
        <ol className="ca-steps">
          <li><b>1</b><span>{agent.how === "terminal" ? "Paste it in a terminal" : <>Paste it into <code>{agent.file}</code></>}</span></li>
          <li><b>2</b><span>Restart {agent.name}</span></li>
          <li><b>3</b><span>Ask it: <q>What slows this app down?</q></span></li>
        </ol>
        {!agent.checked && (
          <p className="ca-note">{Icons.question(15)} Where this file lives differs between versions of {agent.name}.</p>
        )}
      </div>
      <div className={`ca-last${last ? " on" : ""}`} role="status">
        <i aria-hidden="true" />
        {last
          ? <span><b>Connected</b> · last call {when(last.at)}</span>
          : <span>Waiting for your agent's first question</span>}
      </div>
    </section>
  );
}

function Gets({ repo }: { repo: string | null }) {
  const preview = useApi<{ repo: string; cards: Card[] }>(repo ? "/agent/preview" : null);
  return (
    <section aria-labelledby="ca-gets">
      <h2 className="ca-label" id="ca-gets">What your agent gets{preview.data && <> from <span>{preview.data.repo}</span></>}</h2>
      {!repo && <p className="ca-note">Scan a folder first: your agent asks about that folder.</p>}
      {preview.error && <ErrorBox error={preview.error} what="the preview" />}
      {repo && !preview.data && !preview.error && <CardSkeleton lines={4} />}
      {preview.data && (
        <ul className="ca-cards">
          {preview.data.cards.map((card) => {
            const t = TOOLS[card.tool];
            return (
              <li key={card.tool} className={`ca-card tone-${card.tone}`}>
                <span className="ca-ask">{t?.icon(15)} {t?.ask}</span>
                {card.headline && <strong>{card.headline}</strong>}
                {card.sub && <span className="ca-sub">{card.sub}</span>}
                <code>{card.tool}</code>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}

function Asked({ calls }: { calls: Call[] }) {
  return (
    <section aria-labelledby="ca-asked">
      <h2 className="ca-label" id="ca-asked">What your agent asked <span className="ca-live">live</span></h2>
      <ol className="card ca-calls">
        {calls.map((call, i) => (
          <li key={`${call.at}-${i}`}>
            <time dateTime={call.at}>{clock(call.at)}</time>
            <span className="ca-tool">{TOOLS[call.tool]?.icon(14)}<code>{call.tool}</code></span>
            <span className="ca-got">{call.got ?? "answered"}</span>
          </li>
        ))}
      </ol>
    </section>
  );
}

export function ConnectAgent() {
  const data = useApi<Connect>("/agent/connect", 5000);   // re-read, so the agent's calls show up by themselves
  const once = useApi<{ agent: { agents: Record<string, AgentSetup> } }>("/settings");   // paired once (D39, D40)
  if (data.error) return <ErrorBox error={data.error} what="the agent set-up" />;
  if (!data.data) return <CardSkeleton lines={6} />;
  const c = data.data;
  const calls = c.calls ?? [];

  return (
    <>
      <header className="page-head">
        <div className="titles">
          <span className="eyebrow">MCP server · read-only</span>
          <h1>Connect your coding agent</h1>
          <p className="lede">Your agent asks FlowForge about this app, then makes the change itself.</p>
        </div>
      </header>

      <div className="ca-grid">
        <Setup c={{ agents: once.data?.agent.agents ?? c.agents, last_call: c.last_call }} title="Set up · once, for every project" />
        <div className="ca-right">
          <Gets repo={c.repo} />
          {calls.length > 0 && <Asked calls={calls} />}
        </div>
      </div>

      <p className="ca-safe">
        {Icons.shield(16)} Read-only · key values never sent · never edits your code · MCP servers start only after your yes on Checks
      </p>
    </>
  );
}
