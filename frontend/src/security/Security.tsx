// Security on the map (D31, D33): a ⚠ chip in the map's header opens a short list of what to fix: level, title,
// where, a prompt for your coding agent, and the block on the map. No key value is ever shown, so nothing here needs
// protecting.
import { useEffect, useRef, useState } from "react";
import { Icons } from "../components/icons";
import "./security.css";

export type Level = "high" | "medium" | "low";

export interface Finding {
  id: string;
  kind: string;
  level: Level;
  title: string;
  ref: string;
  line: number;
  dep_id: string | null;
  first_line: number | null;
  excerpt: string[];
  fix: string;
  prompt: string;
}

export interface SecurityResponse {
  repo: string | null;
  scanned: boolean;
  summary: Partial<Record<Level, number>>;
  findings: Finding[];
}

export const LEVELS: Level[] = ["high", "medium", "low"];

/** The worst level among a dependency's findings, for the map's badge. */
export function worst(findings: Finding[]): Level | undefined {
  return LEVELS.find((l) => findings.some((f) => f.level === l));
}

export function useCopy(): [string | undefined, (text: string) => void] {
  const [said, setSaid] = useState<string>();
  const copy = (text: string) => {
    navigator.clipboard.writeText(text).then(() => setSaid("Copied"), () => setSaid("Couldn't copy"));
    window.setTimeout(() => setSaid(undefined), 2500);
  };
  return [said, copy];
}

/** "⚠ 3 to fix": hidden when there is nothing to fix. */
export function SecurityChip({ findings, onShow }: { findings: Finding[]; onShow: (depId: string) => void }) {
  const [open, setOpen] = useState(false);
  const [said, copy] = useCopy();
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const away = (e: MouseEvent) => { if (box.current && !box.current.contains(e.target as Node)) setOpen(false); };
    document.addEventListener("mousedown", away);
    return () => document.removeEventListener("mousedown", away);
  }, [open]);
  if (findings.length === 0) return null;
  const top = worst(findings) ?? "medium";
  return (
    <div className="sec-chip-wrap" ref={box} onKeyDown={(e) => e.key === "Escape" && setOpen(false)}>
      <button type="button" className={`sec-chip lv-${top}`} aria-expanded={open} aria-haspopup="dialog"
        onClick={() => setOpen((v) => !v)}>
        {Icons.shield(16)} {findings.length} to fix
      </button>
      {open && (
        <div className="sec-pop" role="dialog" aria-label="To fix">
          <ul>
            {findings.map((f) => (
              <li key={f.id}>
                <i className={`sec-dot lv-${f.level}`} aria-label={f.level} />
                <span className="sec-what"><b>{f.title}</b><code>{f.ref}</code></span>
                <span className="sec-btns">
                  <button type="button" className="btn sm" onClick={() => copy(f.prompt)} title={f.fix}>
                    {Icons.copy(14)} Copy fix
                  </button>
                  {f.dep_id && (
                    <button type="button" className="btn sm" onClick={() => { setOpen(false); onShow(f.dep_id!); }}>Show</button>
                  )}
                </span>
              </li>
            ))}
          </ul>
          <p className="sec-note">Values are never shown. Catches known key formats, not everything.<span aria-live="polite">{said && ` · ${said}`}</span></p>
        </div>
      )}
    </div>
  );
}
