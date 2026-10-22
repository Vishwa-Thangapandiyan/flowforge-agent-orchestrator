import type * as React from "react";
import { useEffect, useMemo, useState } from "react";
import { Link, Navigate, useNavigate, useParams } from "react-router-dom";
import { api, ApiError, useApi } from "../api/client";
import { useRunEvents } from "../api/sse";
import type { RunDetail, RunSummary, Workflow } from "../api/types";
import { count, seconds, shortId, when } from "../components/format";
import { GanttBars } from "../components/GanttBars";
import { Icons } from "../components/icons";
import { OutputViewer } from "../components/OutputViewer";
import { runTone } from "../components/status";
import { buildTimeline, narrate } from "../components/timeline";
import { CardSkeleton, Chip, EmptyState, ErrorBox, prefersReducedMotion, Stat } from "../components/ui";

const humanize = (name: string) => name.replace(/[_-]+/g, " ").replace(/^\w/, (c) => c.toUpperCase());

/** Seconds since `startedAt`, re-rendered every animation frame (every 250 ms under reduced motion). */
function useElapsed(startedAt: string | undefined, running: boolean): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!running) return;
    if (prefersReducedMotion()) {
      const id = window.setInterval(() => setNow(Date.now()), 250);
      return () => window.clearInterval(id);
    }
    let frame = requestAnimationFrame(function tick() {
      setNow(Date.now());
      frame = requestAnimationFrame(tick);
    });
    return () => cancelAnimationFrame(frame);
  }, [running]);
  return startedAt ? Math.max(0, (now - new Date(startedAt).getTime()) / 1000) : 0;
}

export function LiveRun() {
  const { id = "" } = useParams();
  const navigate = useNavigate();
  const { events, ended } = useRunEvents(id);
  const runningGuess = !ended;
  const detail = useApi<RunDetail>(`/runs/${encodeURIComponent(id)}`, runningGuess ? 1500 : undefined);
  const [selected, setSelected] = useState<string>();
  const [stopping, setStopping] = useState(false);
  const [stopError, setStopError] = useState<string>();

  const status = detail.data?.status ?? "running";
  const running = status === "running";
  const elapsedLive = useElapsed(detail.data?.summary.started_at, running);
  const nowS = running ? elapsedLive : (detail.data?.result?.makespan_ms ?? detail.data?.summary.time_ms ?? 0) / 1000;

  const timeline = useMemo(
    () => buildTimeline(detail.data?.steps ?? [], events, detail.data?.result ?? null, nowS),
    [detail.data, events, nowS],
  );
  const log = useMemo(() => narrate(detail.data?.steps ?? [], events), [detail.data?.steps, events]);

  useEffect(() => {
    // refresh the final numbers the moment the stream ends
    if (ended) detail.reload();
  }, [ended]); // eslint-disable-line react-hooks/exhaustive-deps

  if (detail.error) {
    if (detail.error instanceof ApiError && detail.error.status === 404) {
      return <EmptyState icon={Icons.history(30)} title="That run doesn't exist">It may belong to another FlowForge data folder. <Link to="/runs">See run history</Link>.</EmptyState>;
    }
    return <ErrorBox error={detail.error} what="this run" />;
  }
  if (!detail.data) return <><CardSkeleton lines={2} /><CardSkeleton lines={6} /></>;

  const d = detail.data;
  const [tone, word] = runTone(status);
  const row = timeline.rows.find((r) => r.id === selected) ?? timeline.rows.find((r) => r.output !== undefined && r.output !== null) ?? timeline.rows[0];
  const calls = d.result?.api_calls ?? timeline.calls;
  const hits = d.result?.cache_hits ?? timeline.cacheHits;

  async function stop() {
    setStopping(true);
    setStopError(undefined);
    try {
      await api.post(`/runs/${encodeURIComponent(id)}/stop`);
    } catch (e) {
      setStopError((e as Error).message);
    } finally {
      setStopping(false);
      detail.reload();
    }
  }

  return (
    <>
      <header className="page-head">
        <div className="titles">
          <span className="eyebrow">Run {shortId(d.summary.id)} · {d.summary.plan}</span>
          <h1>{running ? "Running now" : { succeeded: "Finished", failed: "Finished with a failure", stopped: "Stopped", interrupted: "Interrupted", error: "Something went wrong" }[status] ?? word}</h1>
          <span className="lede">Started {when(d.summary.started_at)}</span>
        </div>
        <div className="actions">
          {running ? (
            <button type="button" className="btn danger" onClick={stop} disabled={stopping}>{Icons.stop(16)} {stopping ? "Stopping…" : "Stop run"}</button>
          ) : (
            <button type="button" className="btn" onClick={() => navigate("/live?again=" + encodeURIComponent(d.summary.workflow_id))}>
              {Icons.refresh(16)} Run it again
            </button>
          )}
          <Link to="/runs" className="btn">Run history</Link>
        </div>
      </header>
      {stopError && <div className="error-box" role="alert"><b>Couldn't stop it.</b> {stopError}</div>}
      {d.summary.failure_reason && !running && (
        <div className="error-box" role="status"><b>Why: </b>{d.summary.failure_reason}</div>
      )}

      <div className="stats" aria-live="polite">
        <Stat tone={tone} value={<span style={{ display: "inline-flex", alignItems: "center", gap: 10 }}>{running && <span className="chip-dot pulse" />}{word}</span>} label="status" />
        <Stat value={seconds(nowS * 1000)} label={timeline.predictedMs ? `elapsed · about ${seconds(timeline.predictedMs, 0)} expected` : "elapsed"} />
        <Stat value={count(calls)} label={`API calls · ${count(hits)} skipped by cache`} />
        <Stat value={count(timeline.tokens)} label={running ? "tokens so far" : "tokens used"} />
      </div>

      <section className="card raised">
        <div className="card-head">
          <h2>Who ran when</h2>
          <span className="card-note">The outlined chain is the slowest, so it sets the total time.</span>
        </div>
        <div className="table-wrap">
          <GanttBars rows={timeline.rows} scaleS={timeline.scaleS} nowS={nowS} live={running} selected={row?.id} onSelect={setSelected} />
        </div>
        <div className="legend">
          <span><i style={{ background: "var(--teal)" }} />done</span>
          <span><i style={{ background: "var(--blue)" }} />running</span>
          <span><i style={{ background: "color-mix(in srgb, var(--teal) 45%, var(--surface))" }} />answered from cache</span>
          <span><i style={{ border: "2px dashed var(--idle)" }} />waiting</span>
          <span><i style={{ background: "var(--coral)" }} />failed</span>
        </div>
      </section>

      <div className="grid" style={{ "--min": "420px" } as React.CSSProperties}>
        {row && <OutputViewer key={row.id} output={row.output} title={`${row.n} ${row.title}`} />}
        <section className="card" aria-label="Events">
          <span className="eyebrow">Events</span>
          <ol className="event-log" aria-live="polite">
            {log.map((l, i) => (
              <li key={i} style={l.tone ? { color: `var(--${l.tone})` } : undefined}>
                <span className="t">{l.t.toFixed(1)}s</span>{l.text}
              </li>
            ))}
            {running && <li className="t" style={{ color: "var(--blue)" }}><span className="t">{nowS.toFixed(1)}s</span>running…</li>}
          </ol>
        </section>
      </div>
    </>
  );
}

/** /live: jump to the run that is running now, or offer plans to start. */
export function LiveRunLatest() {
  const runs = useApi<RunSummary[]>("/runs?limit=10", 3000);
  const workflows = useApi<string[]>("/workflows");
  const navigate = useNavigate();
  const [starting, setStarting] = useState<string>();
  const [error, setError] = useState<string>();
  const again = new URLSearchParams(window.location.search).get("again");

  async function start(name: string) {
    setStarting(name);
    setError(undefined);
    try {
      const wf = await api.get<Workflow>(`/workflows/${encodeURIComponent(name)}`);
      const { run_id } = await api.post<{ run_id: string }>("/runs", wf);
      navigate(`/runs/${run_id}`);
    } catch (e) {
      setError((e as Error).message);
      setStarting(undefined);
    }
  }

  useEffect(() => {
    if (again && workflows.data?.includes(again) && !starting) void start(again);
  }, [again, workflows.data]); // eslint-disable-line react-hooks/exhaustive-deps

  const running = runs.data?.find((r) => r.status === "running");
  if (running && !again) return <Navigate to={`/runs/${running.id}`} replace />;
  const recent = runs.data?.filter((r) => r.status !== "running").slice(0, 3) ?? [];

  return (
    <>
      <header className="page-head">
        <div className="titles">
          <span className="eyebrow">Live run</span>
          <h1>Nothing is running</h1>
          <span className="lede">Start a plan and watch every step as it happens.</span>
        </div>
      </header>
      {error && <div className="error-box" role="alert"><b>Couldn't start it.</b> {error}</div>}
      <section className="card raised">
        <h2>Start a run</h2>
        {workflows.data ? (
          <div className="grid" style={{ "--min": "240px" } as React.CSSProperties}>
            {workflows.data.map((name) => (
              <button key={name} type="button" className="choice" onClick={() => start(name)} disabled={!!starting}
                aria-busy={starting === name}>
                <b>{humanize(name)}</b>
                <span>{starting === name ? "Starting…" : "Run now"}</span>
              </button>
            ))}
          </div>
        ) : <CardSkeleton lines={2} />}
        <p className="card-note">
          Soon the Planner will propose plans from your connected apps (Phase 5). For now these are ready-made
          plans; developers can also send their own workflow JSON to <code>POST /runs</code>.
        </p>
      </section>
      {recent.length > 0 && (
        <section className="card">
          <h2>Recent runs</h2>
          {recent.map((r) => (
            <Link key={r.id} to={`/runs/${r.id}`} className="row" style={{ textDecoration: "none", color: "var(--fg)" }}>
              <span>{r.plan} · {when(r.started_at)}</span>
              <Chip tone={runTone(r.status)[0]}>{runTone(r.status)[1]}</Chip>
            </Link>
          ))}
        </section>
      )}
    </>
  );
}
