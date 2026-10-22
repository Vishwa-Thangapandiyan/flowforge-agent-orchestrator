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
