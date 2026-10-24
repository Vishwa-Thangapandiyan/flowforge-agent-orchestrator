// The locked key view (D37, docs/design/issues-keys steps 2–5): the only place a key's value shows. First a lock is
// made (a password, then the phone scans a QR and its code turns it on); after that, the password and the phone's
// code open it for five minutes. Values come one at a time and hide again after 30 s; nothing is kept in the browser.
import { type FormEvent, useEffect, useRef, useState } from "react";
import { api, useApi } from "../api/client";
import { Icons } from "../components/icons";

interface LockState {
  state: "none" | "pending" | "on";
  open: boolean;
  seconds_left: number;
  reset_at: string | null;
}

interface Hidden {
  where: "code" | "saved" | "env";
  name: string;
  ref: string | null;
}

const SHOW_S = 30;
const WHERE: Record<Hidden["where"], string> = { code: "in code", saved: "saved", env: ".env" };

function message(err: unknown): string {
  return err instanceof Error ? err.message : "That didn't work";
}

function clock(s: number): string {
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

/** Step 3: pick a password, scan the QR, type the code. The password stays in this form only until the code is in. */
function SetUp({ onDone, onCancel }: { onDone: () => void; onCancel: () => void }) {
  const [password, setPassword] = useState("");
  const [again, setAgain] = useState("");
  const [qr, setQr] = useState<{ uri: string; qr: string }>();
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();
  const [manual, setManual] = useState(false);
  const start = async (e: FormEvent) => {
    e.preventDefault();
    if (password !== again) { setError("The two passwords differ."); return; }
    setBusy(true);
    setError(undefined);
    try {
      setQr(await api.post<{ uri: string; qr: string }>("/lock/setup", { password }));
    } catch (err) {
      setError(message(err));
    } finally {
      setBusy(false);
    }
  };
  const turnOn = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(undefined);
    try {
      await api.post("/lock/confirm", { password, code });
      setPassword(""); setAgain(""); setCode(""); setQr(undefined);
      onDone();
    } catch (err) {
      setCode("");
      setError(message(err));
    } finally {
      setBusy(false);
    }
  };
  const secret = qr ? new URL(qr.uri).searchParams.get("secret") ?? "" : "";
  return (
    <div className="kv-setup">
      <div className="kv-head">{Icons.lock(16)} <b>Set up the key view</b></div>
      <ol className="kv-steps">
        <li>
          <b>Pick a password</b>
          <form className="kv-fields two" onSubmit={start}>
            <input type="password" autoComplete="new-password" aria-label="Password" placeholder="Password (8+ characters)"
              value={password} disabled={!!qr} onChange={(e) => setPassword(e.target.value)} />
            <input type="password" autoComplete="new-password" aria-label="Password again" placeholder="The same again"
              value={again} disabled={!!qr} onChange={(e) => setAgain(e.target.value)} />
            {!qr && <button className="btn sm primary" type="submit" disabled={busy || password.length < 8}>Next</button>}
          </form>
        </li>
        <li className={qr ? "" : "kv-later"}>
          <b>Scan the QR</b> with Google Authenticator, Authy or 1Password
          {qr && (
            <div className="kv-qr">
              <img src={qr.qr} width={168} height={168} alt="QR code for your authenticator app" />
              <button type="button" className="btn sm quiet" onClick={() => setManual((v) => !v)}>Can't scan?</button>
              {manual && <code className="kv-secret" aria-label="Setup key">{secret}</code>}
            </div>
          )}
        </li>
        <li className={qr ? "" : "kv-later"}>
          <b>Type the code it shows</b>
          {qr && (
            <form className="kv-fields" onSubmit={turnOn}>
              <input inputMode="numeric" autoComplete="one-time-code" aria-label="Code from your phone" placeholder="6 digits"
                className="kv-code" maxLength={6} value={code} onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))} />
              <button className="btn sm primary" type="submit" disabled={busy || code.length !== 6}>Turn on</button>
            </form>
          )}
        </li>
      </ol>
      {error && <p className="key-err" role="alert">{error}</p>}
      <p className="kv-note">Your phone's code is locked by your password. Without both, nothing on this computer can open the view.</p>
      <button type="button" className="btn sm quiet" onClick={onCancel}>Cancel</button>
    </div>
  );
}

/** Step 4: password + the 6 digits on the phone. Both fields empty again whatever the answer. */
function Unlock({ onDone }: { onDone: () => void }) {
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    const sent = { password, code };
    setPassword(""); setCode("");
    setBusy(true);
    setError(undefined);
    try {
      await api.post("/lock/open", sent);
      onDone();
    } catch (err) {
      setError(message(err));
    } finally {
      setBusy(false);
    }
  };
  return (
    <form className="kv-fields three" onSubmit={submit}>
      <input type="password" autoComplete="current-password" aria-label="Password" placeholder="Password"
        value={password} onChange={(e) => setPassword(e.target.value)} />
      <input inputMode="numeric" autoComplete="one-time-code" aria-label="Code from your phone" placeholder="Code from your phone"
        className="kv-code" maxLength={6} value={code} onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))} />
      <button className="btn sm primary" type="submit" disabled={busy || !password || code.length !== 6}>Unlock</button>
      {error && <p className="key-err" role="alert">{error}</p>}
    </form>
  );
}

/** Step 5: one value at a time, hidden again after 30 s. */
function Values({ secondsLeft, onClosed }: { secondsLeft: number; onClosed: () => void }) {
  const list = useApi<{ items: Hidden[] }>("/keys/hidden");
  const [shown, setShown] = useState<{ key: string; value: string; left: number }>();
  const [left, setLeft] = useState(secondsLeft);
  const [error, setError] = useState<string>();
  useEffect(() => {
    const tick = window.setInterval(() => {
      setLeft((s) => Math.max(0, s - 1));
      setShown((v) => (v && v.left > 1 ? { ...v, left: v.left - 1 } : undefined));
    }, 1000);
    return () => window.clearInterval(tick);
  }, []);
  const ended = useRef(false);
  useEffect(() => {
    if (left === 0 && !ended.current) { ended.current = true; onClosed(); }   // once, when the session runs out
  }, [left, onClosed]);
  const show = async (h: Hidden) => {
    setError(undefined);
    try {
      const got = await api.post<{ value: string }>("/keys/reveal", h);
      setShown({ key: `${h.where}:${h.name}:${h.ref}`, value: got.value, left: SHOW_S });
    } catch (err) {
      setError(message(err));
    }
  };
  const close = async () => {
    setShown(undefined);
    await api.post("/lock/close").catch(() => {});
    onClosed();
  };
  return (
    <>
      <div className="kv-head">{Icons.lock(16)} <b>Key values</b>
        <span className="kv-timer" aria-live="off">locks in {clock(left)}</span>
        <button type="button" className="btn sm" onClick={() => void close()}>Lock now</button>
      </div>
      <ul className="kv-values">
        {list.data?.items.map((h) => {
          const key = `${h.where}:${h.name}:${h.ref}`;
          const open = shown?.key === key;
          return (
            <li key={key}>
              <span className="kv-name">{h.name}</span>
              <span className={`kv-where w-${h.where}`}>{WHERE[h.where]}{h.where === "code" && h.ref ? ` · ${h.ref}` : ""}</span>
              {open ? <code className="kv-shown">{shown.value}</code> : <span className="kv-mask" aria-hidden="true">••••••••••••</span>}
              <button type="button" className="btn sm" onClick={() => (open ? setShown(undefined) : void show(h))}>
                {open ? `Hide · ${shown.left} s` : "Show"}
              </button>
            </li>
          );
        })}
      </ul>
      {list.data && list.data.items.length === 0 && <p className="kv-note">No keys to show.</p>}
      {error && <p className="key-err" role="alert">{error}</p>}
      <p className="kv-note">One at a time, hidden again after 30 s. Never stored, never logged, never sent to your agent.</p>
    </>
  );
}

export function KeyView() {
  const lock = useApi<LockState>("/lock");
  const [step, setStep] = useState<"idle" | "setup" | "unlock">("idle");
  const reload = lock.reload;
  const state = lock.data;
  if (!state) return null;
  const banner = state.reset_at && (
    <p className="kv-banner" role="alert">⚠ Key view was reset at {new Date(state.reset_at).toLocaleString()}. If that wasn't you, replace your keys.</p>
  );
  let body;
  if (state.open) {
    body = <Values secondsLeft={state.seconds_left} onClosed={() => { setStep("idle"); reload(); }} />;
  } else if (step === "setup") {
    body = <SetUp onDone={() => { setStep("unlock"); reload(); }} onCancel={() => setStep("idle")} />;
  } else if (step === "unlock" && state.state === "on") {
    body = (
      <>
        <div className="kv-head">{Icons.lock(16)} <b>Open your key values</b></div>
        <Unlock onDone={() => { setStep("idle"); reload(); }} />
        <p className="kv-note">Opens for 5 minutes. Your coding agent can't do this: it has no phone.</p>
      </>
    );
  } else {
    body = (
      <div className="kv-head">{Icons.lock(16)} <b>See your key values</b>
        <button type="button" className="btn sm agent" onClick={() => setStep(state.state === "on" ? "unlock" : "setup")}>
          {state.state === "on" ? "Open" : state.state === "pending" ? "Finish setting up" : "Set up"} {Icons.arrow(14)}
        </button>
        <p className="kv-note">{state.state === "on" ? "Needs your password and the code from your phone." : "Needs a password and an authenticator app on your phone."}</p>
      </div>
    );
  }
  return <section className="kv" aria-label="Key values">{banner}{body}</section>;
}
