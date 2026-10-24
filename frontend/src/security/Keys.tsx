// Keys the coding agent never sees (D36, D37): each key the code reads, whether FlowForge has it, and one button or
// box that fixes it, with no command to copy. A value typed here goes to the server once and is cleared at once;
// nothing ever sends one back.
import { type FormEvent, useState } from "react";
import { api } from "../api/client";
import { Icons } from "../components/icons";

export type KeyStatus = "saved" | "unreadable" | "env_file" | "missing";

export interface KeyInfo {
  name: string;
  status: KeyStatus;
  requested?: boolean;
  ref: string | null;
  deps: string[];
  command: string | null;
}

export interface KeysResponse {
  repo: string | null;
  example: boolean;
  summary: Partial<Record<KeyStatus, number>>;
  keys: KeyInfo[];
  /** `flowforge run --repo … --`, to put before the command that starts your app */
  run?: string;
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

/** A password box that saves one key. The value lives only in this box's state until Save, then is cleared. */
function KeyBox({ name, onSaved, onCancel }: { name: string; onSaved: () => void; onCancel?: () => void }) {
  const [value, setValue] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();
  const save = async (e: FormEvent) => {
    e.preventDefault();
    const typed = value;
    setValue("");   // out of state at once, whatever the answer
    setBusy(true);
    setError(undefined);
    try {
      await api.put(`/keys/${encodeURIComponent(name)}`, { value: typed });
      onSaved();
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
      <button className="btn sm primary" type="submit" disabled={busy || !value.trim()}>{Icons.lock(14)} Save</button>
      {onCancel && <button className="btn sm quiet" type="button" onClick={() => { setValue(""); onCancel(); }}>Cancel</button>}
      {error && <span className="key-err" role="alert">{error}</span>}
    </form>
  );
}

/** One key and the one thing that fixes it: paste it (missing, can't read), move it in from .env, or replace it. */
export function KeyRow({ k, onSaved, note }: { k: KeyInfo; onSaved: () => void; note?: string }) {
  const [replacing, setReplacing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();
  const act = async (call: () => Promise<unknown>) => {
    setBusy(true);
    setError(undefined);
    try {
      await call();
      onSaved();
    } catch (err) {
      setError(err instanceof Error ? err.message : "That didn't work");
    } finally {
      setBusy(false);
    }
  };
  const path = `/keys/${encodeURIComponent(k.name)}`;
  const needsValue = k.status === "missing" || k.status === "unreadable";
  return (
    <li className={`key-row ks-${k.status}`}>
      <span className={`key-ic ks-${k.status}`} aria-hidden="true">{Icons.key(16)}</span>
      <span className="key-what">
        <b>{k.name}</b>
        <span><span className={`key-st ks-${k.status}`}>{k.status === "saved" ? "✓ saved" : KEY_WORD[k.status]}</span>
          {k.ref && <code>{k.ref}</code>}
          {k.status === "env_file" && <span className="key-hint">a coding agent can read .env</span>}
          {k.status === "unreadable" && <span className="key-hint">save it again</span>}
          {note && <span className="key-hint">{note}</span>}
        </span>
      </span>
      <span className="key-act">
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
        <KeyBox name={k.name} onSaved={() => { setReplacing(false); onSaved(); }}
          onCancel={replacing ? () => setReplacing(false) : undefined} />
      )}
      {error && <span className="key-err" role="alert">{error}</span>}
    </li>
  );
}

export function KeyList({ keys, onSaved }: { keys: KeyInfo[]; onSaved: () => void }) {
  return (
    <ul className="key-list">
      {keys.map((k) => <KeyRow key={k.name} k={k} onSaved={onSaved} />)}
    </ul>
  );
}
