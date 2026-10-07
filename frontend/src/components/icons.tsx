// Small line icons (generic shapes, drawn here; no third-party marks).
import type { ReactNode } from "react";

function Icon({ children, size = 20 }: { children: ReactNode; size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"
      strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      {children}
    </svg>
  );
}

export const Icons = {
  hub: (s?: number) => <Icon size={s}><circle cx="12" cy="12" r="3" /><circle cx="4" cy="6" r="2" /><circle cx="20" cy="6" r="2" /><circle cx="4" cy="18" r="2" /><circle cx="20" cy="18" r="2" /><path d="M6 7l4 3M18 7l-4 3M6 17l4-3M18 17l-4-3" /></Icon>,
  plug: (s?: number) => <Icon size={s}><path d="M9 2v6M15 2v6M7 8h10v4a5 5 0 0 1-10 0V8zM12 17v5" /></Icon>,
  list: (s?: number) => <Icon size={s}><path d="M9 6h11M9 12h11M9 18h11" /><circle cx="4.5" cy="6" r="1" /><circle cx="4.5" cy="12" r="1" /><circle cx="4.5" cy="18" r="1" /></Icon>,
  play: (s?: number) => <Icon size={s}><path d="M7 4.5v15l12-7.5-12-7.5z" /></Icon>,
  check: (s?: number) => <Icon size={s}><path d="M5 12.5l4.5 4.5L19 7.5" /></Icon>,
  history: (s?: number) => <Icon size={s}><path d="M3 12a9 9 0 1 0 3-6.7L3 8" /><path d="M3 3v5h5M12 7v5l3 2" /></Icon>,
  shield: (s?: number) => <Icon size={s}><path d="M12 3l8 3v6c0 4.5-3.4 8.2-8 9-4.6-.8-8-4.5-8-9V6l8-3z" /><path d="M9 12l2 2 4-4" /></Icon>,
  plus: (s?: number) => <Icon size={s}><path d="M12 5v14M5 12h14" /></Icon>,
  sun: (s?: number) => <Icon size={s}><circle cx="12" cy="12" r="4" /><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" /></Icon>,
  moon: (s?: number) => <Icon size={s}><path d="M20 14.5A8.5 8.5 0 0 1 9.5 4 8.5 8.5 0 1 0 20 14.5z" /></Icon>,
  monitor: (s?: number) => <Icon size={s}><rect x="3" y="4" width="18" height="12" rx="2" /><path d="M8 20h8M12 16v4" /></Icon>,
  menu: (s?: number) => <Icon size={s}><path d="M4 7h16M4 12h16M4 17h16" /></Icon>,
  spark: (s?: number) => <Icon size={s}><path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8L12 3z" /><path d="M19 16l.7 2 2 .7-2 .7-.7 2-.7-2-2-.7 2-.7.7-2z" /></Icon>,
  lock: (s?: number) => <Icon size={s}><rect x="5" y="11" width="14" height="10" rx="2" /><path d="M8 11V8a4 4 0 0 1 8 0v3" /></Icon>,
  stop: (s?: number) => <Icon size={s}><rect x="6" y="6" width="12" height="12" rx="2" /></Icon>,
  arrow: (s?: number) => <Icon size={s}><path d="M5 12h14M13 6l6 6-6 6" /></Icon>,
  refresh: (s?: number) => <Icon size={s}><path d="M20 11a8 8 0 1 0-2.3 5.7M20 4v7h-7" /></Icon>,
  bolt: (s?: number) => <Icon size={s}><path d="M13 2L4 14h7l-1 8 9-12h-7l1-8z" /></Icon>,
};
