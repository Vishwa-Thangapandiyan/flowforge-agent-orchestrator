import { Link } from "react-router-dom";
import type { Connector, Health } from "../api/types";
import { BrandTile } from "../brand/BrandTile";
import { healthTone } from "./status";
import "./HubMap.css";

const TYPE_LABEL: Record<string, string> = { llm: "LLM", mcp: "MCP server", http: "HTTP API", local: "script" };

export interface HubMapProps {
  project: string;
  connectors: Connector[];
  health: Record<string, Health | undefined>;
  /** connectors used by a run that is running now: their links animate */
  active: Set<string>;
}

/** Positions on an ellipse around the hub, starting at the top, in % of the map box. */
export function layout(n: number): { x: number; y: number }[] {
  if (n === 0) return [];
  return Array.from({ length: n }, (_, i) => {
    const angle = -Math.PI / 2 + (2 * Math.PI * i) / n;
    return { x: 50 + 38 * Math.cos(angle), y: 50 + 39 * Math.sin(angle) };
  });
}

export function HubMap({ project, connectors, health, active }: HubMapProps) {
  const spots = layout(connectors.length);
  return (
    <div className="hub-wrap">
    <div className="hubmap" data-active={active.size > 0 || undefined}>
      <svg className="hub-lines" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">
        {spots.map((p, i) => {
          const on = active.has(connectors[i].id);
          return (
            <g key={connectors[i].id}>
              <line x1="50" y1="50" x2={p.x} y2={p.y} className="hub-line" vectorEffect="non-scaling-stroke" />
              {on && <line x1="50" y1="50" x2={p.x} y2={p.y} className="hub-line live flowing" vectorEffect="non-scaling-stroke" />}
            </g>
          );
        })}
      </svg>
      <div className="hub-core">
        <b>{project}</b>
        <span>your project · scheduler, keys, history</span>
      </div>
      <ul className="hub-tiles">
        {connectors.map((c, i) => {
          const h = health[c.id];
          const tone = h ? healthTone(h.status) : "slate";
          const on = active.has(c.id);
          return (
            <li key={c.id} style={{ left: `${spots[i].x}%`, top: `${spots[i].y}%` }} className={on ? "is-active" : undefined}>
              <Link to={`/connectors/${c.id}`} className="hub-tile">
                <BrandTile c={c} size={38} />
                <span className="hub-text">
                  <b>{c.name}</b>
                  <span>{[c.role || TYPE_LABEL[c.type], c.mode].filter(Boolean).join(" · ")}</span>
                </span>
                <span className={`hub-dot tone-${tone}${on ? " pulse" : ""}`} aria-hidden="true" />
                <span className="visually-hidden">, {h?.label ?? "status unknown"}</span>
              </Link>
            </li>
          );
        })}
      </ul>
    </div>
    </div>
  );
}
