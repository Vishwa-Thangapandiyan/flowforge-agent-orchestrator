// The map's legends: the dependency map (D21), a flow read from code (D25), and the Planner's flow (D17).
import { Icons } from "../components/icons";

export function DepsLegend() {
  return (
    <>
      <div className="fm-lrow"><span className="fm-lg"><span className="lg-card lg-llm" /></span>LLM</div>
      <div className="fm-lrow"><span className="fm-lg"><span className="lg-card" /></span>API, MCP server or local command</div>
      <div className="fm-lrow"><span className="fm-lg"><span className="lg-card lg-unc" /></span>Unconfirmed: mentioned, no call found</div>
      <div className="fm-ldiv" />
      <div className="fm-lrow"><span className="fm-lg"><svg width="28" height="8" viewBox="0 0 28 8" aria-hidden="true"><path d="M1 4h26" style={{ stroke: "var(--edge)", strokeWidth: 2 }} /></svg></span>Uses</div>
      <div className="fm-lrow"><span className="fm-lg" style={{ color: "var(--teal)" }}>{Icons.shield(16)}</span>Scanned on your machine. Nothing sent</div>
      <div className="fm-lhint">Drag to pan · scroll to zoom · drag a block to move it</div>
    </>
  );
}

/** A flow read from code (D25): no gates, no fallbacks, no redaction claims; the app's own calls are its own. */
export function CodeLegend() {
  return (
    <>
      <div className="fm-lrow"><span className="fm-lg"><span className="lg-card" /></span>A call to a dependency</div>
      <div className="fm-lrow"><span className="fm-lg"><span className="lg-card lg-llm" /></span>An LLM call</div>
      <div className="fm-lrow"><span className="fm-lg"><span className="lg-dia" /></span>An if in the code</div>
      <div className="fm-ldiv" />
      <div className="fm-lrow"><span className="fm-lg"><svg width="28" height="8" viewBox="0 0 28 8" aria-hidden="true"><path d="M1 4h26" style={{ stroke: "var(--edge)", strokeWidth: 2 }} /></svg></span>Waits for the call before it</div>
      <div className="fm-lrow"><span className="fm-lg"><svg width="28" height="8" viewBox="0 0 28 8" aria-hidden="true"><path d="M1 4h26" style={{ stroke: "var(--teal)", strokeWidth: 3.5 }} /></svg></span>Critical path: sets the total time</div>
      <div className="fm-lhint">Every block and line points to its file:line</div>
    </>
  );
}

export function Legend() {
  return (
    <>
      <div className="fm-lrow"><span className="fm-lg"><span className="lg-card" /></span>App call or your code</div>
      <div className="fm-lrow"><span className="fm-lg"><span className="lg-card lg-llm" /></span>LLM call</div>
      <div className="fm-lrow"><span className="fm-lg"><span className="lg-dia" /></span>Decision (yes / no)</div>
      <div className="fm-lrow"><span className="fm-lg"><span className="lg-bar" /></span>Run together / wait for all</div>
      <div className="fm-lrow"><span className="fm-lg"><span className="lg-card lg-gate" /></span>You approve (payments, messages)</div>
      <div className="fm-lrow"><span className="fm-lg"><span className="lg-card lg-unc" /></span>Unconfirmed: no evidence</div>
      <div className="fm-ldiv" />
      <div className="fm-lrow"><span className="fm-lg"><svg width="28" height="8" viewBox="0 0 28 8" aria-hidden="true"><path d="M1 4h26" style={{ stroke: "var(--edge)", strokeWidth: 2 }} /></svg></span>Data flows this way</div>
      <div className="fm-lrow"><span className="fm-lg"><svg width="28" height="8" viewBox="0 0 28 8" aria-hidden="true"><path d="M1 4h26" style={{ stroke: "var(--coral)", strokeWidth: 2, strokeDasharray: "5 4" }} /></svg></span>Fallback when a call fails</div>
      <div className="fm-lrow"><span className="fm-lg" style={{ color: "var(--teal)" }}>{Icons.shield(16)}</span>Keys and personal data removed first</div>
      <div className="fm-ldiv" />
      <div className="fm-ldots">
        <span><i style={{ background: "var(--teal)" }} />done</span><span><i style={{ background: "var(--blue)" }} />running</span>
        <span><i style={{ background: "var(--amber-strong)" }} />waits for you</span><span><i style={{ background: "var(--coral)" }} />failed</span>
        <span><i style={{ background: "var(--violet)" }} />Planner</span>
      </div>
      <div className="fm-lhint">Drag to pan · scroll to zoom · drag a step to move it</div>
    </>
  );
}
