// The re-check diff (D17, docs/design/flow-map-artboards/Recheck). Re-checking never overwrites the map:
// it shows what changed, and you pick what to take. Saving makes a new version; the old one stays listed.
import { ReactFlow, ReactFlowProvider } from "@xyflow/react";
import { useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, useApi } from "../api/client";
import type { Change, Connector, FlowEdge, FlowNode, FlowResponse, NodeKind, PendingVersion } from "../api/types";
import { when } from "../components/format";
import { Icons } from "../components/icons";
import { CardSkeleton, EmptyState, ErrorBox } from "../components/ui";
import { edgeTypes, Markers, type LineEdge } from "./FlowEdge";
import { handlesFor, placeAll, sizeOf } from "./layout";
import { nodeTypes, typeFor, type BlockData, type BlockNode } from "./nodes";
import "./flowmap.css";
import "./how.css";

type Take = Record<string, boolean | string>;
const TYPE_LABEL: Record<Change["type"], string> = { add: "Added", change: "Changed", remove: "Removed", conflict: "Needs you", kept: "Yours, kept" };

export function Recheck() {
  const current = useApi<FlowResponse>("/flow?layer=planner");
  const pendingNo = current.data && current.data.available ? current.data.pending : null;
  const pending = useApi<PendingVersion>(pendingNo ? `/flow/versions/${pendingNo}` : null);
  const connectors = useApi<Connector[]>("/connectors");

  if (current.error) return <ErrorBox error={current.error} what="the map" />;
  if (!current.data) return <CardSkeleton lines={6} />;
  if (!current.data.available || !pendingNo) {
    return (
      <EmptyState tone="violet" icon={Icons.refresh(28)} title="Nothing to review"
        action={<Link className="btn primary" to="/">Back to the map</Link>}>
        Re-check the repo from the map. The Planner looks again and shows you what changed; nothing changes until you save.
      </EmptyState>
    );
  }
  if (pending.error) return <ErrorBox error={pending.error} what="the re-check" />;
  if (!pending.data) return <CardSkeleton lines={6} />;
  return <Review base={current.data} pending={pending.data} connectors={connectors.data ?? []} />;
}

function Review({ base, pending, connectors }: { base: Extract<FlowResponse, { available: true }>; pending: PendingVersion; connectors: Connector[] }) {
  const navigate = useNavigate();
  const [take, setTake] = useState<Take>(pending.default_take);
  const [view, setView] = useState<"diff" | "old" | "new">("diff");
  const [sel, setSel] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string>();
  const changes = pending.changes;

  const byNode = useMemo(() => {
    const m = new Map<string, Change>();
    for (const c of changes) for (const id of c.nodes) m.set(id, c);
    return m;
  }, [changes]);

  // the diff shows the new version plus the blocks it would remove
  const removed = base.nodes.filter((n) => !pending.nodes.some((p) => p.id === n.id));
  const allNodes: FlowNode[] = useMemo(() => {
    if (view === "old") return base.nodes;
    const skipped = (n: FlowNode) => {
      const c = byNode.get(n.id);
      return c?.type === "add" && take[c.id] === false;
    };
    const newNodes = pending.nodes.map((n) => {
      const c = byNode.get(n.id);
      const kept = c && (c.type === "change" || c.type === "conflict") && (take[c.id] === false || take[c.id] === "mine") && view === "new";
      return kept ? base.nodes.find((b) => b.id === n.id) ?? n : n;
    });
    const back = removed.filter((n) => view === "diff" || take[byNode.get(n.id)?.id ?? ""] === false);
    return [...newNodes.filter((n) => view === "diff" || !skipped(n)), ...back];
  }, [view, base.nodes, pending.nodes, removed, byNode, take]);
  const ids = new Set(allNodes.map((n) => n.id));
  const allEdges: FlowEdge[] = [...pending.edges, ...base.edges.filter((e) => removed.some((r) => r.id === e.source || r.id === e.target))]
    .filter((e, i, arr) => ids.has(e.source) && ids.has(e.target) && arr.findIndex((x) => x.id === e.id) === i);
  const placed = placeAll(allNodes, allEdges, base.positions);

  const rfNodes: BlockNode[] = allNodes.map((n) => {
    const c = byNode.get(n.id);
    const choice = c ? take[c.id] : undefined;
    const off = !!c && choice === false;
    const data: BlockData = {
      node: { ...n, yours: [], on_critical_path: false, stats: null, tip: null, planner_connector: n.connector } as FlowNode,
      tile: n.connector && n.kind !== "gate" ? connectors.find((x) => x.id === n.connector) ?? { id: n.connector, type: "http", name: n.connector } : null,
      state: "idle", cap: "", search: sel && c?.id !== sel ? "miss" : null, cp: false, showTip: false, showEvidence: false, retryMax: null,
      ...(view === "diff" && c ? {
        diff: c.type, diffOff: off,
        diffTag: off ? "skipped" : { add: "new", change: "changed", remove: "removed", conflict: choice === "planner" ? "Planner's pick" : "your call", kept: "yours · kept" }[c.type],
      } : {}),
    };
    const size = sizeOf(n.kind);
    return { id: n.id, type: typeFor(n.kind), position: { x: placed[n.id][0], y: placed[n.id][1] }, width: size.w, height: size.h, data, draggable: false, selectable: false };
  });
  const kinds = Object.fromEntries(allNodes.map((n) => [n.id, n.kind])) as Record<string, NodeKind>;
  const rfEdges: LineEdge[] = allEdges.map((e) => {
    const h = handlesFor(e, kinds, placed);
    return {
      id: e.id, source: e.source, target: e.target, type: "flow", sourceHandle: h.s, targetHandle: h.t, focusable: false, selectable: false,
      data: { edge: e, state: "idle", cp: false, dim: !!sel && !byNode.get(e.source) && !byNode.get(e.target), guard: false },
    };
  });

  const counts = (type: Change["type"]) => changes.filter((c) => c.type === type).length;
  const taking = changes.filter((c) => c.type !== "kept" && (take[c.id] === true || take[c.id] === "planner")).length;
  const save = async () => {
    setSaving(true);
    setError(undefined);
    try {
      await api.post(`/flow/versions/${pending.version}/accept`, { take });
      navigate("/");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setSaving(false);
    }
  };
  const keep = async () => {
    await api.post(`/flow/versions/${pending.version}/discard`).catch(() => undefined);
    navigate("/");
  };

  return (
    <>
      <header className="page-head">
        <div className="titles">
          <span className="eyebrow">Re-check · v{pending.base_version} → v{pending.version}</span>
          <h1>What changed in your repo</h1>
        </div>
        <div className="actions"><Link className="btn" to="/">Back to the map</Link></div>
      </header>
      <section className="rc-banner" aria-label="Re-check summary">
        <span className="fm-spark" style={{ width: 44, height: 44 }}>{Icons.spark(22)}</span>
        <div><h2>The Planner re-checked your repo</h2><p>{pending.fact_sheet_hash} · {when(pending.created_at)}</p></div>
        <div className="rc-counts">
          {counts("add") > 0 && <span className="rc-cnt"><i style={{ background: "var(--teal)" }} />{counts("add")} added</span>}
          {counts("change") > 0 && <span className="rc-cnt"><i style={{ background: "var(--violet)" }} />{counts("change")} changed</span>}
          {counts("remove") > 0 && <span className="rc-cnt"><i style={{ background: "var(--coral)" }} />{counts("remove")} removed</span>}
          {counts("conflict") > 0 && <span className="rc-cnt"><i style={{ background: "var(--amber-strong)" }} />{counts("conflict")} needs you</span>}
          {counts("kept") > 0 && <span className="rc-cnt"><i style={{ background: "var(--fg)" }} />{counts("kept")} of yours kept</span>}
        </div>
      </section>

      <div className="rc-map">
        <Markers />
        <div className="rc-tools">
          <div className="seg" role="group" aria-label="What to show">
            <button type="button" aria-pressed={view === "diff"} onClick={() => setView("diff")}>Diff</button>
            <button type="button" aria-pressed={view === "old"} onClick={() => setView("old")}>v{pending.base_version} (now)</button>
            <button type="button" aria-pressed={view === "new"} onClick={() => setView("new")}>v{pending.version} (after)</button>
          </div>
        </div>
        <ReactFlowProvider>
          <ReactFlow<BlockNode, LineEdge> nodes={rfNodes} edges={rfEdges} nodeTypes={nodeTypes} edgeTypes={edgeTypes}
            nodesDraggable={false} nodesConnectable={false} elementsSelectable={false} fitView fitViewOptions={{ padding: 0.06 }}
            minZoom={0.25} maxZoom={1.5} proOptions={{ hideAttribution: true }} deleteKeyCode={null} nodesFocusable={false}
            aria-label="The map, with the changes marked" />
        </ReactFlowProvider>
      </div>

      <div className="card-head"><h2>Changes</h2><span className="card-note">Pick what to take. Nothing changes until you save.</span></div>
      <div className="rc-changes">
        {changes.map((c) => (
          <div key={c.id} className={`rc-change${sel === c.id ? " sel" : ""}`} onMouseEnter={() => setSel(c.id)} onMouseLeave={() => setSel(null)}>
            <span className={`rc-type ${c.type}`}>{TYPE_LABEL[c.type]}</span>
            <b>{c.title}</b>
            {c.detail && <p>{c.detail}</p>}
            {c.evidence && <span className="rc-ev">{c.evidence}</span>}
            {c.type !== "kept" && (
              <div className="seg" role="group" aria-label={`Take: ${c.title}`}>
                {((c.choices as [string, string][] | undefined) ?? ([[true, c.type === "remove" ? "Remove it" : "Take it"], [false, c.type === "remove" ? "Keep it" : "Skip"]] as [boolean, string][]))
                  .map(([value, label]: [boolean | string, string]) => (
                  <button key={String(value)} type="button" aria-pressed={take[c.id] === value}
                    onFocus={() => setSel(c.id)} onClick={() => setTake((t) => ({ ...t, [c.id]: value }))}>{label}</button>
                ))}
              </div>
            )}
          </div>
        ))}
      </div>
      {error && <div className="error-box" role="alert">{error}</div>}
      <div className="rc-foot">
        <span>Your edits stay on top. v{pending.base_version} stays listed. Gates on payments and messages are kept whatever you pick.</span>
        <button className="btn" type="button" onClick={keep}>Keep v{pending.base_version} as it is</button>
        <button className="btn primary" type="button" onClick={save} disabled={saving}>
          {saving ? "Saving…" : `Save as map v${pending.version}${taking ? ` · ${taking} change${taking > 1 ? "s" : ""}` : ""}`}
        </button>
      </div>
    </>
  );
}
