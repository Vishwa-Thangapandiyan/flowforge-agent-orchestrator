import { useState } from "react";
import type { CSSProperties } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, ApiError, useApi } from "../api/client";
import type { Activity, Connector, Health, Tool } from "../api/types";
import { BrandTile } from "../brand/BrandTile";
import { clock, seconds, when } from "../components/format";
import { Icons } from "../components/icons";
import { useMeta } from "../components/Shell";
import { TYPE_TAG, healthTone, stepTone } from "../components/status";
import { CardSkeleton, Chip, EmptyState, ErrorBox } from "../components/ui";

const TYPE_NAME: Record<string, string> = { llm: "LLM", mcp: "MCP server", http: "HTTP API", local: "Local command" };
const FIELD_NAME: Record<string, string> = {
  provider: "Provider", base_url: "Base URL", model: "Model", temperature_default: "Default temperature",
  command: "Command", args: "Arguments", cwd: "Runs in folder", env: "Settings passed in", env_refs: "Keys passed in",
  auth_header: "Auth header", auth_scheme: "Auth style", max_output_bytes: "Output cap",
};

function show(value: unknown): string {
  if (Array.isArray(value)) return value.join(" ") || "—";
  if (value && typeof value === "object") return Object.entries(value).map(([k, v]) => `${k}=${String(v)}`).join(", ") || "—";
  if (value === null || value === undefined || value === "") return "—";
  return String(value);
}

function keyText(c: Connector): { text: string; tone: string } {
  if (!c.secret) return { text: "No key needed", tone: "var(--muted)" };
  if (c.secret.status === "set") return { text: "configured ••••••", tone: "var(--teal)" };
  if (c.secret.status === "example") return { text: "example (no key)", tone: "var(--violet)" };
  return { text: "missing", tone: "var(--amber)" };
}

export function ConnectorsList() {
  const connectors = useApi<Connector[]>("/connectors", 8000);
  const health = useApi<Health[]>("/health/tools", 5000);
  const byId = Object.fromEntries((health.data ?? []).map((h) => [h.id, h]));
  return (
    <>
      <header className="page-head">
        <div className="titles">
          <span className="eyebrow">Connectors</span>
          <h1>Your apps</h1>
          <span className="lede">Everything FlowForge can call. Each one keeps its own rate limit and cache.</span>
        </div>
        <Link to="/connectors/new" className="btn primary">{Icons.plus(18)} Add app</Link>
      </header>
      {connectors.error ? <ErrorBox error={connectors.error} what="your apps" /> : !connectors.data ? <CardSkeleton lines={4} /> : (
        <ul className="grid" style={{ "--min": "260px", listStyle: "none", padding: 0, margin: 0 } as CSSProperties}>
          {connectors.data.map((c, i) => {
            const h = byId[c.id];
            const tag = TYPE_TAG[c.type];
            return (
              <li key={c.id} className={`rise rise-${Math.min(4, i + 1)}`}>
                <Link to={`/connectors/${c.id}`} className="card app-card">
                  <span style={{ display: "flex", gap: 12, alignItems: "center" }}>
                    <BrandTile c={c} size={44} />
                    <span style={{ minWidth: 0 }}>
                      <b style={{ display: "block", fontSize: 17 }}>{c.name}</b>
                      <span className="card-note">{c.role || TYPE_NAME[c.type]}</span>
                    </span>
                  </span>
                  <span style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
                    <span className={`tag tone-${tag.tone}`}>{tag.label}</span>
                    {c.mode && <span className="tag tone-amber">{c.mode} mode</span>}
                    {c.is_default && <span className="tag tone-slate">default</span>}
                    <span style={{ marginLeft: "auto", color: `var(--${h ? healthTone(h.status) : "muted"})`, fontWeight: 600, fontSize: 14 }}>
                      {h?.label ?? "…"}
                    </span>
                  </span>
                </Link>
              </li>
            );
          })}
        </ul>
      )}
    </>
  );
}

export function ConnectorPage() {
  const { id = "" } = useParams();
  const meta = useMeta();
  const navigate = useNavigate();
  const connector = useApi<Connector>(`/connectors/${encodeURIComponent(id)}`);
  const health = useApi<Health[]>("/health/tools", 5000);
  const activity = useApi<Activity[]>(`/connectors/${encodeURIComponent(id)}/activity`, 5000);
  const isMcp = connector.data?.type === "mcp";
  const tools = useApi<Tool[]>(isMcp && !meta.example ? `/connectors/${encodeURIComponent(id)}/tools` : null);
  const [test, setTest] = useState<{ ok: boolean; message: string } | null>(null);
  const [testing, setTesting] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [actionError, setActionError] = useState<string>();

  if (connector.error) {
    if (connector.error instanceof ApiError && connector.error.status === 404) {
      return <EmptyState icon={Icons.plug(30)} title="No app with that name" action={<Link to="/connectors" className="btn">See all apps</Link>} />;
    }
    return <ErrorBox error={connector.error} what="this app" />;
  }
  if (!connector.data) return <><CardSkeleton lines={2} /><CardSkeleton lines={5} /></>;

  const c = connector.data;
  const h = health.data?.find((x) => x.id === c.id);
  const key = keyText(c);
  const canTest = c.type === "mcp" || c.type === "local";
  const editable = c.managed_by === "app";

  async function runTest() {
    setTesting(true);
    try {
      setTest(await api.post<{ ok: boolean; message: string }>(`/connectors/${encodeURIComponent(c.id)}/test`));
      health.reload();
    } catch (e) {
      setTest({ ok: false, message: (e as Error).message });
    } finally {
      setTesting(false);
    }
  }

  async function remove() {
    if (!confirmDelete) {
      setConfirmDelete(true);
      return;
    }
    try {
      await api.del(`/connectors/${encodeURIComponent(c.id)}`);
      navigate("/connectors");
    } catch (e) {
      setActionError((e as Error).message);
      setConfirmDelete(false);
    }
  }

  const statusChip = !h ? null : h.status === "ok" ? (
    <Chip tone="teal" dot>Connected{c.mode ? ` · ${c.mode} mode` : ""}</Chip>
  ) : <Chip tone={healthTone(h.status)} dot>{h.label}</Chip>;
  const recentTasks = [...new Map((activity.data ?? []).map((a) => [a.step_id, a])).values()];

  return (
    <>
      <nav className="crumbs" aria-label="Breadcrumb">
        <Link to="/">{meta.project}</Link><span aria-hidden="true">›</span>
        <Link to="/connectors">Connectors</Link><span aria-hidden="true">›</span><b>{c.name}</b>
      </nav>

      <header className="card raised" style={{ flexDirection: "row", flexWrap: "wrap", alignItems: "center", gap: 16 }}>
        <BrandTile c={c} size={60} />
        <div style={{ flex: "1 1 220px", display: "flex", flexDirection: "column", gap: 2 }}>
          <h1 style={{ fontSize: 30 }}>{c.name}</h1>
          <span className="lede">{[c.role, TYPE_NAME[c.type], c.slot && `slot: ${c.slot}`].filter(Boolean).join(" · ")}</span>
        </div>
        <div className="actions">
          {statusChip}
          <button type="button" className="btn" onClick={runTest} disabled={!canTest || testing}
            title={canTest ? "Makes one harmless check" : "Testing LLM and HTTP apps arrives in Phase 3"}>
            {testing ? "Testing…" : "Test connection"}
          </button>
          <button type="button" className="btn violet" disabled title="Swapping an app arrives in Phase 5">Swap app</button>
        </div>
      </header>
      {test && (
        <div className={test.ok ? "notice" : "error-box"} role="status" style={test.ok ? { background: "var(--teal-bg)" } : undefined}>
          <b>{test.ok ? "It works. " : "It didn't work. "}</b>{test.message}
        </div>
      )}
      {!canTest && <p className="card-note">Testing {TYPE_NAME[c.type]} apps from here arrives in Phase 3; a run will tell you straight away if the key or address is wrong.</p>}
      {actionError && <div className="error-box" role="alert"><b>Couldn't do that.</b> {actionError}</div>}

      <div className="grid" style={{ "--min": "400px" } as CSSProperties}>
        <section className="card" aria-labelledby="conn-title">
          <span className="eyebrow" id="conn-title">Connection</span>
          <div className="row"><span>Type</span><b>{TYPE_NAME[c.type]}</b></div>
          {c.mode && <div className="row"><span>Mode</span><b style={{ textTransform: "capitalize" }}>{c.mode}</b></div>}
          <div className="row"><span>Key</span><b style={{ color: key.tone }}>{key.text}</b></div>
          {c.secret && <div className="row"><span>Read from</span><b className="mono" style={{ fontSize: 14 }}>{c.secret.ref}</b></div>}
          <div className="row"><span>Rate limit</span><b>{c.rate_limit_rpm ? `${c.rate_limit_rpm} calls a minute` : "none"}</b></div>
          {h?.rate && <div className="row"><span>Left this minute</span><b>{h.rate.left} of {h.rate.rpm}</b></div>}
          {c.fallback && <div className="row"><span>If it keeps failing</span><b>tries <Link to={`/connectors/${c.fallback}`}>{c.fallback}</Link></b></div>}
          <div className="row"><span>Last test call</span><b>{h?.last_test ? `${h.last_test.ok ? "OK" : "failed"}, ${when(h.last_test.at)}` : "—"}</b></div>
          <p className="card-note">
            {c.secret?.status === "missing"
              ? <>Add <code>{c.secret.ref.replace("env:", "")}=…</code> to your <code>.env</code> and restart FlowForge (see <code>api-connect.md</code>).</>
              : "Keys live in your .env file. FlowForge stores only the name and never shows the value."}
          </p>
        </section>

        <section className="card" aria-labelledby="form-title">
          <span className="eyebrow" id="form-title">The form you filled in</span>
          {Object.entries(c.connection).map(([k, v]) => (
            <div className="row" key={k}><span>{FIELD_NAME[k] ?? k}</span><b className={k === "base_url" || k === "command" || k === "cwd" ? "mono" : undefined} style={{ fontSize: 14, textAlign: "right", overflowWrap: "anywhere" }}>{show(v)}</b></div>
          ))}
          {editable ? (
            <div className="actions">
              <Link to={`/connectors/${c.id}/edit`} className="btn small">Edit this form</Link>
              {c.deletable && (
                <button type="button" className="btn small danger" onClick={remove} onBlur={() => setConfirmDelete(false)}>
                  {confirmDelete ? "Click again to remove" : "Remove app"}
                </button>
              )}
            </div>
          ) : <p className="card-note">This app comes from <code>connectors.json</code>; edit that file to change it.</p>}
        </section>
      </div>

      <section className="card" aria-labelledby="tasks-title">
        <div className="card-head">
          <span className="eyebrow" id="tasks-title">Tasks inside this box</span>
          <span className="card-note">{isMcp ? "The tools this server offers" : "What this app has done recently"}</span>
        </div>
        {isMcp && meta.example && <p className="card-note">In example mode MCP servers aren't started, so their tools aren't listed.</p>}
        {isMcp && tools.loading && <p className="card-note">Asking the server for its tools…</p>}
        {isMcp && tools.error && <p className="card-note">Couldn't reach the server: {tools.error.message}</p>}
        {(isMcp ? tools.data ?? [] : []).map((t) => (
          <div key={t.name} className="task-row">
            <span className="tag tone-teal">tool</span><b>{t.name}</b><span className="card-note">{t.description}</span>
          </div>
        ))}
        {!isMcp && recentTasks.map((a) => (
          <div key={a.step_id} className="task-row">
            <span className={`tag tone-${TYPE_TAG[c.type].tone}`}>{TYPE_TAG[c.type].label}</span>
            <b>{a.title}</b>
            <span className="card-note">{a.plan} · {seconds(a.duration_ms)}</span>
          </div>
        ))}
        {!isMcp && recentTasks.length === 0 && <p className="card-note">Nothing yet. Tasks appear here once a run uses this app.</p>}
      </section>

      <section className="card" style={{ background: "var(--violet-bg)", borderColor: "transparent" }} aria-labelledby="planner-title">
        <div className="card-head">
          <span className="eyebrow" id="planner-title" style={{ color: "var(--violet)" }}>Suggested by the Planner</span>
          <Chip tone="violet">Arrives in Phase 4</Chip>
        </div>
        <p>The Planner will read this app's tools, API and your code, and propose tasks you confirm once in Plan review. A suggestion with no real tool, route or file behind it is dropped before you see it.</p>
      </section>

      <section className="card" aria-labelledby="activity-title">
        <span className="eyebrow" id="activity-title">Recent activity</span>
        {!activity.data ? <CardSkeleton lines={3} /> : activity.data.length === 0 ? (
          <p className="card-note">No calls yet.</p>
        ) : (
          <ol className="event-log" style={{ maxHeight: "none" }}>
            {activity.data.slice(0, 12).map((a) => {
              const [tone, word] = stepTone(a.state);
              return (
                <li key={`${a.run_id}-${a.step_id}`} style={{ whiteSpace: "normal", flexWrap: "wrap" }}>
                  <span className="t">{clock(a.at)}</span>
                  <Link to={`/runs/${a.run_id}`}>{a.plan}</Link>
                  <span>· {a.title} ·</span>
                  <span style={{ color: `var(--${tone})` }}>{a.cache_hit ? "from cache" : word}</span>
                  {a.duration_ms !== null && <span className="t">{seconds(a.duration_ms)}</span>}
                  {a.error && <span style={{ color: "var(--coral)" }}>{a.error}</span>}
                </li>
              );
            })}
          </ol>
        )}
      </section>
    </>
  );
}
