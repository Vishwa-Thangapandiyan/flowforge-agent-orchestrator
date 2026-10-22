import { useEffect, useRef, useState, type ReactNode } from "react";
import type { Tone } from "./status";

export function Chip({ tone, children, dot = false, pulse = false }: { tone: Tone; children: ReactNode; dot?: boolean; pulse?: boolean }) {
  return (
    <span className={`chip tone-${tone}`}>
      {dot && <span className={`dot${pulse ? " heartbeat" : ""}`} aria-hidden="true" />}
      {children}
    </span>
  );
}

export function prefersReducedMotion(): boolean {
  return typeof window !== "undefined" && !!window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
}

/** Counts up to `value` once when first shown; shows the final value at once under reduced motion. */
export function CountUp({ value, format, durationMs = 900 }: { value: number; format: (n: number) => string; durationMs?: number }) {
  const [shown, setShown] = useState(() => (prefersReducedMotion() ? value : 0));
  const from = useRef(0);
  useEffect(() => {
    if (prefersReducedMotion()) {
      setShown(value);
      return;
    }
    const start = performance.now();
    const origin = from.current;
    let frame = requestAnimationFrame(function step(now) {
      const p = Math.min(1, (now - start) / durationMs);
      const eased = 1 - Math.pow(1 - p, 3);
      setShown(origin + (value - origin) * eased);
      if (p < 1) frame = requestAnimationFrame(step);
      else from.current = value;
    });
    return () => cancelAnimationFrame(frame);
  }, [value, durationMs]);
  return <>{format(shown)}</>;
}

export function Stat({ value, label, tone, children }: { value: ReactNode; label: ReactNode; tone?: Tone; children?: ReactNode }) {
  return (
    <div className={`stat${tone ? ` tone-${tone}` : ""}`}>
      <div className="value" style={tone ? { color: `var(--${tone})` } : undefined}>{value}</div>
      <div className="label">{label}</div>
      {children}
    </div>
  );
}

export function Skeleton({ height = 14, width = "100%", count = 1 }: { height?: number; width?: number | string; count?: number }) {
  return (
    <span aria-hidden="true" style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      {Array.from({ length: count }, (_, i) => (
        <span key={i} className="skeleton" style={{ height, width: typeof width === "number" ? width : width }} />
      ))}
    </span>
  );
}

export function CardSkeleton({ lines = 4 }: { lines?: number }) {
  return (
    <section className="card" aria-busy="true" aria-label="Loading">
      <Skeleton height={20} width="40%" />
      <Skeleton count={lines} />
    </section>
  );
}

export function EmptyState({
  tone = "slate", icon, title, children, action,
}: { tone?: Tone; icon: ReactNode; title: ReactNode; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className="empty">
      <span className="art" style={{ background: `var(--${tone}-bg)`, color: `var(--${tone})` }} aria-hidden="true">{icon}</span>
      <h2>{title}</h2>
      {children && <p>{children}</p>}
      {action}
    </div>
  );
}

export function ErrorBox({ error, what }: { error: Error; what: string }) {
  return (
    <div className="error-box" role="alert">
      <b>Couldn't load {what}.</b> {error.message}
    </div>
  );
}
