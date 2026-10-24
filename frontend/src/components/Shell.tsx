import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { Link, Outlet, useLocation, useMatches } from "react-router-dom";
import { useApi } from "../api/client";
import type { Meta } from "../api/types";
import { Icons } from "./icons";
import { CountsProvider, useCounts } from "../security/counts";

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
  /** what the count beside it counts (D37) */
  count?: "issues" | "keys";
}

// Five places (D33, D37): the map, what to fix, your keys, the checks, and your coding agent. Apps and workflow runs
// stay one click away from the map's ⋯ menu and the Checks page.
const ITEMS: Item[] = [
  { to: "/", label: "Map", icon: Icons.map(20), active: /^\/($|map(\/|$)|connectors(\/|$))/ },
  { to: "/issues", label: "Issues", icon: Icons.shield(20), active: /^\/issues$/, count: "issues" },
  { to: "/keys", label: "Keys", icon: Icons.key(20), active: /^\/keys$/, count: "keys" },
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

export function Shell() {
  const meta = useApi<Meta>("/meta");
  const location = useLocation();
  const bleed = useBleed();
  const value = meta.data ?? { project: "My project", example: false, version: "" };

  return (
    <MetaContext.Provider value={value}>
      <CountsProvider>
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
              {item.count && <Count of={item.count} />}
              {item.soon && <span className="visually-hidden">(arrives in {item.soon})</span>}
            </Link>
          ))}
          <span className="rail-gap" />
          <ThemeToggle />
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
