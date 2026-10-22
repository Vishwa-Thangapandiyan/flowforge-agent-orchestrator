// Check now (D24): the latest verdicts, a run's live progress over SSE, and the yes before MCP servers start.
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, useApi } from "../api/client";
import { useRunEvents } from "../api/sse";
import type { CheckItem, CheckPlan, ChecksView, HealthStatus } from "../api/types";

export type LiveStatus = HealthStatus | "checking";
export type LiveItem = Omit<CheckItem, "status"> & { status: LiveStatus };

/** What waits for a yes: the plan's servers that this check would start, which dependencies it covers, and
 * what the rest of the check does (one request each, or only looked for). */
export interface Asking {
  plan: CheckPlan;
  ids?: string[];
  requests: number;
  lookedFor: number;
}

const STORED_TRIES = 20;   // after a run ends, how often to re-read /checks until its verdicts are stored

function isResult(output: unknown): output is LiveItem {
  return typeof output === "object" && output !== null && "id" in output && "status" in output;
}

export function useChecks(enabled = true) {
  const view = useApi<ChecksView>(enabled ? "/checks" : null);
  const [run, setRun] = useState<{ id: string; ids: string[] } | null>(null);
  const [asking, setAsking] = useState<Asking | null>(null);
  const [error, setError] = useState<string>();
  const tries = useRef(0);
  const { events, ended } = useRunEvents(run?.id);

  const live = useMemo(() => {
    const out: Record<string, Partial<LiveItem>> = {};
    if (!run) return out;
    for (const id of run.ids) out[id] = { status: "checking", summary: "Checking…" };
    for (const e of events) {
      if (e.type === "step" && e.state === "succeeded" && isResult(e.output)) out[e.output.id] = e.output;
    }
    return out;
  }, [run, events]);

  // the run's verdicts are stored when it ends: re-read until /checks names this run
  const stored = !!run && view.data?.run_id === run.id;
  const reload = view.reload;
  useEffect(() => {
    if (!run || !ended) return;
    if (stored || tries.current >= STORED_TRIES) {
      setRun(null);
      return;
    }
    const timer = window.setTimeout(() => { tries.current += 1; reload(); }, 300);
    return () => window.clearTimeout(timer);
  }, [run, ended, stored, reload, view.data]);

  const items: LiveItem[] = useMemo(() => (view.data?.items ?? []).map((i) => {
    const now = live[i.id];
    return now ? { ...i, ...now, history: i.history } as LiveItem : i;
  }), [view.data, live]);
  const checkable = useMemo(() => items.filter((i) => i.status !== "unconfirmed").map((i) => i.id), [items]);

  const start = useCallback(async (body: { ids?: string[]; confirm?: boolean }) => {
    setError(undefined);
    setAsking(null);
    try {
      const r = await api.post<{ run_id: string; checks: number }>("/checks", body);
      tries.current = 0;
      setRun({ id: r.run_id, ids: body.ids ?? checkable });
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, [checkable]);

  /** Check everything (or `ids`); first ask before any MCP server starts that you haven't said yes to. */
  const checkNow = useCallback(async (ids?: string[]) => {
    setError(undefined);
    try {
      const plan = await api.get<CheckPlan>("/checks/plan");
      const starts = ids ? plan.starts.filter((s) => ids.includes(s.id)) : plan.starts;
      if (!plan.confirmed && starts.length) {
        const covered = items.filter((i) => (ids ?? checkable).includes(i.id) && !starts.some((s) => s.id === i.id));
        setAsking({ plan: { ...plan, starts }, ids, requests: covered.filter((i) => i.kind !== "local").length,
          lookedFor: covered.filter((i) => i.kind === "local").length });
        return;
      }
      await start(ids ? { ids } : {});
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, [start, items, checkable]);

  const confirm = useCallback(() => {
    if (asking) void start(asking.ids ? { ids: asking.ids, confirm: true } : { confirm: true });
  }, [asking, start]);
  const withoutStarts = useCallback(() => {
    if (!asking) return;
    const skip = new Set(asking.plan.starts.map((s) => s.id));
    const ids = (asking.ids ?? checkable).filter((id) => !skip.has(id));
    if (ids.length) void start({ ids });
    else setAsking(null);
  }, [asking, checkable, start]);

  const done = run ? run.ids.filter((id) => live[id] && live[id].status !== "checking").length : 0;
  return {
    view: view.data, loadError: view.error, items, error, asking,
    running: !!run, progress: run ? { done, total: run.ids.length } : null,
    checkNow, confirm, withoutStarts, cancel: () => setAsking(null),
  };
}

export type Checks = ReturnType<typeof useChecks>;
