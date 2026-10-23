// The ⋯ menu (D33): everything that isn't one of the header's three controls, one click away.
import { useEffect, useRef, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { Icons } from "../components/icons";

export type MenuItem =
  | { kind: "head"; label: string }
  | { kind: "action"; label: string; icon?: ReactNode; onClick: () => void; disabled?: boolean }
  | { kind: "link"; label: string; icon?: ReactNode; to: string }
  | { kind: "toggle"; label: string; on: boolean; onClick: () => void }
  | { kind: "radio"; label: string; note?: string; on: boolean; onClick: () => void; swatch?: string };

export function MoreMenu({ items, label = "More", button }: { items: MenuItem[]; label?: string; button?: ReactNode }) {
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const away = (e: MouseEvent) => { if (box.current && !box.current.contains(e.target as Node)) setOpen(false); };
    document.addEventListener("mousedown", away);
    return () => document.removeEventListener("mousedown", away);
  }, [open]);
  const run = (fn: () => void) => () => { setOpen(false); fn(); };
  return (
    <div className="mm" ref={box} onKeyDown={(e) => e.key === "Escape" && setOpen(false)}>
      <button type="button" className="btn mm-btn" aria-haspopup="menu" aria-expanded={open} onClick={() => setOpen((v) => !v)}>
        {button ?? label} <span className="mm-caret" aria-hidden="true">{Icons.chevron(14)}</span>
      </button>
      {open && (
        <div className="mm-menu" role="menu" aria-label={label}>
          {items.map((it, i) => {
            if (it.kind === "head") return <span key={i} className="mm-head" role="presentation">{it.label}</span>;
            if (it.kind === "link") {
              return <Link key={i} role="menuitem" className="mm-item" to={it.to} onClick={() => setOpen(false)}>{it.icon}{it.label}</Link>;
            }
            if (it.kind === "action") {
              return <button key={i} type="button" role="menuitem" className="mm-item" disabled={it.disabled} onClick={run(it.onClick)}>
                {it.icon}{it.label}</button>;
            }
            if (it.kind === "toggle") {
              return <button key={i} type="button" role="menuitemcheckbox" aria-checked={it.on} className="mm-item"
                onClick={() => it.onClick()}><span className="mm-check">{it.on ? Icons.check(14) : null}</span>{it.label}</button>;
            }
            return <button key={i} type="button" role="menuitemradio" aria-checked={it.on} className="mm-item"
              onClick={() => it.onClick()}>
              {it.swatch ? <i className={`fm-swatch ${it.swatch}`} aria-hidden="true" /> : <span className="mm-check">{it.on ? Icons.check(14) : null}</span>}
              <span>{it.label}{it.note && <small>{it.note}</small>}</span>
            </button>;
          })}
        </div>
      )}
    </div>
  );
}
