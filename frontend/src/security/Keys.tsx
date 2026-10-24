// Keys the coding agent never sees (D36): each key the code reads, whether FlowForge has it, and a write-only box.
// A value typed here goes to the server once and is cleared at once; nothing ever sends one back.
import { type FormEvent, useState } from "react";
import { api } from "../api/client";
import { Icons } from "../components/icons";
import { useCopy } from "./Security";

export type KeyStatus = "saved" | "unreadable" | "env_file" | "missing";

export interface KeyInfo {
  name: string;
  status: KeyStatus;
  ref: string | null;
  deps: string[];
  command: string | null;
}

export interface KeysResponse {
  repo: string | null;
  example: boolean;
  summary: Partial<Record<KeyStatus, number>>;
  keys: KeyInfo[];
}

export type KeyNeed = "missing" | "env_file";

const WORD: Record<KeyStatus, string> = { saved: "saved", unreadable: "can't read", env_file: "in .env", missing: "missing" };

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
function KeyBox({ name, onSaved, onClose }: { name: string; onSaved: () => void; onClose: () => void }) {
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
      onClose();
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
      <button className="btn sm" type="button" onClick={() => { setValue(""); onClose(); }}>Cancel</button>
      {error && <span className="key-err" role="alert">{error}</span>}
    </form>
  );
}

/** One key: name, status, where it's read, and how to fix it (copy the command, or paste it here). */
export function KeyRow({ k, example, onSaved }: { k: KeyInfo; example?: boolean; onSaved: () => void }) {
  const [adding, setAdding] = useState(false);
  const [said, copy] = useCopy();
  return (
    <li className="key-row">
      <span className={`key-ic ks-${k.status}`} aria-hidden="true">{Icons.key(14)}</span>
      <span className="key-what">
        <b>{k.name}</b>
        <span><span className={`key-st ks-${k.status}`}>{WORD[k.status]}</span>{k.ref && <code>{k.ref}</code>}</span>
      </span>
      {k.command && (
        <span className="sec-btns">
          <button type="button" className="btn sm" onClick={() => copy(k.command!)} title={k.command}>
            {Icons.copy(14)} Copy command
          </button>
          {(k.status === "missing" || k.status === "unreadable") && !example && !adding && (
            <button type="button" className="btn sm" onClick={() => setAdding(true)}>Add here</button>
          )}
        </span>
      )}
      {adding && <KeyBox name={k.name} onSaved={onSaved} onClose={() => setAdding(false)} />}
      <span className="key-said" aria-live="polite">{said}</span>
    </li>
  );
}

export function KeyList({ keys, example, onSaved }: { keys: KeyInfo[]; example?: boolean; onSaved: () => void }) {
  return (
    <ul className="key-list">
      {keys.map((k) => <KeyRow key={k.name} k={k} example={example} onSaved={onSaved} />)}
    </ul>
  );
}
