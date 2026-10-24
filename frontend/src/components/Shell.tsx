import { createContext, useContext, useEffect, type ReactNode } from "react";
import { Outlet, useLocation, useMatches } from "react-router-dom";
import { Link, useProjectId } from "../projects/links";
import { markOpen, rememberPlace } from "../projects/memory";
import { ProjectPicker } from "../projects/ProjectPicker";
import { api, setProject, useApi } from "../api/client";
import type { Meta } from "../api/types";
import { Icons } from "./icons";
import { applyTheme, readTheme } from "./theme";
import { saveTheme as saveMapStyle, type GraphTheme } from "../flowmap/themes";
import { CountsProvider, useCounts } from "../security/counts";

const MetaContext = createContext<Meta>({ project: "My project", example: false, version: "" });
export const useMeta = () => useContext(MetaContext);

interface Item {
  to: string;
  label: string;
  icon: ReactNode;
  /** highlighted on these paths */
  active: RegExp;
  soon?: string;
  /** what the count beside it counts (D37) */
  count?: "issues" | "keys";
}

// Six places (D33, D37, D38): the map, what to fix, your keys, the Vault, the checks, and your coding agent. Apps and workflow runs
// stay one click away from the map's ⋯ menu and the Checks page.
const ITEMS: Item[] = [
  { to: "/", label: "Map", icon: Icons.map(20), active: /^\/($|map(\/|$)|connectors(\/|$))/ },
  { to: "/issues", label: "Issues", icon: Icons.shield(20), active: /^\/issues$/, count: "issues" },
  { to: "/keys", label: "Keys", icon: Icons.key(20), active: /^\/keys$/, count: "keys" },
  { to: "/vault", label: "Vault", icon: Icons.lock(20), active: /^\/vault$/ },
  { to: "/checks", label: "Checks", icon: Icons.activity(20), active: /^\/(checks|runs|live)(\/|$)/ },
  { to: "/connect", label: "Connect agent", icon: Icons.code(20), active: /^\/connect$/ },
];

/** A route with `handle: { bleed: true }` (the flow map) fills the page edge to edge. */
function useBleed(): boolean {
  return useMatches().some((m) => (m.handle as { bleed?: boolean } | undefined)?.bleed);
}

function Count({ of }: { of: "issues" | "keys" }) {
  const counts = useCounts();
  const n = counts[of];
  if (!n) return null;
  return <span className={`rail-count ${of}`} aria-label={`${n} ${of === "issues" ? "to fix" : "need you"}`}>{n}</span>;
}

let synced = false;

/** Once per load: the theme this browser chose, and the map style Settings saved when this browser has none (D40). */
function useLook(): void {
  useEffect(() => {
    applyTheme(readTheme());
    if (synced) return;
    synced = true;
    let mapStyleSaved = false;
    try { mapStyleSaved = localStorage.getItem("flowforge.graphTheme") !== null; } catch { /* private window */ }
    if (!mapStyleSaved) {
      api.get<{ map_style: GraphTheme | null }>("/settings").then((s) => { if (s.map_style) saveMapStyle(s.map_style); }, () => {});
    }
  }, []);
}

export function Shell() {
  useLook();
  const pid = useProjectId();
  setProject(pid);   // before any page renders: its requests go to this project (D39)
  return <ProjectShell key={pid ?? "home"} pid={pid} />;
}

/** One project's shell, or the home page's (D39). Keyed by project, so switching starts each one afresh. */
function ProjectShell({ pid }: { pid: string | undefined }) {
  const meta = useApi<Meta>(pid ? "/meta" : null);
  const location = useLocation();
  const bleed = useBleed();
  const value = meta.data ?? { project: "My project", example: false, version: "" };
  useEffect(() => {   // where you were, so switching back brings you here
    if (pid) { rememberPlace(pid, location.pathname + location.search); markOpen(pid); }
  }, [pid, location.pathname, location.search]);
  useEffect(() => {   // opened now, however you got here: the default after a restart (D39)
    if (pid) void api.post(`/projects/${encodeURIComponent(pid)}/open`).catch(() => {});
  }, [pid]);
  const at = pid ? location.pathname.slice(`/p/${encodeURIComponent(pid)}`.length) || "/" : location.pathname;

  return (
    <MetaContext.Provider value={value}>
      <CountsProvider active={!!pid}>
      <a className="skip-link" href="#main">Skip to content</a>
      <div className={`shell${bleed ? " bleed" : ""}`}>
        <nav className="rail" aria-label="Main">
          <ProjectPicker current={pid} />
          {pid ? ITEMS.map((item) => (
            <Link key={item.to} to={item.to} className="rail-item" title={item.soon ? `${item.label}: arrives in ${item.soon}` : item.label}
              aria-current={item.active.test(at) ? "page" : undefined}>
              {item.icon}
              <span>{item.label}</span>
              {item.count && <Count of={item.count} />}
              {item.soon && <span className="visually-hidden">(arrives in {item.soon})</span>}
            </Link>
          )) : (
            <Link to="/" className="rail-item" aria-current={location.pathname === "/" ? "page" : undefined}>
              {Icons.hub(20)}<span>Projects</span>
            </Link>
          )}
          <span className="rail-gap" />
          <Link to="/settings" className="rail-item" aria-current={at === "/settings" ? "page" : undefined} title="Settings">
            {Icons.gear(20)}<span>Settings</span>
          </Link>
        </nav>
        <main className="main" id="main" tabIndex={-1}>
          <div key={location.pathname} className={`page${bleed ? "" : " page-enter"}`}>
            <Outlet />
          </div>
        </main>
      </div>
      </CountsProvider>
    </MetaContext.Provider>
  );
}
