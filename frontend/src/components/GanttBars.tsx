import { TYPE_TAG, stepTone } from "./status";
import type { Row } from "./timeline";
import "./GanttBars.css";

const pct = (s: number, scale: number) => `${Math.max(0, Math.min(100, (s / scale) * 100))}%`;

/** "Who ran when": one bar per step on a shared time axis; the critical chain is outlined. */
export function GanttBars({ rows, scaleS, nowS, live, selected, onSelect }: {
  rows: Row[];
  scaleS: number;
  nowS: number;
  live: boolean;
  selected?: string;
  onSelect?: (id: string) => void;
}) {
  const ticks = [0, 0.25, 0.5, 0.75, 1].map((f) => f * scaleS);
  return (
    <div className="gantt" role="list" aria-label="Who ran when">
      {rows.map((r) => {
        const [tone, word] = stepTone(r.state);
        const running = r.state === "running";
        const end = r.end ?? (running ? nowS : null);
        const tag = TYPE_TAG[r.type] ?? { label: r.type, tone: "slate" };
        const status = `: ${r.cacheHit ? "answered from cache" : word}${
          r.start !== null && end !== null ? `, ${(end - r.start).toFixed(1)} s` : ""}${r.critical ? ", on the slowest chain" : ""}`;
        return (
          <div role="listitem" key={r.id} className={`gantt-row${selected === r.id ? " is-selected" : ""}`}>
            <button type="button" className="gantt-label" onClick={() => onSelect?.(r.id)} aria-pressed={selected === r.id}>
              <span className="gantt-n">{r.n}</span>
              <span className="gantt-title">{r.title}</span>
              <span className={`tag tone-${tag.tone}`}>{tag.label}</span>
              <span className="visually-hidden">{status}</span>
            </button>
            <div className="gantt-track" onClick={() => onSelect?.(r.id)} aria-hidden="true">
              {r.start !== null && end !== null && (
                <div
                  className={`gantt-bar state-${r.state}${r.cacheHit ? " is-cache" : ""}${r.critical ? " is-critical" : ""}${running ? " running-stripes pulse" : ""}`}
                  style={{ left: pct(r.start, scaleS), width: `max(6px, ${pct(end - r.start, scaleS)})`, ["--tone" as string]: `var(--${tone})` }}
                >
                  {r.cacheHit && <span className="gantt-chip">cache</span>}
                </div>
              )}
              {r.start === null && r.expectedStart !== null && r.expectedEnd !== null && (
                <div className={`gantt-bar is-expected${r.critical ? " is-critical" : ""}`}
                  style={{ left: pct(r.expectedStart, scaleS), width: `max(6px, ${pct(r.expectedEnd - r.expectedStart, scaleS)})` }} />
              )}
              {r.state === "skipped" && <span className="gantt-skip">skipped</span>}
            </div>
          </div>
        );
      })}
      <div className="gantt-row gantt-axis" aria-hidden="true">
        <span />
        <div className="gantt-ticks">
          {ticks.map((t) => <span key={t}>{t === 0 ? "0 s" : `${Number(t.toFixed(1))}${t === scaleS ? " s" : ""}`}</span>)}
          {live && <span className="gantt-now" style={{ left: pct(nowS, scaleS) }} />}
        </div>
      </div>
    </div>
  );
}
