// The project picker at the top of the rail (D39, docs/design/projects step 2): your open projects, each opening where
// you left it; × closes one from this list and never deletes it; then All projects and + New project.
import { useEffect, useRef, useState } from "react";
import { useNavigate as useRouterNavigate } from "react-router-dom";
import { useApi } from "../api/client";
import { closeProject, markOpen, openProjects, placeOf } from "./memory";
import { initials, type ProjectsResponse, tileColor } from "./ProjectsPage";

export function ProjectPicker({ current }: { current: string | undefined }) {
  const list = useApi<ProjectsResponse>("/projects");
  const go = useRouterNavigate();
  const [open, setOpen] = useState(false);
  const [, redraw] = useState(0);
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const away = (e: MouseEvent) => { if (box.current && !box.current.contains(e.target as Node)) setOpen(false); };
    document.addEventListener("mousedown", away);
    return () => document.removeEventListener("mousedown", away);
  }, [open]);
  const data = list.data;
  const name = (id: string) => id === data?.example.id ? data.example.name : data?.projects.find((p) => p.id === id)?.name ?? id;
  const known = (id: string) => id === data?.example.id || !!data?.projects.some((p) => p.id === id);
  const ids = [...new Set([...(current ? [current] : []), ...openProjects()])].filter((id) => !data || known(id));
  const here = current ? name(current) : "All projects";
  const switchTo = (id: string) => { setOpen(false); markOpen(id); go(placeOf(id)); };
  const close = (id: string) => {
    closeProject(id);
    redraw((n) => n + 1);
    if (id === current) {
      const next = openProjects().find(known);
      setOpen(false);
      go(next ? placeOf(next) : "/");
    }
  };
  return (
    <div className="pk" ref={box} onKeyDown={(e) => e.key === "Escape" && setOpen(false)}>
      <button type="button" className="pk-tile" aria-haspopup="menu" aria-expanded={open} title={here}
        aria-label={`Project: ${here}. Switch project`} onClick={() => setOpen((v) => !v)}
        style={{ background: current ? tileColor(current) : "var(--teal)" }}>
        {current ? initials(name(current)) : "⌂"}<span className="pk-caret" aria-hidden="true">▾</span>
      </button>
      {open && (
        <div className="pk-pop" role="menu" aria-label="Projects">
          {ids.length > 0 && <h2 className="pk-h">Open projects</h2>}
          {ids.map((id) => (
            <div key={id} className={`pk-row${id === current ? " cur" : ""}`}>
              <button type="button" role="menuitem" className="pk-go" onClick={() => switchTo(id)} aria-current={id === current ? "true" : undefined}>
                <span className="pk-mini" style={{ background: tileColor(id) }} aria-hidden="true">{id === data?.example.id ? "EX" : initials(name(id))}</span>
                <span className="pk-name"><b>{name(id)}</b><small>{id === current ? "open now" : "where you left it"}</small></span>
              </button>
              <button type="button" className="pk-x" aria-label={`Close ${name(id)}`} title="Close (the project stays)" onClick={() => close(id)}>×</button>
            </div>
          ))}
          {ids.length > 0 && <hr />}
          <button type="button" role="menuitem" className="pk-link" onClick={() => { setOpen(false); go("/"); }}>⌂ All projects</button>
          <button type="button" role="menuitem" className="pk-link pk-new" onClick={() => { setOpen(false); go("/projects/new"); }}>+ New project</button>
          {ids.length > 0 && <p className="pk-note">× closes it here. The project stays on the home page.</p>}
        </div>
      )}
    </div>
  );
}
