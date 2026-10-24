// The home page (D39, docs/design/projects step 1): every project as a card, the example, and + New project. A new
// project is one step: its folder, scanned (plain code, nothing run or sent: D20), then its map.
import { type FormEvent, useState } from "react";
import { Navigate as RouterNavigate, useLocation, useNavigate as useRouterNavigate } from "react-router-dom";
import { api, useApi } from "../api/client";
import { Icons } from "../components/icons";
import { EmptyState, ErrorBox } from "../components/ui";
import { Link } from "./links";
import { markOpen, placeOf } from "./memory";
import "./projects.css";

export interface ProjectCard {
  id: string;
  name: string;
  path: string;
  added: string;
  opened: string | null;
  missing: boolean;
  summary: { dependencies: number; issues: number; keys_missing: number };
}

export interface ProjectsResponse {
  default: string | null;
  projects: ProjectCard[];
  example: { id: string; name: string };
}

const TILES = ["#2457C5", "#6B46C1", "#B93C2B", "#0B7A70", "#8A5A00", "#3A4756", "#1F7A45"];

/** A project's colour, the same everywhere it shows. */
export function tileColor(id: string): string {
  let h = 0;
  for (const c of id) h = (h * 31 + c.charCodeAt(0)) >>> 0;
  return id === "example" ? "#3A4756" : TILES[h % TILES.length];
}

/** Two letters for a project's tile: "trip-planner" → TP, "shop" → SH. */
export function initials(name: string): string {
  const words = name.split(/[^A-Za-z0-9]+/).filter(Boolean);
  const two = words.length > 1 ? words[0][0] + words[1][0] : (words[0] ?? "?").slice(0, 2);
  return two.toUpperCase();
}

function ago(at: string | null): string {
  if (!at) return "not opened yet";
  const s = Math.max(0, (Date.now() - new Date(at).getTime()) / 1000);
  if (s < 3600) return `opened ${Math.max(1, Math.round(s / 60))} min ago`;
  if (s < 86400) return `opened ${Math.round(s / 3600)} h ago`;
  return s < 172800 ? "opened yesterday" : `opened ${new Date(at).toLocaleDateString()}`;
}

function Card({ p, onChanged }: { p: ProjectCard; onChanged: () => void }) {
  const go = useRouterNavigate();
  const [menu, setMenu] = useState(false);
  const [naming, setNaming] = useState<string>();
  const [error, setError] = useState<string>();
  const open = () => {
    markOpen(p.id);
    go(placeOf(p.id));   // the project's shell tells the server it was opened
  };
  const rename = async (e: FormEvent) => {
    e.preventDefault();
    try { await api.patch(`/projects/${encodeURIComponent(p.id)}`, { name: naming }); setNaming(undefined); onChanged(); }
    catch (err) { setError(err instanceof Error ? err.message : "Couldn't rename"); }
  };
  const remove = async () => {
    if (!window.confirm(`Remove ${p.name} from FlowForge? Its map and checks go; your folder and code stay.`)) return;
    try { await api.del(`/projects/${encodeURIComponent(p.id)}`); onChanged(); }
    catch (err) { setError(err instanceof Error ? err.message : "Couldn't remove"); }
  };
  const s = p.summary;
  return (
    <li className="pj-card">
      <button type="button" className="pj-open" onClick={open} aria-label={`Open ${p.name}`}>
        <span className="pj-top">
          <span className="pj-tile" style={{ background: tileColor(p.id) }} aria-hidden="true">{initials(p.name)}</span>
          <span className="pj-name"><b>{p.name}</b><span className="pj-path">{p.path}</span></span>
        </span>
        <span className="pj-stats">
          <span className="chip grey">{s.dependencies} {s.dependencies === 1 ? "dependency" : "dependencies"}</span>
          {s.issues > 0 ? <span className="chip lv-high">⚠ {s.issues} to fix</span> : <span className="chip ok">✓ nothing to fix</span>}
          {s.keys_missing > 0 && <span className="chip lv-medium">🔑 {s.keys_missing} missing</span>}
          {p.missing && <span className="chip lv-high">folder not found</span>}
        </span>
        <span className="pj-when">{ago(p.opened)}</span>
      </button>
      <button type="button" className="pj-more" aria-label={`More for ${p.name}`} aria-expanded={menu} onClick={() => setMenu((v) => !v)}>⋯</button>
      {menu && (
        <div className="pj-menu" role="menu">
          <button type="button" role="menuitem" onClick={() => { setMenu(false); setNaming(p.name); }}>Rename</button>
          <button type="button" role="menuitem" className="pj-danger" onClick={() => { setMenu(false); void remove(); }}>Remove from FlowForge</button>
        </div>
      )}
      {naming !== undefined && (
        <form className="pj-rename" onSubmit={rename}>
          <input aria-label={`New name for ${p.name}`} value={naming} autoFocus onChange={(e) => setNaming(e.target.value)} />
          <button className="btn sm primary" type="submit" disabled={!naming.trim()}>Save</button>
          <button className="btn sm quiet" type="button" onClick={() => setNaming(undefined)}>Cancel</button>
        </form>
      )}
      {error && <p className="key-err" role="alert">{error}</p>}
    </li>
  );
}

export function ProjectsPage() {
  const list = useApi<ProjectsResponse>("/projects");
  const go = useRouterNavigate();
  const data = list.data;
  const head = (
    <div className="page-head">
      <div className="titles">
        <h1>Projects</h1>
        <p className="lede">Every app FlowForge maps. Open one to see its map, issues and keys.</p>
      </div>
      <Link className="btn primary" to="/projects/new">{Icons.plus(16)} New project</Link>
    </div>
  );
  if (list.error && !data) return <div className="pj-page">{head}<ErrorBox error={list.error} what="your projects" /></div>;
  if (!data) return <div className="pj-page" aria-busy="true">{head}</div>;
  const openExample = () => { markOpen(data.example.id); go(placeOf(data.example.id)); };
  return (
    <div className="pj-page">{head}
      {data.projects.length === 0 && (
        <EmptyState tone="teal" icon={Icons.map(28)} title="No projects yet"
          action={<Link className="btn primary" to="/projects/new">Map your first app</Link>}>
          Pick your app's folder: FlowForge reads its code (nothing is run or sent) and draws what it depends on.
        </EmptyState>
      )}
      <ul className="pj-grid">
        {data.projects.map((p) => <Card key={p.id} p={p} onChanged={list.reload} />)}
        <li className="pj-card pj-example">
          <button type="button" className="pj-open" onClick={openExample}>
            <span className="pj-top">
              <span className="pj-tile" style={{ background: tileColor(data.example.id) }} aria-hidden="true">EX</span>
              <span className="pj-name"><b>{data.example.name}</b><span className="pj-path">built in · read-only</span></span>
            </span>
            <span className="pj-stats"><span className="chip grey">try FlowForge without your code</span></span>
          </button>
        </li>
        <li className="pj-card pj-new">
          <Link to="/projects/new" className="pj-open"><span className="pj-plus">+</span><b>New project</b>
            <span className="pj-when">pick a folder · FlowForge maps it</span></Link>
        </li>
      </ul>
    </div>
  );
}

/** + New project (step 4): the folder, then its map. */
export function NewProjectPage() {
  const go = useRouterNavigate();
  const [path, setPath] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();
  const scan = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(undefined);
    try {
      const made = await api.post<ProjectCard>("/projects", { path: path.trim() });
      markOpen(made.id);
      go(`/p/${encodeURIComponent(made.id)}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't map that folder");
      setBusy(false);
    }
  };
  return (
    <div className="pj-page pj-wizard">
      <div className="page-head"><div className="titles"><h1>New project</h1>
        <p className="lede">Your coding agent sees it as soon as it's mapped: it's paired once, for every project.</p></div></div>
      <form className="pj-step" onSubmit={scan}>
        <h2>Which folder is your app in?</h2>
        <p className="pj-note">The scan is plain code: nothing is run, nothing is sent anywhere.</p>
        <div className="pj-in">
          <input aria-label="Your app's folder" placeholder="/home/you/code/my-app" value={path} autoFocus
            onChange={(e) => setPath(e.target.value)} disabled={busy} />
          <button className="btn primary" type="submit" disabled={busy || !path.trim()}>{busy ? "Reading your code…" : <>Scan {Icons.arrow(16)}</>}</button>
        </div>
        {busy && <div className="pj-prog" role="progressbar" aria-label="Reading your code"><i /></div>}
        {error && <p className="key-err" role="alert">{error}</p>}
      </form>
      <p className="pj-back"><Link to="/">← All projects</Link></p>
    </div>
  );
}

/** An address from before projects (`/issues`, `/keys`…): the same page of the default project. */
export function ToDefaultProject() {
  const list = useApi<ProjectsResponse>("/projects");
  const where = useLocation();
  if (!list.data) return null;
  const id = list.data.default;
  if (!id) return <RouterNavigate to="/" replace />;
  return <RouterNavigate to={`/p/${encodeURIComponent(id)}${where.pathname}${where.search}`} replace />;
}
