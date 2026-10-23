// The home page (D17, D21): the map of your app. The dependency map (the default) shows what a scanned repo uses;
// the flow map shows the order it runs in, one action at a time (D25, D33). Three controls in the header, the rest
// in ⋯ (D33). Pan, zoom and drag; click a block for its details; edits never touch your code.
import {
  MiniMap, ReactFlow, ReactFlowProvider, useNodesState, useReactFlow, useViewport, ViewportPortal,
  type NodeChange, type OnSelectionChangeParams,
} from "@xyflow/react";
import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties, type FormEvent } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { api, ApiError, useApi } from "../api/client";
import { CheckConfirm } from "../checks/Health";
import { useChecks } from "../checks/useChecks";
import { type Finding, SecurityChip, type SecurityResponse, worst } from "../security/Security";
import type { Connector, ConnectorType, FlowAction, FlowNode, FlowResponse, FlowView, NodeKind, Trace } from "../api/types";
import { took } from "../checks/Health";
import { Icons } from "../components/icons";
import { useMeta } from "../components/Shell";
import { EmptyState, ErrorBox } from "../components/ui";
import { Faster } from "./Faster";
import { earliest } from "./kinds";
import { scheduleTrace } from "./schedule";
import { boxes, readTheme, saveTheme, THEMES, timeColumns, type GraphTheme } from "./themes";
import { edgeTypes, Markers, type LineEdge } from "./FlowEdge";
import { autoLayout, compactSize, handlesFor, placeAll, sizeOf } from "./layout";
import { mapQuery, useMapId, type MapId } from "./mapId";
import { MoreMenu, type MenuItem } from "./MoreMenu";
import { nodeTypes, typeFor, type BlockData, type BlockNode, type TileSource } from "./nodes";
import { buildReplay, frameAt, type Frame } from "./replay";
import { StepPanel } from "./StepPanel";
import "./flowmap.css";

const TIPS_KEY = "flowforge.tips.dismissed";
const TILE_TYPE: Partial<Record<NodeKind, ConnectorType>> = { llm: "llm", api: "http", mcp: "mcp", local: "local" };

/** A design token's current value (SVG attributes such as the minimap's fill can't read CSS variables). */
function token(name: string, fallback: string): string {
  if (typeof window === "undefined") return fallback;
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fallback;
}

function readDismissed(): Set<string> {
  try {
    return new Set(JSON.parse(localStorage.getItem(TIPS_KEY) ?? "[]") as string[]);
  } catch {
    return new Set();
  }
}

export function FlowMapPage() {
  const meta = useMeta();
  const map = useMapId();
  const [layer, setLayer] = useState<"mine" | "planner">("mine");
  const flow = useApi<FlowResponse>(`/flow?layer=${layer}${mapQuery(map, "&")}`);
  const isFlowMap = flow.data?.available && (flow.data.kind ?? "flow") === "flow";
  const trace = useApi<Trace>(isFlowMap ? `/flow/trace${mapQuery(map)}` : null);
  const connectors = useApi<Connector[]>("/connectors");
  const [action, setAction] = useState<string | null>(null);   // the action a code flow shows (D33)
  if (flow.error) return <div style={{ padding: 24 }}><ErrorBox error={flow.error} what="the map" /></div>;
  if (!flow.data) return <div className="fm" aria-busy="true"><div className="fm-stage"><div className="fm-canvas skeleton" /></div></div>;
  if (!flow.data.available) {
    return (
      <div style={{ padding: "32px clamp(16px, 3vw, 40px)" }}>
        <EmptyState tone="violet" icon={Icons.map(28)} title="No map yet"
          action={map === "deps" && !meta.example ? <ScanForm onDone={flow.reload} /> : undefined}>
          {flow.data.message}
        </EmptyState>
      </div>
    );
  }
  const actions = flow.data.source === "code" ? flow.data.actions ?? [] : [];
  const current = actions.length > 1 ? (actions.find((a) => a.id === action) ?? actions[0]) : null;
  return (
    <ReactFlowProvider>
      <MapView key={`${map}:${current?.id ?? ""}`} map={map} flow={current ? only(flow.data, current) : flow.data}
        trace={trace.data ?? null} connectors={connectors.data ?? []} layer={layer} setLayer={setLayer} reload={flow.reload}
        actions={actions} action={current?.id ?? null} setAction={setAction} />
    </ReactFlowProvider>
  );
}

/** One action of a code flow (D33): what its start reaches, with its own times, critical path and advice. Laid out
 * fresh: the saved layout is for the whole flow. */
export function only(flow: FlowView, a: FlowAction): FlowView {
  // steps you added stay in view, so you can connect and edit them (they reach nothing yet)
  const keep = new Set([a.id, ...flow.nodes.filter((n) => n.added_by === "user").map((n) => n.id)]);
  for (let grew = true; grew;) {
    grew = false;
    for (const e of flow.edges) if (keep.has(e.source) && !keep.has(e.target)) { keep.add(e.target); grew = true; }
  }
  const onPath = new Set(a.path);
  const pathEdges = new Set(a.path.slice(1).map((id, i) => `${a.path[i]}>${id}`));
  const nodes = flow.nodes.filter((n) => keep.has(n.id)).map((n) => ({ ...n, on_critical_path: onPath.has(n.id) }));
  const slowest = nodes.filter((n) => onPath.has(n.id)).sort((x, y) => (y.estimate_ms ?? 0) - (x.estimate_ms ?? 0))[0];
  return {
    ...flow, nodes, positions: {},
    edges: flow.edges.filter((e) => keep.has(e.source) && keep.has(e.target))
      .map((e) => ({ ...e, on_critical_path: pathEdges.has(`${e.source}>${e.target}`) })),
    critical_path: { path: a.path, length_ms: a.could_ms, bottleneck: slowest?.id ?? null },
    written_ms: a.written_ms, advice: (flow.advice ?? []).filter((x) => x.nodes.every((id) => keep.has(id))),
  };
}

/** Which action the flow shows: every entry point, slowest first, with its time (D33). */
function ActionPicker({ actions, value, onChange }: { actions: FlowAction[]; value: string | null; onChange: (id: string) => void }) {
  return (
    <label className="fm-action">
      <span>Action</span>
      <select value={value ?? ""} onChange={(e) => onChange(e.target.value)}>
        {actions.map((a) => <option key={a.id} value={a.id}>{a.title} · {took(a.written_ms)}</option>)}
      </select>
    </label>
  );
}

/** Name a folder to map. It is read, never run, and nothing is sent (D20). With a map of `current` already, a
 * different folder replaces it, after you confirm (D22, D23). */
function ScanForm({ onDone, current }: { onDone: () => void; current?: string }) {
  const [path, setPath] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();
  const [confirming, setConfirming] = useState(false);
  const scan = async (replace: boolean) => {
    setBusy(true);
    setError(undefined);
    try {
      await api.post("/scan", replace ? { path: path.trim(), replace: true } : { path: path.trim() });
      onDone();
    } catch (err) {
      if (current && err instanceof ApiError && err.status === 409) setConfirming(true);
      else setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };
  const submit = (e: FormEvent) => {
    e.preventDefault();
    void scan(false);
  };
  return (
    <form className="scan-form" onSubmit={submit}>
      <label className="field">
        <span>Folder to scan</span>
        <input value={path} onChange={(e) => { setPath(e.target.value); setConfirming(false); }}
          placeholder="/home/you/my-app" className="mono" autoComplete="off" spellCheck={false} />
      </label>
      {confirming ? (
        <div className="notice" role="alert">
          <p style={{ margin: "0 0 10px" }}>A different folder: {current}'s map and its versions are deleted.</p>
          <button className="btn warn" type="button" onClick={() => void scan(true)} disabled={busy}>
            {busy ? "Scanning…" : "Replace the map"}
          </button>
        </div>
      ) : (
        <button className="btn primary" type="submit" disabled={busy || !path.trim()}>{busy ? "Scanning…" : "Scan this folder"}</button>
      )}
      {error && <div className="notice" role="alert">{error}</div>}
      <small>Read on this machine only. Nothing in it runs, and nothing is sent.</small>
    </form>
  );
}

/** Example data never mixes with yours (D16), so example mode says how to map your own folder instead. */
function ScanHint() {
  return (
    <div className="scan-form">
      <span>This is example data. To map your own folder, stop FlowForge and run:</span>
      <code className="mono">uv run flowforge --repo /home/you/my-app</code>
      <small>Read on this machine only. Nothing in it runs, and nothing is sent.</small>
    </div>
  );
}

interface ViewProps {
  map: MapId;
  flow: FlowView;
  trace: Trace | null;
  connectors: Connector[];
  layer: "mine" | "planner";
  setLayer: (l: "mine" | "planner") => void;
  reload: () => void;
  actions?: FlowAction[];
  action?: string | null;
  setAction?: (id: string) => void;
}

interface Play {
  t: number;
  running: boolean;
  approved: boolean;
  rejected: boolean;
  /** how much faster than real time it plays: Watch it run fits a long schedule into a few seconds (D26) */
  speed: number;
}

const WATCH_MS = 7000;

function MapView({ map, flow, trace, connectors, layer, setLayer, reload, actions = [], action = null, setAction }: ViewProps) {
  const deps = flow.kind === "dependencies";
  const code = flow.source === "code";   // the app's own flow, read from its code (D25)
  const [params, setParams] = useSearchParams();
  const setMap = (m: MapId) => setParams(m === "flow" ? { ...Object.fromEntries(params), map: "flow" } : {});
  const [pointed, setPointed] = useState<Set<string> | null>(null);   // the blocks a piece of advice covers
  const repo = useApi<{ name: string | null }>(code ? "/scan" : null);   // a code flow is named after its repo
  const q = mapQuery(map);
  const meta = useMeta();
  const navigate = useNavigate();
  const rf = useReactFlow<BlockNode, LineEdge>();
  const { zoom } = useViewport();
  const [nodes, setNodes, onNodesChangeBase] = useNodesState<BlockNode>([]);
  const [sel, setSel] = useState<string | null>(null);
  const [scanning, setScanning] = useState(false);
  const checks = useChecks(deps);   // health on a dependency map (D24)
  const health = useMemo(() => Object.fromEntries(checks.items.map((i) => [i.id, i])), [checks.items]);
  const security = useApi<SecurityResponse>(deps ? "/security" : null);   // findings on a dependency map (D31)
  const findings = useMemo(() => {
    const out: Record<string, Finding[]> = {};
    for (const f of security.data?.findings ?? []) if (f.dep_id) (out[f.dep_id] ??= []).push(f);
    return out;
  }, [security.data]);
  const [find, setFind] = useState("");
  const [cp, setCp] = useState(code);   // a flow read from code opens on its critical path (D25)
  const [showEvidence, setShowEvidence] = useState(false);   // file:line on hover and in the panel by default (D33)
  const [legend, setLegend] = useState(false);
  const [minimap, setMinimap] = useState(false);
  const [allChecks, setAllChecks] = useState(false);   // decisions as full boxes instead of ◆ marks (D33)
  const compact = code && !allChecks;
  const size = compact ? compactSize : sizeOf;
  const oneAction = actions.length > 1;   // one action of many, laid out fresh: its layout isn't saved
  const [theme, setThemeState] = useState<GraphTheme>(readTheme);   // how the map looks, per viewer (D26)
  const setTheme = (t: GraphTheme) => { setThemeState(t); saveTheme(t); };
  const [dismissed, setDismissed] = useState(readDismissed);
  const [play, setPlay] = useState<Play | null>(null);
  const [rechecking, setRechecking] = useState(false);
  const [notice, setNotice] = useState<string>();
  const saveTimer = useRef<number>(0);
  const pending = useRef<Record<string, [number, number]>>({});
  const fitted = useRef(false);

  const kinds = useMemo(() => Object.fromEntries(flow.nodes.map((n) => [n.id, n.kind])) as Record<string, NodeKind>, [flow.nodes]);
  // a flow read from code has no recording: Watch it run plays its could-be schedule instead (D26)
  const played = useMemo(() => trace ?? (code ? scheduleTrace(flow) : null), [trace, code, flow]);
  const replay = useMemo(() => (played ? buildReplay(flow.nodes, flow.edges, played) : null), [flow.nodes, flow.edges, played]);
  const frame: Frame | null = useMemo(() => (play && replay ? frameAt(replay, play.t, play.approved, play.rejected) : null), [play, replay]);

  // --- blocks: positions from the server (or dagre for new ones), data from the current view --------------
  const tileOf = useCallback((id: string | null): TileSource | null => {
    if (!id) return null;
    const app = flow.apps[id];
    const c = connectors.find((x) => x.id === id);
    if (c) return c;
    return { id, type: app?.type ?? "http", name: app?.name ?? id };
  }, [flow.apps, connectors]);
  /** a block's tile: its connected app, or on a dependency map the service it was recognised as (a monogram if unknown) */
  const tileFor = useCallback((n: FlowNode): TileSource | null => {
    if (n.kind === "gate" || n.kind === "end") return null;
    if (n.connector) return tileOf(n.connector);
    const type = TILE_TYPE[n.kind];
    return (deps || code) && type ? { id: n.catalog ?? n.id, type, name: n.title } : null;
  }, [tileOf, deps, code]);

  const query = find.trim().toLowerCase();
  const hits = useMemo(() => new Set(query ? flow.nodes.filter((n) => [n.title, n.connector, flow.apps[n.connector ?? ""]?.name,
    n.op?.tool, n.op?.path, n.what, ...n.evidence.map((e) => e.ref)].filter(Boolean).join(" ").toLowerCase().includes(query)).map((n) => n.id) : []),
  [query, flow.nodes, flow.apps]);

  const dataFor = useCallback((id: string): BlockData | null => {
    const n = flow.nodes.find((x) => x.id === id);
    if (!n) return null;
    const retry = flow.edges.find((e) => e.kind === "retry" && e.source === id);
    return {
      node: n, tile: tileFor(n), deps, code, theme, state: frame?.nodes[id] ?? "idle",
      cap: frame?.caps[id] ?? "", cp: cp && n.on_critical_path,
      search: query ? (hits.has(id) ? "hit" : "miss") : pointed ? (pointed.has(id) ? "hit" : "miss") : null,
      showTip: !dismissed.has(id) && !frame, showEvidence, retryMax: retry?.max ?? null,
      health: deps && health[id] ? health[id] : undefined,
      risk: findings[id] ? worst(findings[id]) : undefined, compact,
    };
  }, [flow.nodes, flow.edges, tileFor, deps, code, theme, frame, query, hits, cp, dismissed, showEvidence, health, pointed,
    findings, compact]);

  // Boxed on a flow lays blocks out in time columns (D26); every other style keeps your saved layout
  const timed = theme === "boxed" && !deps;
  // lines draw themselves in once, in call order (D26); off with reduced motion (the CSS checks it too)
  const [drawing, setDrawing] = useState(true);
  useEffect(() => {
    const done = window.setTimeout(() => setDrawing(false), 2600);
    return () => window.clearTimeout(done);
  }, []);
  /** Pointing at a block (D26): it, everything it waits for, and everything that waits for it. */
  const traceFrom = useCallback((id: string) => {
    const walk = (next: (e: FlowView["edges"][number]) => [string, string]) => {
      const seen = new Set([id]);
      const stack = [id];
      while (stack.length) {
        const here = stack.pop()!;
        for (const e of flow.edges) {
          const [from, to] = next(e);
          if (from === here && !seen.has(to)) { seen.add(to); stack.push(to); }
        }
      }
      return seen;
    };
    return new Set([...walk((e) => [e.target, e.source]), ...walk((e) => [e.source, e.target])]);
  }, [flow.edges]);
  const wasTimed = useRef(timed);
  const wasCompact = useRef(compact);   // ◆ marks and full boxes need their own layout (D33)
  useEffect(() => {
    const saved = placeAll(flow.nodes, flow.edges, flow.positions, size);
    const placed = timed ? timeColumns(flow, saved, size) : saved;
    const switched = wasTimed.current !== timed || wasCompact.current !== compact;
    wasTimed.current = timed;
    wasCompact.current = compact;
    setNodes((current) => {
      const at = timed || switched ? {} : Object.fromEntries(current.map((n) => [n.id, n.position]));
      return flow.nodes.map((n) => {
        const box = size(n.kind);
        const p = at[n.id] ?? { x: placed[n.id][0], y: placed[n.id][1] };
        return { id: n.id, type: typeFor(n.kind), position: p, width: box.w, height: box.h, data: dataFor(n.id)!,
          selected: current.find((c) => c.id === n.id)?.selected ?? false };
      });
    });
    if (switched) window.requestAnimationFrame(() => rf.fitView({ padding: 0.08, maxZoom: 1.1, duration: 400 }));
    // positions only reset when the map itself (or the time layout) changes; data updates are below
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [flow, timed, compact]);

  useEffect(() => {
    setNodes((ns) => ns.map((n) => ({ ...n, data: dataFor(n.id) ?? n.data })));
  }, [dataFor, setNodes]);

  useEffect(() => {
    if (!fitted.current && nodes.length) {
      fitted.current = true;
      window.requestAnimationFrame(() => rf.fitView({ padding: 0.08, maxZoom: 1.1 }));
    }
  }, [nodes.length, rf]);

  const savePositions = useCallback((replace = false) => {
    window.clearTimeout(saveTimer.current);
    saveTimer.current = window.setTimeout(() => {
      const positions = pending.current;
      pending.current = {};
      if (Object.keys(positions).length) api.put(`/flow/positions${q}`, { positions, replace }).catch(() => undefined);
    }, replace ? 0 : 400);
  }, [q]);

  const onNodesChange = useCallback((changes: NodeChange<BlockNode>[]) => {
    onNodesChangeBase(changes);
    for (const c of changes) {
      if (c.type === "position" && c.position && !c.dragging && !timed && !oneAction) {   // these layouts aren't saved
        pending.current[c.id] = [Math.round(c.position.x), Math.round(c.position.y)];
        savePositions();
      }
    }
  }, [onNodesChangeBase, savePositions, timed, oneAction]);

  const onSelectionChange = useCallback(({ nodes: picked }: OnSelectionChangeParams) => {
    setSel(picked[0]?.id ?? null);
  }, []);

  // --- lines ----------------------------------------------------------------------------------------------
  const posNow = useMemo(() => Object.fromEntries(nodes.map((n) => [n.id, [n.position.x, n.position.y] as [number, number]])), [nodes]);
  const cpEdges = useMemo(() => {
    const path = flow.critical_path.path;
    return new Set(path.slice(1).map((id, i) => `${path[i]}>${id}`));
  }, [flow.critical_path.path]);
  const drawDelay = useMemo(() => {   // seconds: lines out of earlier calls draw first
    const start = earliest(flow);
    const last = Math.max(1, ...Object.values(start));
    return Object.fromEntries(Object.entries(start).map(([id, t]) => [id, (t / last) * 1.2]));
  }, [flow]);
  const edges: LineEdge[] = useMemo(() => flow.edges.filter((e) => kinds[e.source] && kinds[e.target]).map((e) => {
    const h = handlesFor(e, kinds, posNow);
    return {
      id: e.id, source: e.source, target: e.target, type: "flow", sourceHandle: h.s, targetHandle: h.t,
      focusable: false, selectable: false,
      data: {
        edge: e, state: frame?.edges[e.id] ?? "idle", cp: cp && cpEdges.has(`${e.source}>${e.target}`),
        // the shield means FlowForge masks keys before this LLM call: true of runs it executes, not of an app's own
        // calls, whether scanned (D21) or read from its code (D25)
        dim: !!query && !(hits.has(e.source) && hits.has(e.target)),
        guard: !deps && !code && kinds[e.target] === "llm" && e.kind !== "fallback",
        theme, to: kinds[e.target], delay: drawDelay[e.source] ?? 0,
      },
    };
  }), [flow.edges, kinds, posNow, frame, cp, cpEdges, query, hits, deps, code, theme, drawDelay]);
  // Boxed containers (D26): drawn in map coordinates behind the blocks, never nodes themselves
  const boxRects = useMemo(() => (theme === "boxed" ? boxes(flow, nodes) : []), [theme, flow, nodes]);

  // --- test-run replay ------------------------------------------------------------------------------------
  useEffect(() => {
    if (!play?.running || !replay) return;
    let raf = 0;
    let last = performance.now();
    const gateAt = replay.gate ? replay.gate.start_ms : null;
    const step = (now: number) => {
      const dt = now - last;
      last = now;
      setPlay((p) => {
        if (!p || !p.running) return p;
        const next = p.t + dt * p.speed;
        const held = gateAt !== null && !p.approved && !p.rejected && next >= gateAt;
        return { ...p, t: held ? gateAt : next };
      });
      raf = requestAnimationFrame(step);
    };
    raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
  }, [play?.running, replay]);

  useEffect(() => {
    if (frame?.done && play?.running) setPlay((p) => (p ? { ...p, running: false } : p));
  }, [frame?.done, play?.running]);

  const startReplay = () => {
    const reduced = typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    const speed = code ? Math.max(1, (replay?.end ?? 0) / WATCH_MS) : 1;
    // reduced motion: show where the schedule ends, without the motion
    setPlay({ t: reduced && code ? (replay?.end ?? 0) : 0, running: true, approved: false, rejected: false, speed });
    setSel(null);
  };
  const approve = () => setPlay((p) => (p ? { ...p, approved: true, running: true } : p));
  const reject = () => setPlay((p) => (p ? { ...p, rejected: true, running: true } : p));

  // --- edits ----------------------------------------------------------------------------------------------
  const edit = async (body: Record<string, unknown>) => {
    await api.post(`/flow/overrides${q}`, body);
    reload();
  };
  const reset = async (nodeId: string) => {
    await api.del(`/flow/nodes/${encodeURIComponent(nodeId)}/overrides${q}`);
    reload();
  };
  const dismissTip = (nodeId: string) => {
    const next = new Set(dismissed).add(nodeId);
    setDismissed(next);
    try { localStorage.setItem(TIPS_KEY, JSON.stringify([...next])); } catch { /* not remembered */ }
  };
  const addStep = async () => {
    const box = document.querySelector(".fm-canvas")?.getBoundingClientRect();
    const mid = box ? rf.screenToFlowPosition({ x: box.left + box.width / 2, y: box.top + box.height / 2 }) : { x: 0, y: 0 };
    const id = `${deps ? "dep" : "step"}_${Date.now().toString(36)}`;
    const newNode = deps ? { id, kind: "api", title: "New dependency", what: "A dependency you added." }
      : { id, kind: "code", title: "New step", what: "A step you added." };
    try {
      await api.put(`/flow/positions${q}`, { positions: { [id]: [Math.round(mid.x - 98), Math.round(mid.y - 32)] } });
      await api.post(`/flow/overrides${q}`, { op: "add_node", new_node: newNode });
      setLayer("mine");
      reload();
      setSel(id);
    } catch (e) {
      setNotice(e instanceof Error ? e.message : String(e));
    }
  };
  const retidy = () => {
    const laid = autoLayout(flow.nodes, flow.edges, size);
    if (timed || oneAction) {   // Boxed's time columns and one action's layout are tidied, never saved (D26, D33)
      const cols = timed ? timeColumns(flow, laid, size) : laid;
      setNodes((ns) => ns.map((n) => (cols[n.id] ? { ...n, position: { x: cols[n.id][0], y: cols[n.id][1] } } : n)));
      window.setTimeout(() => rf.fitView({ padding: 0.08, duration: 500 }), 30);
      return;
    }
    setNodes((ns) => ns.map((n) => (laid[n.id] ? { ...n, position: { x: laid[n.id][0], y: laid[n.id][1] } } : n)));
    pending.current = { ...laid };
    savePositions(true);
    window.setTimeout(() => rf.fitView({ padding: 0.08, duration: 500 }), 30);
  };
  const recheck = async () => {
    if (flow.pending) { navigate(`/map/recheck${q}`); return; }
    setRechecking(true);
    try {
      await api.post(`/flow/recheck${q}`);
      navigate(`/map/recheck${q}`);
    } catch (e) {
      setNotice(e instanceof Error ? e.message : String(e));
      setRechecking(false);
    }
  };
  const focusOn = (id: string) => {
    const n = rf.getNode(id);
    if (!n) return;
    setSel(id);
    setNodes((ns) => ns.map((x) => ({ ...x, selected: x.id === id })));
    rf.setCenter(n.position.x + (n.width ?? 196) / 2, n.position.y + (n.height ?? 64) / 2, { zoom: Math.max(zoom, 0.9), duration: 450 });
  };  // "Show on map" from the Security page: /?focus=<dependency> selects and centres that block once it is drawn (D31)
  const focus = params.get("focus");
  const focused = useRef<string | null>(null);
  useEffect(() => {
    if (!focus || focused.current === focus || !nodes.some((n) => n.id === focus)) return;
    focused.current = focus;   // once per request: focusOn changes the blocks, which runs this again
    // after the first fit to the screen (a frame after the blocks are drawn), or that fit moves it away again
    window.setTimeout(() => focusOn(focus), 120);
    const rest = Object.fromEntries(params);
    delete rest.focus;
    setParams(rest, { replace: true });
  }, [focus, nodes]);   // eslint-disable-line react-hooks/exhaustive-deps


  const selected = sel ? flow.nodes.find((n) => n.id === sel) : undefined;
  const appName = flow.nodes.find((n) => n.id === "app")?.title;
  const busy = !!play && !frame?.done;
  const elapsed = frame ? (frame.t / 1000).toFixed(1) : "0.0";
  const progress = frame ? Math.round((Object.values(frame.nodes).filter((s) => !["idle", "running", "retry", "waiting"].includes(s)).length / Math.max(1, flow.nodes.length)) * 100) : 0;
  const fellBack = !!frame && !!trace && trace.steps.some((s) => s.outcome === "failed" && (frame.nodes[s.node] === "failed"));

  const rescanLabel = deps || code
    ? (flow.pending ? "Review the re-scan" : rechecking ? "Re-scanning…" : "Re-scan the repo")
    : (flow.pending ? "Review the re-check" : rechecking ? "Re-checking…" : "Re-check the repo");
  const menu: MenuItem[] = [
    { kind: "head", label: deps ? "Map" : "Flow" },
    ...(deps ? [{ kind: "action" as const, label: "Scan another folder", icon: Icons.search(16), onClick: () => setScanning(true) }] : []),
    { kind: "toggle", label: `Show my edits (${flow.counts.edits})`, on: layer === "mine",
      onClick: () => setLayer(layer === "mine" ? "planner" : "mine") },
    { kind: "action", label: deps ? "Add a block" : "Add a step", icon: Icons.addBox(16), onClick: () => void addStep() },
    ...(deps ? [{ kind: "link" as const, label: "Apps and connectors", icon: Icons.plug(16), to: "/connectors" }] : []),
    { kind: "link", label: deps ? "How it was mapped" : code ? "How it was read" : "How it was drawn", icon: Icons.question(16), to: `/map/how${q}` },
    { kind: "head", label: "View" },
    { kind: "action", label: "Re-tidy", icon: Icons.tidy(16), onClick: retidy },
    ...(!deps ? [{ kind: "toggle" as const, label: "Critical path", on: cp, onClick: () => setCp((v) => !v) }] : []),
    ...(code ? [{ kind: "toggle" as const, label: "Show every check", on: allChecks, onClick: () => setAllChecks((v) => !v) }] : []),
    { kind: "toggle", label: "File and line under blocks", on: showEvidence, onClick: () => setShowEvidence((v) => !v) },
    { kind: "toggle", label: "Legend", on: legend, onClick: () => setLegend((v) => !v) },
    { kind: "toggle", label: "Minimap", on: minimap, onClick: () => setMinimap((v) => !v) },
  ];
  const styles: MenuItem[] = THEMES.map((t) => ({ kind: "radio" as const, label: t.name, note: t.note, on: t.id === theme,
    swatch: `sw-${t.id}`, onClick: () => setTheme(t.id) }));

  return (
    <div className={`fm${drawing ? " drawing" : ""}`} data-graph={theme}>
      <Markers />
      <header className="fm-top">
        <div className="fm-proj">
          <h1>{deps ? (appName ?? meta.project) : code ? (repo.data?.name ?? meta.project) : meta.project}</h1>
          {meta.example && <span className="chip tone-violet fm-ex">Example</span>}
        </div>
        <div className="seg" role="group" aria-label="Which map">
          <button type="button" aria-pressed={map === "deps"} onClick={() => setMap("deps")}>Dependencies</button>
          <button type="button" aria-pressed={map === "flow"} onClick={() => setMap("flow")}>Flow</button>
        </div>
        {oneAction && setAction && <ActionPicker actions={actions} value={action} onChange={setAction} />}
        <div className="fm-actions">
          {deps && <SecurityChip findings={security.data?.findings ?? []} onShow={focusOn} />}
          {!deps && !code && (
            <button className="btn primary" type="button" onClick={startReplay} disabled={!trace || busy}>
              {Icons.play(18)} {busy ? "Running…" : "Test run"}
            </button>
          )}
          <button className="btn" type="button" onClick={() => void recheck()} disabled={rechecking}>
            {Icons.refresh(18)} {rescanLabel}
          </button>
          <Link className="btn" to={`/map/export${q}`}>{Icons.share(18)} Export</Link>
          <MoreMenu items={styles} label="Map style" button={<>{Icons.monitor(18)} Style</>} />
          {deps && checks.items.length > 0 && (
            <button className="btn primary" type="button" onClick={() => void checks.checkNow()} disabled={checks.running}>
              {Icons.activity(18)} {checks.progress ? `Checking ${checks.progress.done}/${checks.progress.total}…`
                : checks.running ? "Checking…" : "Check now"}
            </button>
          )}
          <MoreMenu items={menu} />
        </div>
      </header>
      {checks.asking && (
        <CheckConfirm asking={checks.asking} onStart={checks.confirm} onWithout={checks.withoutStarts} onCancel={checks.cancel} />
      )}
      {checks.error && <div className="notice" role="alert" style={{ margin: "8px 16px 0" }}>{checks.error}</div>}
      {scanning && (
        <section className="fm-scan" aria-label="Scan a folder">
          {meta.example ? <ScanHint /> : <ScanForm current={appName} onDone={() => { setScanning(false); reload(); }} />}
        </section>
      )}
      {notice && <div className="notice" role="alert" style={{ margin: "8px 16px 0" }}>{notice}</div>}
      <div className="fm-stage">
        <div className="fm-canvas" style={{ backgroundImage: "radial-gradient(var(--dot) 1.1px, transparent 1.4px)",
          backgroundSize: `${22 * zoom}px ${22 * zoom}px` } as CSSProperties}>
          <ReactFlow<BlockNode, LineEdge>
            nodes={nodes} edges={edges}
            onNodeMouseEnter={(_, n) => { if (!play) setPointed(traceFrom(n.id)); }} onNodeMouseLeave={() => setPointed(null)}
            onFocus={(e) => {   // the keyboard traces a block's path too
              const id = (e.target as HTMLElement).closest(".react-flow__node")?.getAttribute("data-id");
              if (id && !play) setPointed(traceFrom(id));
            }}
            onBlur={(e) => { if ((e.target as HTMLElement).closest(".react-flow__node")) setPointed(null); }}
            nodeTypes={nodeTypes} edgeTypes={edgeTypes}
            onNodesChange={onNodesChange} onSelectionChange={onSelectionChange} onPaneClick={() => setSel(null)}
            nodesConnectable={false} edgesFocusable={false} elementsSelectable minZoom={0.15} maxZoom={1.8}
            fitView fitViewOptions={{ padding: 0.08, maxZoom: 1.1 }} proOptions={{ hideAttribution: true }}
            aria-label="Flow map" zoomOnDoubleClick={false} deleteKeyCode={null}>
            {boxRects.length > 0 && (
              <ViewportPortal>
                {boxRects.map((b) => (
                  <div key={b.key} className="ff-box" role="group" aria-label={/^\d+$/.test(b.note) ? b.label : `${b.label} ${b.note}`}
                    style={{ transform: `translate(${b.x}px, ${b.y}px)`, width: b.w, height: b.h }}>
                    <span className="ff-box-label">{b.label}</span>
                    {b.note && <span className="ff-box-note">{b.note}</span>}
                  </div>
                ))}
              </ViewportPortal>
            )}
            {minimap && <MiniMap position="bottom-right" pannable zoomable ariaLabel="Mini map" nodeStrokeWidth={0}
              nodeColor={(n) => {
                const k = (n.data as BlockData).node.kind;
                return token(k === "llm" ? "--violet" : k === "gate" ? "--amber-strong" : "--line-2", "#9AAAB4");
              }}
              maskColor={token("--mask", "rgba(120, 140, 150, 0.18)")} />}
          </ReactFlow>

          <div className="fm-float fm-tools" role="toolbar" aria-label="Map tools">
            <button className="fm-ib" type="button" aria-label="Zoom out" onClick={() => rf.zoomOut({ duration: 200 })}>{Icons.minus(18)}</button>
            <button className="fm-ib" type="button" aria-label="Zoom in" onClick={() => rf.zoomIn({ duration: 200 })}>{Icons.plus(18)}</button>
            <button className="fm-ib" type="button" aria-label="Fit to screen" onClick={() => rf.fitView({ padding: 0.08, duration: 450 })}>{Icons.fit(18)}</button>
          </div>

          <label className="fm-float fm-search">
            {Icons.search(18)}
            <span className="visually-hidden">Find a step</span>
            <input type="search" name="find-step" placeholder={deps ? "Find a dependency, host or file" : "Find a step, app or file"} value={find}
              onChange={(e) => setFind(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && hits.size) focusOn([...hits][0]);
                if (e.key === "Escape") setFind("");
              }} />
            {query && <span className="c">{hits.size} found</span>}
          </label>

          {legend && (
            <div className="fm-float fm-legend" role="region" aria-label="Legend">
              <button className="fm-lh" type="button" onClick={() => setLegend(false)}>
                <span>Legend</span>{Icons.close(15)}
              </button>
              {deps ? <DepsLegend /> : code ? <CodeLegend /> : <Legend />}
            </div>
          )}

          {frame && played && (code || trace) && (
            <div className="fm-float fm-hud" role="status" aria-live="polite">
              <span className="s"><span className="d" style={{ background: frame.waiting ? "var(--amber-strong)" : frame.done ? (play?.rejected ? "var(--coral)" : "var(--teal)") : "var(--blue)" }} />
                {frame.waiting ? "Waiting for you" : frame.done ? (play?.rejected ? "Stopped at your gate" : code ? "Schedule played" : "Test run done")
                  : code ? `Watch it run · ${played.label}` : `Test run · ${played.label}`}</span>
              <span className="m">{elapsed} s{fellBack ? " · a fallback answered" : ""}</span>
              <span className="fm-prog" aria-hidden="true"><span style={{ width: `${progress}%` }} /></span>
              {!code && <span className="m">{frame.calls} calls · {frame.cached} cached · {(frame.tokens / 1000).toFixed(1)}k tokens</span>}
              {frame.waiting && (
                <>
                  <button className="btn warn" type="button" onClick={approve}>Approve: {flow.nodes.find((n) => n.id === frame.waiting)?.title}</button>
                  <button className="btn" type="button" onClick={reject}>Reject</button>
                </>
              )}
              {frame.done && <button className="btn" type="button" onClick={() => setPlay(null)}>Clear</button>}
            </div>
          )}
        </div>
        {selected && (
          <StepPanel key={selected.id} node={selected} flow={flow} tile={tileFor(selected)}
            health={deps ? health[selected.id] : undefined} example={meta.example} checking={checks.running}
            findings={findings[selected.id]}
            othersUp={checks.items.filter((i) => i.status === "up" && i.id !== selected.id).length}
            onCheck={(id) => void checks.checkNow([id])}
            state={frame?.nodes[selected.id] ?? "idle"} cap={frame?.caps[selected.id] ?? ""} waiting={frame?.waiting === selected.id}
            connectors={connectors} tipShown={!dismissed.has(selected.id)} layer={layer}
            actions={{ close: () => { setSel(null); setNodes((ns) => ns.map((n) => ({ ...n, selected: false }))); }, approve, reject, edit, reset, dismissTip }} />
        )}
        {!selected && code && <Faster flow={flow} onPoint={(ids) => setPointed(ids ? new Set(ids) : null)}
          onWatch={startReplay} watching={busy} canWatch={!!replay} />}
      </div>
    </div>
  );
}

function DepsLegend() {
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
function CodeLegend() {
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

function Legend() {
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
