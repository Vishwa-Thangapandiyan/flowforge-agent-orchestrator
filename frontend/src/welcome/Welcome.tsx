// The welcome (D40): once, full-screen, on a launch with no projects. Three steps, each can be skipped: your app,
// your agent (paired once, for every project), your keys (the Vault's lock). Finishing or skipping marks it done.
import { type FormEvent, useState } from "react";
import { createPortal } from "react-dom";
import { useNavigate } from "react-router-dom";
import { Setup } from "../agent/ConnectAgent";
import { api, useApi } from "../api/client";
import { Icons } from "../components/icons";
import { markOpen, placeOf } from "../projects/memory";
import { type LockState, SetUp } from "../security/VaultPage";
import type { SettingsData } from "../settings/types";
import "./welcome.css";

const STEPS = ["Your app", "Your agent", "Your keys"];

function AppStep({ exampleId, onMapped }: { exampleId: string; onMapped: (id: string) => void }) {
  const [path, setPath] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();
  const scan = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(undefined);
    try {
      const made = await api.post<{ id: string }>("/projects", { path: path.trim() });
      onMapped(made.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't map that folder");
    } finally {
      setBusy(false);
    }
  };
  return (
    <form className="wc-step" onSubmit={scan}>
      <h2>Which app should I map?</h2>
      <p className="wc-note">The folder your app is in. FlowForge reads its code: nothing is run, nothing is sent anywhere.</p>
      <div className="wc-in">
        <input aria-label="Your app's folder" placeholder="/home/you/code/my-app" value={path} autoFocus disabled={busy}
          onChange={(e) => setPath(e.target.value)} />
        <button className="btn primary" type="submit" disabled={busy || !path.trim()}>
          {busy ? "Reading your code…" : <>Map it {Icons.arrow(16)}</>}
        </button>
      </div>
      {busy && <div className="pj-prog" role="progressbar" aria-label="Reading your code"><i /></div>}
      {error && <p className="key-err" role="alert">{error}</p>}
      <p className="wc-or">or <button type="button" className="btn quiet" onClick={() => onMapped(exampleId)} disabled={busy}>
        Try the example app</button></p>
    </form>
  );
}

function AgentStep({ onNext }: { onNext: () => void }) {
  const settings = useApi<SettingsData>("/settings", 3000);   // re-read: the agent's first call turns it green
  const agent = settings.data?.agent;
  return (
    <div className="wc-step">
      <h2>Pair your coding agent, once</h2>
      <p className="wc-note">One line, for every project. Your agent asks FlowForge about your app, then makes the change itself.</p>
      {agent ? <Setup c={{ agents: agent.agents, last_call: agent.last_call }} title="Your agent" /> : <div className="wc-wait" aria-busy="true" />}
      <div className="wc-foot">
        <button type="button" className="btn primary" onClick={onNext}>{agent?.connected ? "Next" : "I'll do it later"} {Icons.arrow(16)}</button>
      </div>
    </div>
  );
}

function KeysStep({ onDone }: { onDone: () => void }) {
  const lock = useApi<LockState>("/lock");
  if (!lock.data) return <div className="wc-step" aria-busy="true" />;
  return (
    <div className="wc-step">
      <h2>Lock your keys</h2>
      <p className="wc-note">A password and the code on your phone. Your keys stay out of your code and away from your agent; only you can see them.</p>
      {lock.data.state === "on"
        ? <p className="wc-done" role="status">{Icons.check(16)} Your lock is already set.</p>
        : <SetUp onDone={onDone} />}
      <div className="wc-foot">
        <button type="button" className="btn primary" onClick={onDone}>{lock.data.state === "on" ? "Finish" : "I'll do it later"} {Icons.arrow(16)}</button>
      </div>
    </div>
  );
}

export function Welcome({ exampleId, onDone }: { exampleId: string; onDone: () => void }) {
  const [step, setStep] = useState(0);
  const [project, setProject] = useState<string>();
  const [error, setError] = useState<string>();
  const go = useNavigate();
  const finish = async () => {
    setError(undefined);
    try {
      await api.patch("/settings", { welcome_done: true });
    } catch (err) {   // not saved: it would come back next time with no reason, so it stays and says why (Codex review)
      setError(`Couldn't save that you're done: ${err instanceof Error ? err.message : "unknown error"}`);
      return;
    }
    if (project) { markOpen(project); go(placeOf(project)); }
    onDone();
  };
  // on the page itself: inside the shell, the page's entry animation would make "fixed" mean "fixed to the page"
  return createPortal(
    <div className="wc" role="dialog" aria-modal="true" aria-labelledby="wc-title">
      <div className="wc-box">
        <header className="wc-head">
          <h1 id="wc-title">Welcome to FlowForge</h1>
          <ol className="wc-bar" aria-label={`Step ${step + 1} of 3`}>
            {STEPS.map((name, i) => (
              <li key={name} className={i < step ? "done" : i === step ? "now" : ""} aria-current={i === step ? "step" : undefined}>
                <i>{i < step ? Icons.check(13) : i + 1}</i><span>{name}</span>
              </li>
            ))}
          </ol>
        </header>
        {step === 0 && <AppStep exampleId={exampleId} onMapped={(id) => { setProject(id); setStep(1); }} />}
        {step === 1 && <AgentStep onNext={() => setStep(2)} />}
        {step === 2 && <KeysStep onDone={() => void finish()} />}
        {error && <p className="key-err" role="alert">{error}</p>}
        <button type="button" className="wc-skip" onClick={() => void finish()}>Skip for now {Icons.arrow(14)}</button>
      </div>
    </div>,
    document.body,
  );
}
