// Settings (D40): what applies to every project, four cards with one idea each. Nothing here is secret: the lock and
// the key view stay behind the Vault's password and code (D37).
import { type ReactNode, useState } from "react";
import { Setup } from "../agent/ConnectAgent";
import { api, useApi } from "../api/client";
import { Icons } from "../components/icons";
import { applyTheme, readTheme, type Theme } from "../components/theme";
import { CardSkeleton, ErrorBox } from "../components/ui";
import { THEMES, type GraphTheme, useMapStyle } from "../flowmap/themes";
import { Link } from "../projects/links";
import { size, type ProjectData, type SettingsData } from "./types";
import "./settings.css";

const THEME_CHOICES: { id: Theme; label: string; icon: (s?: number) => ReactNode }[] = [
  { id: "system", label: "System", icon: Icons.monitor }, { id: "light", label: "Light", icon: Icons.sun },
  { id: "dark", label: "Dark", icon: Icons.moon },
];

const REFRESH_MS = 3000;
const INSTALL_WORD = { checkout: "from source", uvx: "with uvx", pip: "with pip" };

function Look() {
  const [theme, setTheme] = useState<Theme>(readTheme);
  const [style, setStyle] = useMapStyle();
  const [error, setError] = useState<string>();
  const pickTheme = (t: Theme) => { setTheme(t); applyTheme(t); };
  const pickStyle = (s: GraphTheme) => {
    setStyle(s);
    setError(undefined);
    api.patch("/settings", { map_style: s }).catch((err: unknown) => {   // this browser keeps it; say the rest didn't
      setError(`Kept in this browser only: ${err instanceof Error ? err.message : "couldn't save it"}`);
    });
  };
  return (
    <section className="card st-card" aria-labelledby="st-look">
      <h2 id="st-look">{Icons.sun(18)} Look</h2>
      <div className="st-row">
        <span className="st-k" id="st-theme">Theme</span>
        <div className="st-seg" role="group" aria-labelledby="st-theme">
          {THEME_CHOICES.map((c) => (
            <button key={c.id} type="button" aria-pressed={theme === c.id} onClick={() => pickTheme(c.id)}>
              {c.icon(15)} {c.label}
            </button>
          ))}
        </div>
      </div>
      <label className="st-row">
        <span className="st-k">Maps open in</span>
        <select value={style} onChange={(e) => pickStyle(e.target.value as GraphTheme)}>
          {THEMES.map((t) => <option key={t.id} value={t.id}>{t.name} · {t.note}</option>)}
        </select>
      </label>
      {error && <p className="key-err" role="alert">{error}</p>}
    </section>
  );
}

function Vault({ data }: { data: SettingsData }) {
  const lock = { none: "Not set", pending: "Set-up not finished", on: "Set" }[data.vault.lock];
  return (
    <section className="card st-card" aria-labelledby="st-vault">
      <h2 id="st-vault">{Icons.lock(18)} Keys &amp; Vault</h2>
      <dl className="st-facts">
        <div><dt>Lock</dt><dd className={data.vault.lock === "on" ? "ok" : "warn"}>{data.vault.lock === "on" ? Icons.check(14) : null} {lock}</dd></div>
        <div><dt>Keys kept in</dt><dd>{data.vault.store === "keychain" ? "your keychain" : "an encrypted file"}</dd></div>
      </dl>
      <Link className="btn" to="/vault">{data.vault.lock === "on" ? "Open the Vault" : "Set the lock"} {Icons.arrow(15)}</Link>
      <p className="st-note">No key is shown here. Seeing one needs your password and the code on your phone.</p>
    </section>
  );
}

function ProjectRow({ p, onChanged }: { p: ProjectData; onChanged: () => void }) {
  const [asking, setAsking] = useState<"checks" | "confirmed">();
  const [error, setError] = useState<string>();
  const go = async (what: "checks" | "confirmed") => {
    setError(undefined);
    try { await api.del(`/projects/${encodeURIComponent(p.id)}/${what}`); setAsking(undefined); onChanged(); }
    catch (err) { setError(err instanceof Error ? err.message : "Couldn't change it"); }
  };
  return (
    <li className="st-proj">
      <span className="st-pname"><b>{p.name}</b><small>{size(p.size_bytes)} · {p.checks} {p.checks === 1 ? "check" : "checks"} · {p.confirmed.length} {p.confirmed.length === 1 ? "server" : "servers"} allowed</small></span>
      {asking ? (
        <span className="st-ask" role="group" aria-label="Are you sure?">
          <span>{asking === "checks" ? `Clear ${p.checks} checks?` : `Take back ${p.confirmed.length} yes?`}</span>
          <button type="button" className="btn sm danger" onClick={() => void go(asking)}>Yes</button>
          <button type="button" className="btn sm" onClick={() => setAsking(undefined)}>No</button>
        </span>
      ) : (
        <span className="st-btns">
          <button type="button" className="btn sm" disabled={p.confirmed.length === 0} onClick={() => setAsking("confirmed")}
            title={p.confirmed.join("\n")}>Take back yeses</button>
          <button type="button" className="btn sm" disabled={p.checks === 0} onClick={() => setAsking("checks")}>Clear check history</button>
        </span>
      )}
      {error && <span className="key-err" role="alert">{error}</span>}
    </li>
  );
}

interface Update { current: string; latest: string | null; newer: boolean; error?: string }

function Data({ data, onChanged }: { data: SettingsData; onChanged: () => void }) {
  const [update, setUpdate] = useState<Update>();
  const [checking, setChecking] = useState(false);
  const check = async () => {
    setChecking(true);
    try { setUpdate(await api.post<Update>("/settings/update-check")); }
    catch (err) { setUpdate({ current: data.version, latest: null, newer: false, error: err instanceof Error ? err.message : "Couldn't check" }); }
    finally { setChecking(false); }
  };
  return (
    <section className="card st-card st-wide" aria-labelledby="st-data">
      <h2 id="st-data">{Icons.file(18)} Data &amp; checks</h2>
      <p className="st-where"><code>{data.home}</code> · {data.projects.length} {data.projects.length === 1 ? "project" : "projects"} · {size(data.total_bytes)}</p>
      {data.projects.length > 0 && (
        <ul className="st-projs">{data.projects.map((p) => <ProjectRow key={p.id} p={p} onChanged={onChanged} />)}</ul>
      )}
      <div className="st-version">
        <span>FlowForge <b>{data.version}</b> · installed {INSTALL_WORD[data.install]}</span>
        <button type="button" className="btn sm" onClick={() => void check()} disabled={checking}>
          {Icons.refresh(14)} {checking ? "Checking…" : "Check for updates"}
        </button>
        <span role="status" className={`st-update${update?.newer ? " new" : ""}`}>
          {update && (update.error ?? (update.newer ? `${update.latest} is out` : "You have the newest version"))}
        </span>
      </div>
      <p className="st-note">Check for updates asks pypi.org once, only when you press it. Nothing else here goes online.</p>
    </section>
  );
}

export function SettingsPage() {
  const loaded = useApi<SettingsData>("/settings", REFRESH_MS);   // re-read: your agent's first call shows by itself
  const head = (
    <div className="page-head"><div className="titles"><h1>Settings</h1>
      <p className="lede">For every project.</p></div></div>
  );
  if (loaded.error && !loaded.data) return <div className="st-page">{head}<ErrorBox error={loaded.error} what="your settings" /></div>;
  if (!loaded.data) return <div className="st-page" aria-busy="true">{head}<CardSkeleton lines={6} /></div>;
  const data = loaded.data;
  return (
    <div className="st-page">{head}
      <div className="st-grid">
        <div className="st-agent">
          <Setup c={{ agents: data.agent.agents, last_call: data.agent.last_call }} title="Your agent · paired once, for every project" />
        </div>
        <Look />
        <Vault data={data} />
        <Data data={data} onChanged={loaded.reload} />
      </div>
    </div>
  );
}
