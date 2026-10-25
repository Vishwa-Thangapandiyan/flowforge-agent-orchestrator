// Keys the coding agent never sees (D36, D37): each key the code reads, whether FlowForge has it, and one button or
// box that fixes it, with no command to copy. A value typed here goes to the server once and is cleared at once;
// nothing ever sends one back.
import { type FormEvent, useState } from "react";
import { api } from "../api/client";
import { Icons } from "../components/icons";
import { useCopy } from "./Security";

export type KeyStatus = "saved" | "unreadable" | "env_file" | "missing";

/** Where a key goes in the code, for "Add to code" (D44) */
export interface KeySpot {
  name: string;
  kind: "reads" | "placeholder" | "open";
  ref: string;
  /** the file the app reads it from; null when the app reads none */
  sink: string | null;
  why_not: string | null;
  /** the line as this page saw it: a changed line is refused */
  check: string;
  where: string | null;
}

export interface KeyInfo {
  name: string;
  status: KeyStatus;
  requested?: boolean;
  ref: string | null;
  deps: string[];
  command: string | null;
  spot?: KeySpot | null;
  /** already in a file the app reads (D44) */
  in_app?: boolean;
}

export interface Added {
  name: string;
  changed: string[];
  /** Flutter: a Run config passes the defines file (else `terminal` is the one command that does) */
  run_config?: boolean;
  terminal?: string;
}

export interface KeysResponse {
  repo: string | null;
  example: boolean;
  summary: Partial<Record<KeyStatus, number>>;
  keys: KeyInfo[];
  /** keys your coding agent asked for, waiting for you (D38) */
  requests?: { name: string; why: string; at: string }[];
}

export type KeyNeed = "missing" | "env_file";

export const KEY_WORD: Record<KeyStatus, string> = { saved: "saved", unreadable: "can't read", env_file: "in .env", missing: "missing" };

/** What a block's keys need, for its 🔑 badge: missing (or saved but unreadable) beats "only in .env"; nothing when
 *  all are saved. */
export function keyNeed(keys: KeyInfo[]): KeyNeed | undefined {
  if (keys.some((k) => k.status === "missing" || k.status === "unreadable")) return "missing";
  return keys.some((k) => k.status === "env_file") ? "env_file" : undefined;
}

export function needsAction(keys: KeyInfo[]): KeyInfo[] {
  return keys.filter((k) => k.status !== "saved");
}

/** A password box for one key. With a spot the app reads from, it adds the key to the code (D44); without one it
 *  saves it in the Vault. The value lives only in this box's state until the click, then is cleared. */
function KeyBox({ name, spot, example, onDone, onCancel }: {
  name: string; spot?: KeySpot | null; example?: boolean; onDone: (added?: Added) => void; onCancel?: () => void;
}) {
  const [value, setValue] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();
  const intoCode = !!spot?.sink && !example;
  const save = async (e: FormEvent) => {
    e.preventDefault();
    const typed = value;
    setValue("");   // out of state at once, whatever the answer
    setBusy(true);
    setError(undefined);
    try {
      if (intoCode) {
        onDone(await api.post<Added>(`/keys/${encodeURIComponent(name)}/add-to-code`, { value: typed, ref: spot!.ref, check: spot!.check }));
      } else {
        await api.put(`/keys/${encodeURIComponent(name)}`, { value: typed });
        onDone();
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't save");
    } finally {
      setBusy(false);
    }
  };
  return (
    <form className="key-box" onSubmit={save}>
      <input type="password" autoComplete="off" spellCheck={false} name="flowforge-key" value={value}
        aria-label={`Value of ${name}`} placeholder="Paste the key" onChange={(e) => setValue(e.target.value)} />
      <button className="btn sm primary" type="submit" disabled={busy || !value.trim()}>
        {intoCode ? <>{Icons.code(14)} Add to code</> : <>{Icons.lock(14)} Save</>}
      </button>
      {onCancel && <button className="btn sm quiet" type="button" onClick={() => { setValue(""); onCancel(); }}>Cancel</button>}
      {!intoCode && spot?.why_not && <span className="key-hint key-why">{spot.why_not}</span>}
      {error && <span className="key-err" role="alert">{error}</span>}
    </form>
  );
}

/** One key and the one thing that fixes it (D44): paste it and it goes into the code; hide a key written in the open;
 *  put a saved key into the app; move it in from .env; or replace it. */
export function KeyRow({ k, onSaved, note, example, onAdded }: {
  k: KeyInfo; onSaved: () => void; note?: string; example?: boolean; onAdded?: (added: Added) => void;
}) {
  const [replacing, setReplacing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();
  const done = (a?: Added) => { if (a) onAdded?.(a); setReplacing(false); onSaved(); };
  const act = async (call: () => Promise<Added | unknown>, shows = false) => {
    setBusy(true);
    setError(undefined);
    try {
      const got = await call();
      done(shows ? got as Added : undefined);
    } catch (err) {
      setError(err instanceof Error ? err.message : "That didn't work");
    } finally {
      setBusy(false);
    }
  };
  const path = `/keys/${encodeURIComponent(k.name)}`;
  const spot = k.spot;
  const canWire = !!spot?.sink && !example;
  const open = spot?.kind === "open" && k.status !== "saved";
  const needsValue = !open && (k.status === "missing" || k.status === "unreadable");
  const notInApp = k.status === "saved" && canWire && !k.in_app;
  const word = open ? "open in code" : k.status === "saved" ? (k.in_app ? "✓ in your app" : "✓ saved") : KEY_WORD[k.status];
  const wire = (value?: string) => api.post<Added>(`${path}/add-to-code`, { ref: spot!.ref, check: spot!.check, ...(value ? { value } : {}) });
  return (
    <li className={`key-row ks-${open ? "missing" : k.status}`}>
      <span className={`key-ic ks-${open ? "missing" : k.status}`} aria-hidden="true">{Icons.key(16)}</span>
      <span className="key-what">
        <b>{k.name}</b>
        <span><span className={`key-st ks-${open ? "missing" : k.status}`}>{word}</span>
          {(spot?.ref ?? k.ref) && <code>{spot?.ref ?? k.ref}</code>}
          {open && <span className="key-hint">anyone with the code can read it</span>}
          {notInApp && <span className="key-hint">not in your app yet</span>}
          {k.status === "env_file" && <span className="key-hint">a coding agent can read .env</span>}
          {k.status === "unreadable" && <span className="key-hint">save it again</span>}
          {note && <span className="key-hint">{note}</span>}
        </span>
      </span>
      <span className="key-act">
        {open && canWire && (
          <button type="button" className="btn sm primary" disabled={busy} onClick={() => void act(() => wire(), true)}>
            {Icons.lock(14)} Hide it
          </button>
        )}
        {notInApp && !replacing && (
          <button type="button" className="btn sm primary" disabled={busy} onClick={() => void act(() => wire(), true)}>
            {Icons.code(14)} Add to code
          </button>
        )}
        {k.status === "env_file" && (
          <button type="button" className="btn sm primary" disabled={busy} onClick={() => void act(() => api.post(`${path}/import`))}>
            Move into FlowForge
          </button>
        )}
        {k.status === "saved" && !replacing && (
          <>
            <button type="button" className="btn sm" onClick={() => setReplacing(true)}>Replace</button>
            <button type="button" className="btn sm quiet" disabled={busy} onClick={() => void act(() => api.del(path))}>Remove</button>
          </>
        )}
      </span>
      {(needsValue || replacing) && (
        <KeyBox name={k.name} spot={spot} example={example} onDone={done}
          onCancel={replacing ? () => setReplacing(false) : undefined} />
      )}
      {error && <span className="key-err" role="alert">{error}</span>}
    </li>
  );
}

export function KeyList({ keys, onSaved, example, onAdded }: {
  keys: KeyInfo[]; onSaved: () => void; example?: boolean; onAdded?: (added: Added) => void;
}) {
  return (
    <ul className="key-list">
      {keys.map((k) => <KeyRow key={k.name} k={k} onSaved={onSaved} example={example} onAdded={onAdded} />)}
    </ul>
  );
}

/** What "Add to code" just changed, kept on the page after the key moves to the saved ones (D44). */
export function AddedNote({ added, onClose }: { added: Added; onClose: () => void }) {
  const [said, copy] = useCopy();
  const flutter = added.run_config !== undefined;
  const command = flutter && !added.run_config ? added.terminal : undefined;
  return (
    <div className="key-added" role="status">
      <p>{Icons.check(16)} <b>{added.name}</b> is in your app.
        {command ? " Start it with:" : flutter ? " Press Run as always." : " Start your app as always."}</p>
      {command && (
        <p className="key-terminal"><code>{command}</code>
          <button type="button" className="btn sm" onClick={() => copy(command)}>{Icons.copy(14)} Copy</button>
          <span aria-live="polite">{said}</span></p>
      )}
      <p className="key-changed">Changed: {added.changed.join(" · ")}</p>
      <button type="button" className="btn sm quiet key-close" onClick={onClose} aria-label="Close">×</button>
    </div>
  );
}
