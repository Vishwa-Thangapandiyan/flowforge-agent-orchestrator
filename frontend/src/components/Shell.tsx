import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { Link, Outlet, useLocation, useMatches } from "react-router-dom";
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
  const icon = { system: Icons.monitor(20), light: Icons.sun(20), dark: Icons.moon(20) }[theme];
  return (
    <button type="button" className="rail-item rail-theme" onClick={() => setTheme(next[theme])} aria-label={`${label}. Change theme`}
      title={label}>
      {icon}
      <span>Theme</span>
    </button>
  );
}

interface Item {
  to: string;
  label: string;
  icon: ReactNode;
  /** highlighted on these paths */
  active: RegExp;
  soon?: string;
}

const ITEMS: Item[] = [
  { to: "/", label: "Flow map", icon: Icons.map(20), active: /^\/($|map(\/|$))/ },
  { to: "/runs", label: "Runs", icon: Icons.activity(20), active: /^\/(runs|live)(\/|$)/ },
  { to: "/connectors", label: "Connectors", icon: Icons.plug(20), active: /^\/connectors(\/|$)/ },
  { to: "/approvals", label: "Approvals", icon: Icons.check(20), active: /^\/approvals/, soon: "Phase 5" },
  { to: "/security", label: "Security", icon: Icons.shield(20), active: /^\/security/, soon: "Phase 4" },
];

/** A route with `handle: { bleed: true }` (the flow map) fills the page edge to edge. */
function useBleed(): boolean {
  return useMatches().some((m) => (m.handle as { bleed?: boolean } | undefined)?.bleed);
}

export function Shell() {
  const meta = useApi<Meta>("/meta");
  const location = useLocation();
  const bleed = useBleed();
  const value = meta.data ?? { project: "My project", example: false, version: "" };

  return (
    <MetaContext.Provider value={value}>
      <a className="skip-link" href="#main">Skip to content</a>
      <div className={`shell${bleed ? " bleed" : ""}`}>
        <nav className="rail" aria-label="Main">
          <Link to="/" className="rail-brand" aria-label="FlowForge, flow map">
            <img src="/favicon.svg" width={34} height={34} alt="" />
          </Link>
          {ITEMS.map((item) => (
            <Link key={item.to} to={item.to} className="rail-item" title={item.soon ? `${item.label}: arrives in ${item.soon}` : item.label}
              aria-current={item.active.test(location.pathname) ? "page" : undefined}>
              {item.icon}
              <span>{item.label}</span>
              {item.soon && <span className="visually-hidden">(arrives in {item.soon})</span>}
            </Link>
          ))}
          <span className="rail-gap" />
          <Link to="/connectors/new" className="rail-item rail-add" title="Add an app">
            {Icons.plus(20)}
            <span>Add app</span>
          </Link>
          <ThemeToggle />
        </nav>
        <main className="main" id="main" tabIndex={-1}>
          {value.example && !bleed && (
            <div className="example-banner" role="note">
              {Icons.spark(18)}
              <span><b>Example data.</b> Nothing here touches a real account. Real numbers come from your own runs.</span>
            </div>
          )}
          <div key={location.pathname} className={`page${bleed ? "" : " page-enter"}`}>
            <Outlet />
          </div>
        </main>
      </div>
    </MetaContext.Provider>
  );
}
