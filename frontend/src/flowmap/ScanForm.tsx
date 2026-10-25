// Map a folder (D21, D22): the form, or, in example mode, how to map your own.
import { type FormEvent, useState } from "react";
import { api, ApiError } from "../api/client";
import { useCounts } from "../security/counts";

/** Name a folder to map. It is read, never run, and nothing is sent (D20). With a map of `current` already, a
 * different folder replaces it, after you confirm (D22, D23). */
export function ScanForm({ onDone, current }: { onDone: () => void; current?: string }) {
  const counts = useCounts();
  const [path, setPath] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();
  const [confirming, setConfirming] = useState(false);
  const scan = async (replace: boolean) => {
    setBusy(true);
    setError(undefined);
    try {
      await api.post("/scan", replace ? { path: path.trim(), replace: true } : { path: path.trim() });
      counts.reload();   // a new folder: its issues and keys (D37; Codex review)
      onDone();
    } catch (err) {
      if (current && err instanceof ApiError && err.status === 409) setConfirming(true);
      else setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };
  const submit = (e: FormEvent) => {
    e.preventDefault();
    void scan(false);
  };
  return (
    <form className="scan-form" onSubmit={submit}>
      <label className="field">
        <span>Folder to scan</span>
        <input value={path} onChange={(e) => { setPath(e.target.value); setConfirming(false); }}
          placeholder="/home/you/my-app" className="mono" autoComplete="off" spellCheck={false} />
      </label>
      {confirming ? (
        <div className="notice" role="alert">
          <p style={{ margin: "0 0 10px" }}>A different folder: {current}'s map and its versions are deleted.</p>
          <button className="btn warn" type="button" onClick={() => void scan(true)} disabled={busy}>
            {busy ? "Scanning…" : "Replace the map"}
          </button>
        </div>
      ) : (
        <button className="btn primary" type="submit" disabled={busy || !path.trim()}>{busy ? "Scanning…" : "Scan this folder"}</button>
      )}
      {error && <div className="notice" role="alert">{error}</div>}
      <small>Read on this machine only. Nothing in it runs, and nothing is sent.</small>
    </form>
  );
}

/** Example data never mixes with yours (D16), so example mode says how to map your own folder instead. */
export function ScanHint() {
  return (
    <div className="scan-form">
      <span>This is example data. To map your own folder, stop FlowForge and run:</span>
      <code className="mono">uv run flowforge --repo /home/you/my-app</code>
      <small>Read on this machine only. Nothing in it runs, and nothing is sent.</small>
    </div>
  );
}
