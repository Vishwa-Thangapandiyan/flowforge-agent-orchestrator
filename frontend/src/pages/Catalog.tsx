// The connector catalog (D17): many apps, honest Live / Demo only badges, and a mock test run for each.
// Only apps your code calls go on the map; the rest wait here as "connected, not in your code".
import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, useApi } from "../api/client";
import type { Catalog as CatalogData, CatalogItem, MockTest } from "../api/types";
import { BrandTile } from "../brand/BrandTile";
import { monogram } from "../brand/marks";
import { Icons } from "../components/icons";
import { CardSkeleton, ErrorBox, prefersReducedMotion } from "../components/ui";
import "./catalog.css";

const PRESETS = new Set(["nim", "gemini", "claude", "ollama", "razorpay", "stripe", "fetch"]);
const ORDER = ["llm", "pay", "dev", "data", "media", "custom"];

function addLink(item: CatalogItem): string {
  if (PRESETS.has(item.id)) return `/connectors/new?preset=${item.id}`;
  if (item.id.startsWith("custom_")) return `/connectors/new?type=${item.type}`;
  return `/connectors/new?type=${item.type}&name=${encodeURIComponent(item.name)}`;
}

function Tile({ item, size = 40 }: { item: CatalogItem; size?: number }) {
  const style = item.color ? { color: item.color, logo: { type: "letters" as const, text: monogram(item.name) } } : undefined;
  return <BrandTile c={{ id: item.id, type: item.type, name: item.name, style }} size={size} />;
}

function Badge({ live }: { live: boolean }) {
  return <span className={`cat-badge ${live ? "live" : "demo"}`}><i />{live ? "Live" : "Demo only"}</span>;
}

function Card({ item, onTest }: { item: CatalogItem; onTest: (i: CatalogItem) => void }) {
  return (
    <article className="cat-card">
      <div className="cat-head">
        <Tile item={item} />
        <span className="cat-name"><b>{item.name}</b><small>{item.kind}</small></span>
        <Badge live={item.live} />
      </div>
      <p>{item.description}</p>
      <span className="cat-meta">{item.meta}</span>
      <div className="cat-actions">
        <button className="btn small" type="button" onClick={() => onTest(item)}>{Icons.play(16)} Test run</button>
        {item.status === "none" ? (
          <Link className="btn small primary cat-add" to={addLink(item)}>Add</Link>
        ) : (
          <Link className={`cat-state ${item.status === "on_map" ? "" : "idle"}`} to={`/connectors/${item.id}`}>
            <i />{item.status === "on_map" ? "On the map" : "Connected · not in code"}
          </Link>
        )}
      </div>
    </article>
  );
}

function Drawer({ item, onClose }: { item: CatalogItem; onClose: () => void }) {
  const navigate = useNavigate();
  const [test, setTest] = useState<MockTest>();
  const [error, setError] = useState<string>();
  const [phase, setPhase] = useState(0);
  const closeRef = useRef<HTMLButtonElement>(null);
  const [round, setRound] = useState(0);

  useEffect(() => {
    let cancelled = false;
    const timers: number[] = [];
    setPhase(0);
    setTest(undefined);
    api.post<MockTest>(`/catalog/${encodeURIComponent(item.id)}/test`)
      .then((t) => {
        if (cancelled) return;
        setTest(t);
        if (prefersReducedMotion()) setPhase(3);
        else [450, 950, 1450].forEach((ms, i) => timers.push(window.setTimeout(() => setPhase(i + 1), ms)));
      })
      .catch((e) => !cancelled && setError(e instanceof Error ? e.message : String(e)));
    return () => { cancelled = true; timers.forEach(window.clearTimeout); };
  }, [item.id, round]);
  useEffect(() => { closeRef.current?.focus(); }, []);

  return (
    <>
      <div className="cat-scrim" onClick={onClose} aria-hidden="true" />
      <aside className="cat-drawer" role="dialog" aria-modal="true" aria-label={`Test run: ${item.name}`}
        onKeyDown={(e) => e.key === "Escape" && onClose()}>
        <div className="cat-dhead">
          <Tile item={item} size={44} />
          <div style={{ flex: 1, minWidth: 0 }}><Badge live={item.live} /><h2>Test run: {item.name}</h2></div>
          <button ref={closeRef} className="fm-ib" type="button" aria-label="Close test run" onClick={onClose}>{Icons.close(18)}</button>
        </div>
        {error && <div className="cat-dsec"><div className="error-box" role="alert">{error}</div></div>}
        {test && (
          <>
            <div className="cat-dsec"><div className={`cat-mode ${item.live ? "live" : "demo"}`}>{Icons.shield(18)}<span>{test.mode}</span></div></div>
            <div className="cat-dsec">
              <span className="sp-sh">What happens</span>
              <ol className="cat-steps">
                {test.steps.map((s, i) => (
                  <li key={s.title} className={phase > i ? "done" : phase === i ? "doing" : ""}>
                    <span className="d">{phase > i ? Icons.check(13) : phase === i ? Icons.refresh(13) : null}</span>
                    <span><b>{s.title}</b><code>{s.text}</code></span>
                  </li>
                ))}
              </ol>
            </div>
            {phase >= 3 && (
              <>
                <div className="cat-dsec" role="status">
                  <span className="sp-sh">Result · {test.stats}</span>
                  <pre className="code">{test.result}</pre>
                </div>
                <div className="cat-dsec">
                  <span className="sp-sh">What the Planner learns from it</span>
                  <ul className="cat-learn">{test.learns.map((l) => <li key={l}>{l}</li>)}</ul>
                </div>
                <div className="cat-dsec cat-row">
                  {item.status === "none" && <button className="btn primary" type="button" onClick={() => navigate(addLink(item))}>Add to project</button>}
                  <button className="btn" type="button" onClick={() => setRound((r) => r + 1)}>Run again</button>
                </div>
              </>
            )}
          </>
        )}
      </aside>
    </>
  );
}

export function Catalog() {
  const data = useApi<CatalogData>("/catalog");
  const [q, setQ] = useState("");
  const [cat, setCat] = useState("all");
  const [liveOnly, setLiveOnly] = useState(false);
  const [testing, setTesting] = useState<CatalogItem | null>(null);

  const all = useMemo(() => (data.data ? [...data.data.items, ...data.data.own] : []), [data.data]);
  if (data.error) return <ErrorBox error={data.error} what="the catalog" />;
  if (!data.data) return <CardSkeleton lines={6} />;
  const categories = data.data.categories;
  const query = q.trim().toLowerCase();
  const match = (i: CatalogItem) => (!liveOnly || i.live) && (cat === "all" || i.category === cat)
    && (!query || `${i.name} ${i.description} ${i.kind} ${i.meta}`.toLowerCase().includes(query));
  const hits = all.filter(match);
  const browsing = cat === "all" && !query && !liveOnly;
  const sections = browsing
    ? ORDER.map((k) => ({ key: k, title: categories[k] ?? k, items: all.filter((i) => i.category === k) }))
    : [{ key: "results", title: cat === "all" ? "Results" : categories[cat] ?? cat, items: hits }];
  const onMap = all.filter((i) => i.status === "on_map");
  const idle = all.filter((i) => i.status === "connected");
  const liveCount = all.filter((i) => i.live).length;

  return (
    <>
      <header className="page-head">
        <div className="titles">
          <span className="eyebrow">Connectors</span>
          <h1>Connect as many apps as you like</h1>
          <p className="lede">{all.length} apps. {liveCount} work for real today; every one has a test run on example data.</p>
        </div>
        <div className="actions">
          <button className="btn" type="button" onClick={() => { setCat("custom"); setQ(""); setLiveOnly(false); }}>{Icons.plus(18)} Add your own</button>
        </div>
      </header>

      <section className="cat-hero" aria-label="How the map stays honest">
        <span className="fm-spark" style={{ width: 52, height: 52 }}>{Icons.spark(26)}</span>
        <div>
          <span className="eyebrow" style={{ color: "var(--violet)" }}>How the map stays honest</span>
          <p>Only apps your code already calls go on the map. Anything else you connect waits here, off the map, until your code uses it.</p>
        </div>
        <div className="cat-strips">
          <div className="cat-strip" aria-label="On the map">
            <span className="lbl">On the map</span>
            {onMap.length ? onMap.map((i) => <Link key={i.id} className="cat-pt" to={`/connectors/${i.id}`}><Tile item={i} size={26} />{i.name}<i /></Link>)
              : <span className="cat-none">nothing yet</span>}
          </div>
          <div className="cat-strip" aria-label="Connected, not in your code">
            <span className="lbl">Connected, not in your code</span>
            {idle.length ? idle.map((i) => <Link key={i.id} className="cat-pt idle" to={`/connectors/${i.id}`}><Tile item={i} size={26} />{i.name}<i /></Link>)
              : <span className="cat-none">none</span>}
          </div>
        </div>
      </section>

      <div className="cat-controls">
        <label className="cat-search">
          {Icons.search(18)}
          <span className="visually-hidden">Search apps</span>
          <input type="search" placeholder={`Search ${all.length} apps: Stripe, Postgres, voice…`} value={q} onChange={(e) => setQ(e.target.value)} />
        </label>
        <div className="cat-chips" role="group" aria-label="Category">
          {["all", ...ORDER].map((k) => (
            <button key={k} type="button" className="filter" aria-pressed={cat === k} onClick={() => setCat(k)}>
              {k === "all" ? "All" : categories[k] ?? k}
              <span className="n">{k === "all" ? all.length : all.filter((i) => i.category === k).length}</span>
            </button>
          ))}
        </div>
        <button type="button" className="filter" aria-pressed={liveOnly} onClick={() => setLiveOnly((v) => !v)}>Live only</button>
      </div>

      {sections.map((s) => s.items.length > 0 && (
        <section key={s.key} className="cat-sec" aria-labelledby={`cat-${s.key}`}>
          <div className="cat-sech"><h2 id={`cat-${s.key}`}>{s.title}</h2><span>{s.items.length} · {s.items.filter((i) => i.live).length} live</span></div>
          <div className="cat-grid">{s.items.map((i) => <Card key={i.id} item={i} onTest={setTesting} />)}</div>
        </section>
      ))}
      {!browsing && hits.length === 0 && (
        <div className="empty"><p>Nothing matches “{q}”. Any app with an API, an MCP server or a command line can be added as your own.</p></div>
      )}
      <p className="card-note">Live means FlowForge can call it today with your own key or on your machine. Demo only means the test run uses
        example data; the real integration comes per app. Logos are Simple Icons marks used only to name the app; apps without one get letters.</p>
      {testing && <Drawer item={testing} onClose={() => setTesting(null)} />}
    </>
  );
}
