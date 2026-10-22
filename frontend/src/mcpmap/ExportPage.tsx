// The MCP Map export (D26, docs/mcp-map.md): the map to send, drawn from the same data as the flow map, and five
// ways to send it. Everything is made in the browser from what the API already masked (D16).
import { useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { useApi } from "../api/client";
import type { ChecksView, FlowResponse, HealthStatus } from "../api/types";
import { Icons } from "../components/icons";
import { useMeta } from "../components/Shell";
import { CardSkeleton, EmptyState, ErrorBox } from "../components/ui";
import { mapQuery, useMapId } from "../flowmap/mapId";
import { download, fileName, svgText, toPng } from "./exportMap";
import { layoutMap, took } from "./layout";
import { McpMapSvg } from "./McpMapSvg";
import { toMermaid } from "./mermaid";
import "./mcpmap.css";

const day = (iso: string) => new Date(iso).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });

export function ExportPage() {
  const map = useMapId();
  const flow = useApi<FlowResponse>(`/flow?layer=mine${mapQuery(map, "&")}`);
  const scan = useApi<{ name: string | null }>("/scan");
  const checks = useApi<ChecksView>("/checks");
  const meta = useMeta();
  const svg = useRef<SVGSVGElement>(null);
  const [dark, setDark] = useState(false);
  const [said, setSaid] = useState<string>();
  const quiet = useRef(0);

  const view = flow.data?.available ? flow.data : null;
  const health = useMemo(() => Object.fromEntries((checks.data?.items ?? []).map((i) => [i.id, i.status])) as Record<string, HealthStatus>,
    [checks.data]);
  const laid = useMemo(() => (view ? layoutMap(view, health) : null), [view, health]);

  if (flow.error) return <ErrorBox error={flow.error} what="the map" />;
  if (!flow.data) return <CardSkeleton lines={8} />;
  if (!view || !laid) {
    return <EmptyState tone="violet" icon={Icons.map(28)} title="No map to export yet">Scan a folder from the map page first.</EmptyState>;
  }
  const app = scan.data?.name ?? view.nodes.find((n) => n.id === "app")?.title ?? meta.project;
  const files = laid.files.length > 2 ? `${laid.files.length} files` : laid.files.join(", ") || "the repo";
  const sub = laid.timed
    ? `MCP map, read from ${files} on ${day(view.created_at)}. ${laid.calls} calls, ${laid.decisions} decisions, ${took(laid.span)} at best.`
    : `Dependency map, read from ${files} on ${day(view.created_at)}. ${laid.calls} dependencies.`;
  const mermaid = toMermaid(view, app);

  const say = (text: string) => {
    setSaid(text);
    window.clearTimeout(quiet.current);
    quiet.current = window.setTimeout(() => setSaid(undefined), 2500);
  };
  const run = async (what: () => Promise<void> | void, done: string) => {
    try { await what(); say(done); } catch (e) { say(e instanceof Error ? e.message : String(e)); }
  };
  const current = () => {
    if (!svg.current) throw new Error("The map isn't drawn yet.");
    return svg.current;
  };

  return (
    <>
      <header className="page-head">
        <div className="titles">
          <span className="eyebrow">{laid.timed ? "Flow" : "Dependencies"} · map v{view.version}</span>
          <h1>MCP Map</h1>
          <p className="lede">The map to send: lanes are kinds, time runs left to right.</p>
        </div>
        <div className="actions">
          <div className="seg" role="group" aria-label="Paper">
            <button type="button" aria-pressed={!dark} onClick={() => setDark(false)}>Light paper</button>
            <button type="button" aria-pressed={dark} onClick={() => setDark(true)}>Dark paper</button>
          </div>
          <Link className="btn" to={`/${mapQuery(map)}`}>Back to the map</Link>
        </div>
      </header>

      <div className="mm-actions" role="group" aria-label="Export">
        <button className="btn primary" type="button"
          onClick={() => void run(() => download(fileName(app, "svg"), svgText(current()), "image/svg+xml"), "Saved the SVG")}>
          {Icons.download(18)} Download SVG <small>documents, web</small>
        </button>
        <button className="btn" type="button"
          onClick={() => void run(async () => download(fileName(app, "png"), await toPng(current(), 2)), "Saved the PNG")}>
          {Icons.download(18)} PNG (2×) <small>slides, chat</small>
        </button>
        <button className="btn" type="button" onClick={() => window.print()}>
          {Icons.file(18)} PDF <small>reports, A4</small>
        </button>
        <button className="btn" type="button"
          onClick={() => void run(() => navigator.clipboard.writeText(mermaid), "Copied")}>
          {Icons.copy(18)} Copy as Mermaid <small>READMEs, PRs</small>
        </button>
        <button className="btn" type="button"
          onClick={() => void run(() => download(fileName(app, "json"), JSON.stringify({ mcp_map: 1, app, flow: view }, null, 2),
            "application/json"), "Saved the Flow JSON")}>
          {Icons.fileCode(18)} Flow JSON <small>tools, every file:line</small>
        </button>
        <span className="mm-said" role="status">{said}</span>
      </div>

      <div className="mm-frame mm-print">
        <McpMapSvg ref={svg} map={laid} app={app} sub={sub} dark={dark} />
      </div>

      <details className="mm-mermaid">
        <summary>See the Mermaid text</summary>
        <pre>{mermaid}</pre>
      </details>
      <p className="mm-rules">The six rules are in <code>docs/mcp-map.md</code>. Key values never appear: the map holds only what the scan already masked.</p>
    </>
  );
}
