// The Vault (D37, D38, docs/design/vault steps 4–7): the only page that shows a key's value. First time: a three-step
// set-up (password, the phone scans a QR, the first code). After that: your password, then the code on your phone,
// each on its own screen, then five minutes open with every key's health. Values come one at a time and hide again
// after 30 s; nothing is kept in the browser.
import { type FormEvent, useEffect, useRef, useState } from "react";
import { Link } from "../projects/links";
import { api, useApi } from "../api/client";
import { Icons } from "../components/icons";
import { useCounts } from "./counts";
import "./security.css";

interface LockState {
  state: "none" | "pending" | "on";
  open: boolean;
  seconds_left: number;
  reset_at: string | null;
}

interface Place { where: "saved" | "code" | "env"; ref: string | null; store: string | null }

interface VaultKey {
  name: string;
  places: Place[];
  added: string | null;
  kind: "live" | "test" | null;
  deps: { id: string; name: string }[];
  ref: string | null;
  health: string[];
}

const SHOW_S = 30;

function message(err: unknown): string {
  return err instanceof Error ? err.message : "That didn't work";
}

function clock(s: number): string {
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

function tone(word: string): string {
  if (word === "healthy") return "ok";
  if (["in code", "can't read", "missing"].includes(word)) return "bad";
  if (word === "unused") return "grey";
  return "warn";
}

function lives(k: VaultKey): string {
  const p = k.places[0];
  if (!p) return "nowhere yet";
  if (p.where === "saved") return p.store === "keychain" ? "keychain" : "encrypted file";
  return p.ref ?? (p.where === "env" ? ".env" : "code");
}

function Digits({ value, onChange, label }: { value: string; onChange: (v: string) => void; label: string }) {
  return (
    <input className="vt-digits" inputMode="numeric" autoComplete="one-time-code" aria-label={label} placeholder="000000"
      maxLength={6} value={value} onChange={(e) => onChange(e.target.value.replace(/\D/g, ""))} />
  );
}

/** Step 4, first time only: password, scan the QR, the first code. */
function SetUp({ onDone }: { onDone: () => void }) {
  const [password, setPassword] = useState("");
  const [again, setAgain] = useState("");
  const [qr, setQr] = useState<{ uri: string; qr: string }>();
  const [code, setCode] = useState("");
  const [manual, setManual] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();
  const step = qr ? (code.length === 6 ? 3 : 2) : 1;
  const start = async (e: FormEvent) => {
    e.preventDefault();
    if (password !== again) { setError("The two passwords differ."); return; }
    setBusy(true); setError(undefined);
    try { setQr(await api.post<{ uri: string; qr: string }>("/lock/setup", { password })); }
    catch (err) { setError(message(err)); }
    finally { setBusy(false); }
  };
  const turnOn = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true); setError(undefined);
    try {
      await api.post("/lock/confirm", { password, code });
      setPassword(""); setAgain(""); setCode(""); setQr(undefined);
      onDone();
    } catch (err) { setCode(""); setError(message(err)); }
    finally { setBusy(false); }
  };
  const secret = qr ? new URL(qr.uri).searchParams.get("secret") ?? "" : "";
  return (
    <section className="vt-setup" aria-label="Set up the Vault">
      <div className="vt-stepbar" aria-label={`Step ${step} of 3`}>
        <b>Step {step} of 3</b>{[1, 2, 3].map((n) => <i key={n} className={n <= step ? "on" : ""} />)}
      </div>
      <div className="vt-wiz">
        <form className={`vt-card${step === 1 ? " now" : ""}`} onSubmit={start}>
          <span className="vt-n">{qr ? Icons.check(14) : 1}</span>
          <h3>Pick a password</h3>
          <p>8+ characters. Only you know it.</p>
          <input type="password" autoComplete="new-password" aria-label="Password" placeholder="Password" value={password}
            disabled={!!qr} onChange={(e) => setPassword(e.target.value)} />
          <input type="password" autoComplete="new-password" aria-label="Password again" placeholder="The same again" value={again}
            disabled={!!qr} onChange={(e) => setAgain(e.target.value)} />
          {!qr && <button className="btn primary" type="submit" disabled={busy || password.length < 8}>Next {Icons.arrow(16)}</button>}
        </form>
        <div className={`vt-card${step === 2 ? " now" : ""}`}>
          <span className="vt-n">2</span>
          <h3>Scan with your phone</h3>
          <p>Google Authenticator, Authy or 1Password.</p>
          {qr ? (
            <>
              <img className="vt-qr" src={qr.qr} width={196} height={196} alt="QR code for your authenticator app" />
              <button type="button" className="btn sm quiet" onClick={() => setManual((v) => !v)}>Can't scan? Show the key</button>
              {manual && <code className="kv-secret" aria-label="Setup key">{secret}</code>}
            </>
          ) : <div className="vt-qr empty" aria-hidden="true">{Icons.lock(28)}</div>}
        </div>
        <form className={`vt-card${step === 3 ? " now" : ""}`} onSubmit={turnOn}>
          <span className="vt-n">3</span>
          <h3>Type the code</h3>
          <p>The 6 digits your phone shows now.</p>
          {qr && <Digits value={code} onChange={setCode} label="Code from your phone" />}
          {qr && <button className="btn primary" type="submit" disabled={busy || code.length !== 6}>Turn on</button>}
        </form>
      </div>
      {error && <p className="key-err" role="alert">{error}</p>}
      <p className="kv-note">Your phone's code is locked by your password. Without both, nothing on this computer can open the Vault.</p>
    </section>
  );
}

/** Steps 5 and 6: the password, then the code, one screen at a time. */
function Gate({ onOpen }: { onOpen: () => void }) {
  const [step, setStep] = useState<"password" | "code">("password");
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true); setError(undefined);
    try {
      if (step === "password") {
        const sent = password;
        setPassword("");
        await api.post("/lock/password", { password: sent });
        setStep("code");
      } else {
        const sent = code;
        setCode("");
        await api.post("/lock/code", { code: sent });
        onOpen();
      }
    } catch (err) {
      const text = message(err);
      if (step === "code" && /password first/i.test(text)) setStep("password");   // step 1 ran out
      setError(text);
    } finally { setBusy(false); }
  };
  const first = step === "password";
  return (
    <form className="vt-gate" onSubmit={submit} aria-label={first ? "Vault: your password" : "Vault: the code on your phone"}>
      <div className="vt-dots" aria-hidden="true"><i className="on" /><i className={first ? "" : "on"} /></div>
      <div className="vt-big" aria-hidden="true">{first ? Icons.lock(28) : Icons.key(28)}</div>
      <h2>Vault</h2>
      <p>{first ? "Step 1 of 2 · your password" : "Step 2 of 2 · the code on your phone"}</p>
      {first ? (
        <input type="password" autoComplete="current-password" aria-label="Password" placeholder="Password" autoFocus
          value={password} onChange={(e) => setPassword(e.target.value)} />
      ) : <Digits value={code} onChange={setCode} label="Code from your phone" />}
      <button className="btn primary" type="submit" disabled={busy || (first ? !password : code.length !== 6)}>
        {first ? <>Next {Icons.arrow(16)}</> : "Unlock"}
      </button>
      {error && <p className="key-err" role="alert">{error}</p>}
      {!first && <p className="kv-note">Your coding agent can't do this step: it has no phone.</p>}
    </form>
  );
}

/** Step 7: every key with its health; one value at a time for 30 s. */
function Open({ secondsLeft, onClosed }: { secondsLeft: number; onClosed: () => void }) {
  const list = useApi<{ keys: VaultKey[] }>("/vault/keys");
  const counts = useCounts();
  const [shown, setShown] = useState<{ name: string; value: string; left: number }>();
  const [left, setLeft] = useState(secondsLeft);
  const [error, setError] = useState<string>();
  const ended = useRef(false);
  useEffect(() => {
    const tick = window.setInterval(() => {
      setLeft((s) => Math.max(0, s - 1));
      setShown((v) => (v && v.left > 1 ? { ...v, left: v.left - 1 } : undefined));
    }, 1000);
    return () => window.clearInterval(tick);
  }, []);
  useEffect(() => {
    if (left === 0 && !ended.current) { ended.current = true; onClosed(); }   // once, when the session runs out
  }, [left, onClosed]);
  const act = async (call: () => Promise<unknown>) => {
    setError(undefined);
    try { await call(); list.reload(); counts.reload(); } catch (err) { setError(message(err)); }
  };
  const show = async (k: VaultKey) => {
    const place = ["saved", "env", "code"].map((w) => k.places.find((p) => p.where === w)).find(Boolean);
    if (!place) return;
    setError(undefined);
    try {
      const got = await api.post<{ value: string }>("/keys/reveal", { where: place.where, name: k.name, ref: place.ref });
      setShown({ name: k.name, value: got.value, left: SHOW_S });
    } catch (err) { setError(message(err)); }
  };
  const close = async () => {
    setShown(undefined);
    await api.post("/lock/close").catch(() => {});
    onClosed();
  };
  const keys = list.data?.keys ?? [];
  const n = (pick: (k: VaultKey) => boolean) => keys.filter(pick).length;
  return (
    <>
      <div className="page-head">
        <div className="titles"><h1>Vault</h1><p className="lede">Every key, where it lives and how it's doing.</p></div>
        <span className="is-chips">
          <span className="chip ok">{Icons.lock(13)} open</span>
          <span className="kv-timer">locks in {clock(left)}</span>
          <button type="button" className="btn sm" onClick={() => void close()}>Lock now</button>
        </span>
      </div>
      <div className="vt-sum">
        <div><b>{keys.length}</b><span>keys</span></div>
        <div><b className="ok">{n((k) => k.health[0] === "healthy")}</b><span>healthy</span></div>
        <div><b className="bad">{n((k) => k.health.includes("in code"))}</b><span>written in code</span></div>
        <div><b className="warn">{n((k) => k.health[0] !== "healthy" && !k.health.includes("in code"))}</b><span>need a look</span></div>
      </div>
      <div className="vt-table-wrap">
        <table className="vt-table">
          <thead><tr><th>Key</th><th>Health</th><th>Lives in</th><th>Used by</th><th>Kind</th><th>Saved</th><th>Value</th><th /></tr></thead>
          <tbody>
            {keys.map((k) => {
              const open = shown?.name === k.name;
              const has = k.places.length > 0;
              const saved = k.places.some((p) => p.where === "saved");
              return (
                <tr key={k.name}>
                  <td className="vt-name">{k.name}</td>
                  <td>{k.health.map((h) => <span key={h} className={`vt-h ${tone(h)}`}>{h === "healthy" ? "✓ healthy" : `⚠ ${h}`}</span>)}</td>
                  <td className="vt-mono">{lives(k)}</td>
                  <td>{k.deps.map((d) => d.name).join(", ") || "—"}</td>
                  <td>{k.kind ? <span className="vt-h grey">{k.kind}</span> : "—"}</td>
                  <td>{k.added ? new Date(k.added).toLocaleDateString() : "—"}</td>
                  <td>{open ? <code className="kv-shown">{shown.value}</code> : has ? <span className="kv-mask" aria-hidden="true">••••••••••••</span> : "—"}</td>
                  <td className="vt-acts">
                    {has && (
                      <button type="button" className="btn sm" onClick={() => (open ? setShown(undefined) : void show(k))}>
                        {open ? `Hide · ${shown.left} s` : "Show"}
                      </button>
                    )}
                    {k.health.includes("in code") && <Link className="btn sm primary" to="/issues">Fix</Link>}
                    {k.health.includes("in .env") && !saved && (
                      <button type="button" className="btn sm primary" onClick={() => void act(() => api.post(`/keys/${encodeURIComponent(k.name)}/import`))}>Move in</button>
                    )}
                    {k.health.includes("missing") && <Link className="btn sm primary" to={`/keys?key=${encodeURIComponent(k.name)}`}>Add</Link>}
                    {saved && k.health.includes("unused") && (
                      <button type="button" className="btn sm quiet" onClick={() => void act(() => api.del(`/keys/${encodeURIComponent(k.name)}`))}>Remove</button>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {error && <p className="key-err" role="alert">{error}</p>}
      <p className="kv-note">One value at a time, hidden again after 30 s. Never stored, never logged, never sent to your agent.</p>
    </>
  );
}

export function VaultPage() {
  const lock = useApi<LockState>("/lock");
  const state = lock.data;
  const reload = lock.reload;
  const banner = state?.reset_at && (
    <p className="kv-banner" role="alert">⚠ The Vault's lock was reset at {new Date(state.reset_at).toLocaleString()}. If that wasn't you, replace your keys.</p>
  );
  let body;
  if (!state) body = null;
  else if (state.open) body = <Open secondsLeft={state.seconds_left} onClosed={reload} />;
  else if (state.state === "on") body = <Gate onOpen={reload} />;
  else {
    body = (
      <>
        <div className="page-head">
          <div className="titles"><h1>Vault</h1><p className="lede">See your keys behind your password and your phone. Set it up once.</p></div>
          <span className="chip grey">set up once</span>
        </div>
        <SetUp onDone={reload} />
      </>
    );
  }
  return <div className="sec-page vt">{banner}{body}</div>;
}
