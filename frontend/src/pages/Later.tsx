// Pages whose features arrive in a later phase: a clear empty state, no fake controls.
import { Icons } from "../components/icons";
import { Chip, EmptyState } from "../components/ui";

export function Approvals() {
  return (
    <>
      <header className="page-head">
        <div className="titles">
          <span className="eyebrow">Paused until you decide</span>
          <h1>Approvals</h1>
        </div>
        <Chip tone="amber">Arrives in V2</Chip>
      </header>
      <EmptyState tone="amber" icon={Icons.check(30)} title="Nothing is waiting for you">
        When approval gates arrive, any payment, code change or other step with side effects pauses here
        first. You'll see why it was proposed, what happens if you approve, and whether it can be undone.
        The Planner can never turn that off.
      </EmptyState>
    </>
  );
}

export function Security() {
  return (
    <>
      <header className="page-head">
        <div className="titles">
          <span className="eyebrow">Keys stay out of reach</span>
          <h1>Security</h1>
        </div>
        <Chip tone="teal">Findings arrive in Phase 7</Chip>
      </header>
      <section className="card raised">
        <h2>What protects your keys today</h2>
        <div className="row"><span>Where keys live</span><b>Your <code>.env</code> file, never in FlowForge's data</b></div>
        <div className="row"><span>What connectors store</span><b>Only the variable's name, like <code>env:GEMINI_API_KEY</code></b></div>
        <div className="row"><span>Runs, events and logs</span><b>Known key formats and your configured keys are replaced with [REDACTED] before they're saved or shown</b></div>
        <div className="row"><span>HTTP connectors</span><b>Send their key only to their own address</b></div>
        <p className="card-note">This catches known key formats and the keys you configured, not everything.</p>
      </section>
      <EmptyState tone="teal" icon={Icons.lock(30)} title="What the scan finds">
        Phase 7 lists hard-coded keys, plain http:// APIs and risky MCP setups, each with its file and line and a
        fix. A key's value is never stored or shown.
      </EmptyState>
    </>
  );
}
