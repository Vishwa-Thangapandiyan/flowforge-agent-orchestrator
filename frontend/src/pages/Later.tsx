// Pages whose features arrive in a later phase: a clear empty state, no fake controls.
import type { CSSProperties } from "react";
import { Link } from "react-router-dom";
import { Icons } from "../components/icons";
import { Chip, EmptyState } from "../components/ui";

function Steps({ items }: { items: [string, string][] }) {
  return (
    <ol className="grid" style={{ "--min": "220px", listStyle: "none", padding: 0, margin: 0 } as CSSProperties}>
      {items.map(([title, body], i) => (
        <li key={title} className={`card rise rise-${i + 1}`}>
          <span className="eyebrow">{i + 1}</span>
          <h3>{title}</h3>
          <p className="card-note">{body}</p>
        </li>
      ))}
    </ol>
  );
}

export function PlanReview() {
  return (
    <>
      <header className="page-head">
        <div className="titles">
          <span className="eyebrow">Proposed by the Planner · nothing has run yet</span>
          <h1>Here's what will happen</h1>
        </div>
        <Chip tone="violet">Arrives in Phase 4</Chip>
      </header>
      <EmptyState tone="violet" icon={Icons.spark(30)} title="The Planner will write your plans">
        Connect your apps, and the Planner works out the steps and their order from what they can do.
        You read one plain list (steps in order, which run together, how long it takes, which keys it
        touches) and say "Looks good, run it" once. Payments, code changes and anything with side effects
        always wait for you as well.
      </EmptyState>
      <Steps items={[
        ["You connect apps", "Razorpay, Gemini, an MCP server, a script."],
        ["The Planner proposes", "Tasks come only from tools, routes and files that really exist."],
        ["You confirm once", "A plain list, not a graph. Risky steps still wait for you."],
      ]} />
      <p className="card-note">Until then, start a run from <Link to="/live">Live run</Link>.</p>
    </>
  );
}

export function Approvals() {
  return (
    <>
      <header className="page-head">
        <div className="titles">
          <span className="eyebrow">Paused until you decide</span>
          <h1>Approvals</h1>
        </div>
        <Chip tone="amber">Arrives in Phase 4</Chip>
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
        <Chip tone="teal">Vault arrives in Phase 3</Chip>
      </header>
      <section className="card raised">
        <h2>What protects your keys today</h2>
        <div className="row"><span>Where keys live</span><b>Your <code>.env</code> file, never in FlowForge's data</b></div>
        <div className="row"><span>What connectors store</span><b>Only the variable's name, like <code>env:GEMINI_API_KEY</code></b></div>
        <div className="row"><span>Runs, events and logs</span><b>Known key formats and your configured keys are replaced with [REDACTED] before they're saved or shown</b></div>
        <div className="row"><span>HTTP connectors</span><b>Send their key only to their own address</b></div>
        <p className="card-note">This catches known key formats and the keys you configured, not everything.</p>
      </section>
      <EmptyState tone="teal" icon={Icons.lock(30)} title="The vault and the full redaction pipeline">
        Phase 3 adds an encrypted vault (paste a key once, never see it again), redaction of keys found in
        your code before any AI sees it, and checks that the AI's changes keep every placeholder intact.
      </EmptyState>
    </>
  );
}
