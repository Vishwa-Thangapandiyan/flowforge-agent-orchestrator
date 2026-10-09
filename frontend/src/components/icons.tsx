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
  map: (s?: number) => <Icon size={s}><rect x="3" y="3" width="7" height="7" rx="1.5" /><rect x="14" y="14" width="7" height="7" rx="1.5" /><path d="M6.5 10v2a4 4 0 0 0 4 4H14" /></Icon>,
  activity: (s?: number) => <Icon size={s}><path d="M3 12h4l3 8 4-16 3 8h4" /></Icon>,
  minus: (s?: number) => <Icon size={s}><path d="M5 12h14" /></Icon>,
  fit: (s?: number) => <Icon size={s}><path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5" /></Icon>,
  tidy: (s?: number) => <Icon size={s}><rect x="3" y="4" width="7" height="6" rx="1.5" /><rect x="14" y="4" width="7" height="6" rx="1.5" /><rect x="8.5" y="14" width="7" height="6" rx="1.5" /></Icon>,
  route: (s?: number) => <Icon size={s}><circle cx="6" cy="19" r="2.5" /><circle cx="18" cy="5" r="2.5" /><path d="M8.5 19H16a3.5 3.5 0 0 0 0-7H8a3.5 3.5 0 0 1 0-7h7.5" /></Icon>,
  file: (s?: number) => <Icon size={s}><path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z" /><path d="M14 3v6h6" /></Icon>,
  fileCode: (s?: number) => <Icon size={s}><path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z" /><path d="M14 3v6h6M10 13l-2 2 2 2M14 13l2 2-2 2" /></Icon>,
  addBox: (s?: number) => <Icon size={s}><rect x="3" y="3" width="18" height="18" rx="4" /><path d="M12 8v8M8 12h8" /></Icon>,
  search: (s?: number) => <Icon size={s}><circle cx="11" cy="11" r="7" /><path d="M20 20l-3.5-3.5" /></Icon>,
  close: (s?: number) => <Icon size={s}><path d="M6 6l12 12M18 6L6 18" /></Icon>,
  code: (s?: number) => <Icon size={s}><path d="M8 8l-4 4 4 4M16 8l4 4-4 4" /></Icon>,
  flag: (s?: number) => <Icon size={s}><path d="M5 21V4M5 4h11l-2 4 2 4H5" /></Icon>,
  question: (s?: number) => <Icon size={s}><circle cx="12" cy="12" r="9" /><path d="M9.6 9.4a2.5 2.5 0 1 1 3.4 2.4c-.6.3-1 .8-1 1.5v.5M12 17v.01" /></Icon>,
  key: (s?: number) => <Icon size={s}><circle cx="8" cy="15" r="4" /><path d="M10.8 12.2L20 3M16 7l3 3M14 9l2 2" /></Icon>,
  pencil: (s?: number) => <Icon size={s}><path d="M4 20h4L19 9l-4-4L4 16zM13.5 6.5l4 4" /></Icon>,
  chevron: (s?: number) => <Icon size={s}><path d="M6 9l6 6 6-6" /></Icon>,
};
