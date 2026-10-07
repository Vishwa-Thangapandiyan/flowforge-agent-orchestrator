import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { Link, NavLink, Outlet, useLocation } from "react-router-dom";
import { useApi } from "../api/client";
import type { Meta } from "../api/types";
import { Icons } from "./icons";

const MetaContext = createContext<Meta>({ project: "My project", example: false, version: "" });
export const useMeta = () => useContext(MetaContext);

type Theme = "system" | "light" | "dark";
const THEME_KEY = "flowforge.theme";

function readTheme(): Theme {
  try {
    const t = localStorage.getItem(THEME_KEY);
    return t === "light" || t === "dark" ? t : "system";
  } catch {
    return "system";
  }
}

function ThemeToggle() {
  const [theme, setTheme] = useState<Theme>(readTheme);
  useEffect(() => {
    if (theme === "system") document.documentElement.removeAttribute("data-theme");
    else document.documentElement.setAttribute("data-theme", theme);
    try {
      localStorage.setItem(THEME_KEY, theme);
    } catch {
      /* private window: the choice just isn't remembered */
    }
  }, [theme]);
  const next: Record<Theme, Theme> = { system: "light", light: "dark", dark: "system" };
  const label = { system: "Theme: system", light: "Theme: light", dark: "Theme: dark" }[theme];
  const icon = { system: Icons.monitor(18), light: Icons.sun(18), dark: Icons.moon(18) }[theme];
  return (
    <button type="button" className="theme-toggle" onClick={() => setTheme(next[theme])} aria-label={`${label}. Change theme`}>
      {icon}
      <span>{label}</span>
    </button>
  );
}

interface Item {
  to: string;
  label: string;
  icon: ReactNode;
  soon?: string;
  end?: boolean;
  /** also highlighted on these paths (a run's page belongs to Live run) */
  activeFor?: RegExp;
}

const ITEMS: Item[] = [
  { to: "/", label: "Overview", icon: Icons.hub(18), end: true },
  { to: "/connectors", label: "Connectors", icon: Icons.plug(18) },
  { to: "/plans", label: "Plan review", icon: Icons.list(18), soon: "Phase 4" },
  { to: "/live", label: "Live run", icon: Icons.play(18), activeFor: /^\/(live|runs\/[^/]+)/ },
  { to: "/approvals", label: "Approvals", icon: Icons.check(18), soon: "Phase 4" },
  { to: "/runs", label: "Run history", icon: Icons.history(18), end: true },
  { to: "/security", label: "Security", icon: Icons.shield(18), soon: "Phase 3" },
];

export function Shell() {
  const meta = useApi<Meta>("/meta");
  const [open, setOpen] = useState(false);
  const location = useLocation();
  useEffect(() => setOpen(false), [location.pathname]);
  const value = meta.data ?? { project: "My project", example: false, version: "" };

  return (
    <MetaContext.Provider value={value}>
      <a className="skip-link" href="#main">Skip to content</a>
      <div className="shell">
        <nav className={`nav${open ? " open" : ""}`} aria-label="Main">
          <NavLink to="/" className="brand" aria-label="FlowForge, overview">
            <img src="/favicon.svg" width={30} height={30} alt="" />
            <span>FlowForge</span>
          </NavLink>
          <button type="button" className="menu-button" aria-expanded={open} aria-controls="nav-links"
            onClick={() => setOpen((o) => !o)}>
            {Icons.menu(22)}
            <span className="visually-hidden">Menu</span>
          </button>
          <div className="nav-links" id="nav-links">
            {ITEMS.map((item) => {
              const body = (
                <>
                  <span style={{ display: "flex", alignItems: "center", gap: 10 }}>{item.icon}{item.label}</span>
                  {item.soon && <span className="soon">{item.soon}</span>}
                </>
              );
              // NavLink only marks its own route; a run's page also belongs to "Live run"
              return item.activeFor ? (
                <Link key={item.to} to={item.to} className="nav-link"
                  aria-current={item.activeFor.test(location.pathname) ? "page" : undefined}>{body}</Link>
              ) : (
                <NavLink key={item.to} to={item.to} end={item.end} className="nav-link">{body}</NavLink>
              );
            })}
            <NavLink to="/connectors/new" className="nav-add">{Icons.plus(18)} Add app</NavLink>
          </div>
          <div className="nav-foot">
            <ThemeToggle />
            <span>FlowForge {value.version} · runs on your machine</span>
          </div>
        </nav>
        <main className="main" id="main" tabIndex={-1}>
          {value.example && (
            <div className="example-banner" role="note">
              {Icons.spark(18)}
              <span><b>Example data.</b> Nothing here touches a real account. Real numbers come from your own runs.</span>
            </div>
          )}
          <div key={location.pathname} className="page page-enter">
            <Outlet />
          </div>
        </main>
      </div>
    </MetaContext.Provider>
  );
}
