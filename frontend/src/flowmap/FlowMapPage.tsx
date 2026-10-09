// The home page (D17): the Planner-drawn map of the app's AI flow. Pan, zoom and drag; click a block for its
// evidence; replay a traced test order; edit through overrides that never touch your code.
import {
  MiniMap, ReactFlow, ReactFlowProvider, useNodesState, useReactFlow, useViewport,
  type NodeChange, type OnSelectionChangeParams,
} from "@xyflow/react";
import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, useApi } from "../api/client";
import type { Connector, FlowResponse, FlowView, NodeKind, Trace } from "../api/types";
import { when } from "../components/format";
import { Icons } from "../components/icons";
import { useMeta } from "../components/Shell";
import { EmptyState, ErrorBox } from "../components/ui";
import { edgeTypes, Markers, type LineEdge } from "./FlowEdge";
import { autoLayout, handlesFor, placeAll, sizeOf } from "./layout";
import { nodeTypes, typeFor, type BlockData, type BlockNode, type TileSource } from "./nodes";
import { buildReplay, frameAt, type Frame } from "./replay";
import { StepPanel } from "./StepPanel";
import "./flowmap.css";

const TIPS_KEY = "flowforge.tips.dismissed";

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
  const [layer, setLayer] = useState<"mine" | "planner">("mine");
  const flow = useApi<FlowResponse>(`/flow?layer=${layer}`);
  const trace = useApi<Trace>(flow.data?.available ? "/flow/trace" : null);
  const connectors = useApi<Connector[]>("/connectors");
  if (flow.error) return <div style={{ padding: 24 }}><ErrorBox error={flow.error} what="the flow map" /></div>;
  if (!flow.data) return <div className="fm" aria-busy="true"><div className="fm-stage"><div className="fm-canvas skeleton" /></div></div>;
  if (!flow.data.available) {
    return (
      <div style={{ padding: "32px clamp(16px, 3vw, 40px)" }}>
        <EmptyState tone="violet" icon={Icons.map(28)} title="No map yet">{flow.data.message}</EmptyState>
      </div>
    );
  }
  return (
    <ReactFlowProvider>
      <MapView flow={flow.data} trace={trace.data ?? null} connectors={connectors.data ?? []} layer={layer}
        setLayer={setLayer} reload={flow.reload} />
    </ReactFlowProvider>
  );
}

interface ViewProps {
  flow: FlowView;
  trace: Trace | null;
  connectors: Connector[];
  layer: "mine" | "planner";
  setLayer: (l: "mine" | "planner") => void;
  reload: () => void;
}

interface Play {
  t: number;
  running: boolean;
  approved: boolean;
  rejected: boolean;
}

function MapView({ flow, trace, connectors, layer, setLayer, reload }: ViewProps) {
  const meta = useMeta();
  const navigate = useNavigate();
  const rf = useReactFlow<BlockNode, LineEdge>();
  const { zoom } = useViewport();
  const [nodes, setNodes, onNodesChangeBase] = useNodesState<BlockNode>([]);
  const [sel, setSel] = useState<string | null>(null);
  const [q, setQ] = useState("");
  const [cp, setCp] = useState(false);
  const [showEvidence, setShowEvidence] = useState(true);
  const [legend, setLegend] = useState(false);
  const [dismissed, setDismissed] = useState(readDismissed);
  const [play, setPlay] = useState<Play | null>(null);
  const [rechecking, setRechecking] = useState(false);
  const [notice, setNotice] = useState<string>();
  const saveTimer = useRef<number>(0);
  const pending = useRef<Record<string, [number, number]>>({});
  const fitted = useRef(false);

  const kinds = useMemo(() => Object.fromEntries(flow.nodes.map((n) => [n.id, n.kind])) as Record<string, NodeKind>, [flow.nodes]);
  const replay = useMemo(() => (trace ? buildReplay(flow.nodes, flow.edges, trace) : null), [flow.nodes, flow.edges, trace]);
  const frame: Frame | null = useMemo(() => (play && replay ? frameAt(replay, play.t, play.approved, play.rejected) : null), [play, replay]);

  // --- blocks: positions from the server (or dagre for new ones), data from the current view --------------
  const tileOf = useCallback((id: string | null): TileSource | null => {
    if (!id) return null;
    const app = flow.apps[id];
    const c = connectors.find((x) => x.id === id);
    if (c) return c;
    return { id, type: app?.type ?? "http", name: app?.name ?? id };
  }, [flow.apps, connectors]);

  const query = q.trim().toLowerCase();
  const hits = useMemo(() => new Set(query ? flow.nodes.filter((n) => [n.title, n.connector, flow.apps[n.connector ?? ""]?.name,
    n.op?.tool, n.op?.path, ...n.evidence.map((e) => e.ref)].filter(Boolean).join(" ").toLowerCase().includes(query)).map((n) => n.id) : []),
  [query, flow.nodes, flow.apps]);

  const dataFor = useCallback((id: string): BlockData | null => {
    const n = flow.nodes.find((x) => x.id === id);
    if (!n) return null;
    const retry = flow.edges.find((e) => e.kind === "retry" && e.source === id);
    return {
      node: n, tile: n.kind === "gate" || n.kind === "end" ? null : tileOf(n.connector), state: frame?.nodes[id] ?? "idle",
      cap: frame?.caps[id] ?? "", search: query ? (hits.has(id) ? "hit" : "miss") : null, cp: cp && n.on_critical_path,
      showTip: !dismissed.has(id) && !frame, showEvidence, retryMax: retry?.max ?? null,
    };
  }, [flow.nodes, flow.edges, tileOf, frame, query, hits, cp, dismissed, showEvidence]);

  useEffect(() => {
    const placed = placeAll(flow.nodes, flow.edges, flow.positions);
    setNodes((current) => {
      const at = Object.fromEntries(current.map((n) => [n.id, n.position]));
      return flow.nodes.map((n) => {
        const size = sizeOf(n.kind);
        const p = at[n.id] ?? { x: placed[n.id][0], y: placed[n.id][1] };
        return { id: n.id, type: typeFor(n.kind), position: p, width: size.w, height: size.h, data: dataFor(n.id)!,
          selected: current.find((c) => c.id === n.id)?.selected ?? false };
      });
    });
    // positions only reset when the map itself changes; data updates are below
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [flow]);

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
      if (Object.keys(positions).length) api.put("/flow/positions", { positions, replace }).catch(() => undefined);
    }, replace ? 0 : 400);
  }, []);

  const onNodesChange = useCallback((changes: NodeChange<BlockNode>[]) => {
    onNodesChangeBase(changes);
    for (const c of changes) {
      if (c.type === "position" && c.position && !c.dragging) {
        pending.current[c.id] = [Math.round(c.position.x), Math.round(c.position.y)];
        savePositions();
      }
    }
  }, [onNodesChangeBase, savePositions]);

  const onSelectionChange = useCallback(({ nodes: picked }: OnSelectionChangeParams) => {
    setSel(picked[0]?.id ?? null);
  }, []);

  // --- lines ----------------------------------------------------------------------------------------------
  const posNow = useMemo(() => Object.fromEntries(nodes.map((n) => [n.id, [n.position.x, n.position.y] as [number, number]])), [nodes]);
  const cpEdges = useMemo(() => {
    const path = flow.critical_path.path;
    return new Set(path.slice(1).map((id, i) => `${path[i]}>${id}`));
  }, [flow.critical_path.path]);
  const edges: LineEdge[] = useMemo(() => flow.edges.filter((e) => kinds[e.source] && kinds[e.target]).map((e) => {
    const h = handlesFor(e, kinds, posNow);
    return {
      id: e.id, source: e.source, target: e.target, type: "flow", sourceHandle: h.s, targetHandle: h.t,
      focusable: false, selectable: false,
      data: {
        edge: e, state: frame?.edges[e.id] ?? "idle", cp: cp && cpEdges.has(`${e.source}>${e.target}`),
        dim: !!query && !(hits.has(e.source) && hits.has(e.target)), guard: kinds[e.target] === "llm" && e.kind !== "fallback",
      },
    };
  }), [flow.edges, kinds, posNow, frame, cp, cpEdges, query, hits]);

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
        const next = p.t + dt;
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
    setPlay({ t: 0, running: true, approved: false, rejected: false });
    setSel(null);
  };
  const approve = () => setPlay((p) => (p ? { ...p, approved: true, running: true } : p));
  const reject = () => setPlay((p) => (p ? { ...p, rejected: true, running: true } : p));

  // --- edits ----------------------------------------------------------------------------------------------
  const edit = async (body: Record<string, unknown>) => {
    await api.post("/flow/overrides", body);
    reload();
  };
  const reset = async (nodeId: string) => {
    await api.del(`/flow/nodes/${encodeURIComponent(nodeId)}/overrides`);
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
    const id = `step_${Date.now().toString(36)}`;
    try {
      await api.put("/flow/positions", { positions: { [id]: [Math.round(mid.x - 98), Math.round(mid.y - 32)] } });
      await api.post("/flow/overrides", { op: "add_node", new_node: { id, kind: "code", title: "New step", what: "A step you added." } });
      setLayer("mine");
      reload();
      setSel(id);
    } catch (e) {
      setNotice(e instanceof Error ? e.message : String(e));
    }
  };
  const retidy = () => {
    const laid = autoLayout(flow.nodes, flow.edges);
    setNodes((ns) => ns.map((n) => (laid[n.id] ? { ...n, position: { x: laid[n.id][0], y: laid[n.id][1] } } : n)));
    pending.current = { ...laid };
    savePositions(true);
    window.setTimeout(() => rf.fitView({ padding: 0.08, duration: 500 }), 30);
  };
  const recheck = async () => {
    if (flow.pending) { navigate("/map/recheck"); return; }
    setRechecking(true);
    try {
      await api.post("/flow/recheck");
      navigate("/map/recheck");
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
  };

  const selected = sel ? flow.nodes.find((n) => n.id === sel) : undefined;
  const unconfirmed = flow.nodes.filter((n) => n.status === "unconfirmed");
  const bottleneck = flow.critical_path.bottleneck ? flow.nodes.find((n) => n.id === flow.critical_path.bottleneck) : undefined;
  const busy = !!play && !frame?.done;
  const elapsed = frame ? (frame.t / 1000).toFixed(1) : "0.0";
  const progress = frame ? Math.round((Object.values(frame.nodes).filter((s) => !["idle", "running", "retry", "waiting"].includes(s)).length / Math.max(1, flow.nodes.length)) * 100) : 0;
  const fellBack = !!frame && !!trace && trace.steps.some((s) => s.outcome === "failed" && (frame.nodes[s.node] === "failed"));

  return (
    <div className="fm">
      <Markers />
      <header className="fm-top">
        <div className="fm-proj">
          <h1>{meta.project}</h1>
          <small>
            <span>{flow.counts.steps} steps</span><span>·</span><span>{flow.counts.gates} gates</span>
            {flow.counts.unconfirmed > 0 && <><span>·</span><span>{flow.counts.unconfirmed} unconfirmed</span></>}
            {meta.example && <span className="chip tone-violet" style={{ padding: "2px 8px", fontSize: 11 }}>Example data</span>}
          </small>
        </div>
        <Link className="fm-planner" to="/map/how" aria-label="The Planner drew this map. See how">
          <span className="fm-spark">{Icons.spark(18)}</span>
          <span>
            <span className="k"><span className="fm-live" />Planner · drew this map</span>
            <span className="v">Map v{flow.version}<span>from your code · {when(flow.created_at)}</span></span>
          </span>
        </Link>
        <div className="fm-actions">
          <div className="seg" role="group" aria-label="Which version of the map">
            <button type="button" aria-pressed={layer === "planner"} onClick={() => setLayer("planner")}>Planner's map</button>
            <button type="button" aria-pressed={layer === "mine"} onClick={() => setLayer("mine")}>
              With my edits<span className="n">{flow.counts.edits}</span>
            </button>
          </div>
          <button className="btn ai" type="button" onClick={recheck} disabled={rechecking}>
            {Icons.refresh(18)} {flow.pending ? "Review the re-check" : rechecking ? "Re-checking…" : "Re-check the repo"}
          </button>
          <button className="btn primary" type="button" onClick={startReplay} disabled={!trace || busy}>
            {Icons.play(18)} {busy ? "Running…" : "Test run"}
          </button>
        </div>
      </header>
      {notice && <div className="notice" role="alert" style={{ margin: "8px 16px 0" }}>{notice}</div>}
      <div className="fm-stage">
        <div className="fm-canvas" style={{ backgroundImage: "radial-gradient(var(--dot) 1.1px, transparent 1.4px)",
          backgroundSize: `${22 * zoom}px ${22 * zoom}px` } as CSSProperties}>
          <ReactFlow<BlockNode, LineEdge>
            nodes={nodes} edges={edges} nodeTypes={nodeTypes} edgeTypes={edgeTypes}
            onNodesChange={onNodesChange} onSelectionChange={onSelectionChange} onPaneClick={() => setSel(null)}
            nodesConnectable={false} edgesFocusable={false} elementsSelectable minZoom={0.15} maxZoom={1.8}
            fitView fitViewOptions={{ padding: 0.08, maxZoom: 1.1 }} proOptions={{ hideAttribution: true }}
            aria-label="Flow map" zoomOnDoubleClick={false} deleteKeyCode={null}>
            <MiniMap position="bottom-right" pannable zoomable ariaLabel="Mini map" nodeStrokeWidth={0}
              nodeColor={(n) => {
                const k = (n.data as BlockData).node.kind;
                return token(k === "llm" ? "--violet" : k === "gate" ? "--amber-strong" : "--line-2", "#9AAAB4");
              }}
              maskColor={token("--mask", "rgba(120, 140, 150, 0.18)")} />
          </ReactFlow>

          <div className="fm-tl">
            <div className="fm-float fm-tools" role="toolbar" aria-label="Map tools">
              <button className="fm-ib" type="button" aria-label="Zoom out" onClick={() => rf.zoomOut({ duration: 200 })}>{Icons.minus(18)}</button>
              <span className="fm-zoom" aria-live="polite">{Math.round(zoom * 100)}%</span>
              <button className="fm-ib" type="button" aria-label="Zoom in" onClick={() => rf.zoomIn({ duration: 200 })}>{Icons.plus(18)}</button>
              <span className="fm-sep" />
              <button className="fm-tbtn" type="button" onClick={() => rf.fitView({ padding: 0.08, duration: 450 })}>{Icons.fit(18)} Fit</button>
              <button className="fm-tbtn" type="button" onClick={retidy}>{Icons.tidy(18)} Re-tidy</button>
              <span className="fm-sep" />
              <button className="fm-tbtn" type="button" aria-pressed={cp} onClick={() => setCp((v) => !v)}>{Icons.route(18)} Critical path</button>
              <button className="fm-tbtn" type="button" aria-pressed={showEvidence} onClick={() => setShowEvidence((v) => !v)}>{Icons.fileCode(18)} Evidence</button>
              <span className="fm-sep" />
              <button className="fm-tbtn" type="button" onClick={addStep}>{Icons.addBox(18)} Add step</button>
            </div>
            {unconfirmed.length > 0 && !frame && (
              <button className="fm-note unc" type="button" onClick={() => focusOn(unconfirmed[0].id)}>
                {Icons.question(16)}<b>{unconfirmed.length} step{unconfirmed.length > 1 ? "s" : ""} unconfirmed</b><span className="m">no evidence in the repo</span>
              </button>
            )}
            {cp && bottleneck && (
              <span className="fm-note static">{Icons.route(16)}<span>Bottleneck: <b>{bottleneck.title}</b></span>
                <span className="m">{((bottleneck.estimate_ms ?? 0) / 1000).toFixed(1)} s of {(flow.critical_path.length_ms / 1000).toFixed(1)} s</span></span>
            )}
          </div>

          <label className="fm-float fm-search">
            {Icons.search(18)}
            <span className="visually-hidden">Find a step</span>
            <input type="search" name="find-step" placeholder="Find a step, app or file" value={q} onChange={(e) => setQ(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && hits.size) focusOn([...hits][0]);
                if (e.key === "Escape") setQ("");
              }} />
            {query && <span className="c">{hits.size} found</span>}
          </label>

          <div className="fm-float fm-legend">
            <button className="fm-lh" type="button" aria-expanded={legend} onClick={() => setLegend((v) => !v)}>
              <span>Legend</span><span style={{ transform: `rotate(${legend ? 180 : 0}deg)`, display: "inline-flex" }}>{Icons.chevron(15)}</span>
            </button>
            {legend && <Legend />}
          </div>

          {frame && trace && (
            <div className="fm-float fm-hud" role="status" aria-live="polite">
              <span className="s"><span className="d" style={{ background: frame.waiting ? "var(--amber-strong)" : frame.done ? (play?.rejected ? "var(--coral)" : "var(--teal)") : "var(--blue)" }} />
                {frame.waiting ? "Waiting for you" : frame.done ? (play?.rejected ? "Stopped at your gate" : "Test run done") : `Test run · ${trace.label}`}</span>
              <span className="m">{elapsed} s{fellBack ? " · a fallback answered" : ""}</span>
              <span className="fm-prog" aria-hidden="true"><span style={{ width: `${progress}%` }} /></span>
              <span className="m">{frame.calls} calls · {frame.cached} cached · {(frame.tokens / 1000).toFixed(1)}k tokens</span>
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
          <StepPanel key={selected.id} node={selected} flow={flow} tile={selected.kind === "gate" ? null : tileOf(selected.connector)}
            state={frame?.nodes[selected.id] ?? "idle"} cap={frame?.caps[selected.id] ?? ""} waiting={frame?.waiting === selected.id}
            connectors={connectors} tipShown={!dismissed.has(selected.id)} layer={layer}
            actions={{ close: () => { setSel(null); setNodes((ns) => ns.map((n) => ({ ...n, selected: false }))); }, approve, reject, edit, reset, dismissTip }} />
        )}
      </div>
    </div>
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
