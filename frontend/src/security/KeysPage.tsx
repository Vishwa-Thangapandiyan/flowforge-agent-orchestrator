// The Keys page (D36–D38, docs/design/vault step 3): adding keys only. What your agent is waiting for comes first, then
// what's missing, then keys still in .env, then the saved ones, folded. Values never come back to this page: seeing
// them is the Vault's job.
import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Link } from "../projects/links";
import { AgentRuns } from "./AgentRuns";
import { Icons } from "../components/icons";
import { EmptyState, ErrorBox } from "../components/ui";
import { useCounts } from "./counts";
import { type Added, AddedNote, type KeyInfo, KeyList, KeyRow, SettingRow } from "./Keys";
import "./security.css";

function ago(at: string): string {
  const s = Math.max(0, (Date.now() - new Date(at).getTime()) / 1000);
  return s < 60 ? "just now" : s < 3600 ? `${Math.round(s / 60)} min ago` : `${Math.round(s / 3600)} h ago`;
}

export function KeysPage() {
  const counts = useCounts();
  const data = counts.keysData;
  const [params] = useSearchParams();
  const [added, setAdded] = useState<Added>();
  const focus = params.get("key");
  useEffect(() => {   // /keys?key=NAME: that key's box, ready to paste into (D38)
    if (!focus || !data) return;
    const box = document.querySelector<HTMLInputElement>(`input[aria-label="Value of ${CSS.escape(focus)}"]`);
    box?.scrollIntoView?.({ block: "center" });
    box?.focus();
  }, [focus, data]);
  const keys = data?.keys ?? [];
  const asked = keys.filter((k) => k.requested && k.status !== "saved");
  const by = (pick: (k: KeyInfo) => boolean) => keys.filter((k) => !asked.includes(k) && pick(k));
  const missing = by((k) => k.status === "missing" || k.status === "unreadable");
  const inEnv = by((k) => k.status === "env_file");
  const saved = by((k) => k.status === "saved");
  const head = (
    <div className="page-head">
      <div className="titles">
        <h1>Keys</h1>
        <p className="lede">Paste each key once. Your coding agent only ever sees a mask of it.</p>
      </div>
      {keys.length > 0 && (
        <span className="is-chips">
          {asked.length + missing.length > 0 && <span className="chip lv-medium">{asked.length + missing.length} missing</span>}
          {inEnv.length > 0 && <span className="chip grey">{inEnv.length} in .env</span>}
          {saved.length > 0 && <span className="chip ok">{saved.length} saved</span>}
        </span>
      )}
    </div>
  );
  if (counts.keysError && !data) return <div className="sec-page">{head}<ErrorBox error={counts.keysError} what="the keys" /></div>;
  if (!data) return <div className="sec-page" aria-busy="true">{head}</div>;
  if (keys.length === 0) {
    return (
      <div className="sec-page">{head}
        <EmptyState tone="teal" icon={Icons.key(28)} title={data.repo ? "Your code reads no keys" : "No folder mapped yet"}
          action={data.repo ? undefined : <Link className="btn primary" to="/">Scan a folder</Link>}>
          {data.repo ? "Keys show here when the code reads one, or when your agent asks for one." : "Keys come from the scan of a folder."}
        </EmptyState>
        <AgentRuns />
      </div>
    );
  }
  return (
    <div className="sec-page">{head}
      {added && <AddedNote added={added} onClose={() => setAdded(undefined)} />}
      {asked.length > 0 && (
        <section className="key-wait" aria-label="Your agent is waiting for">
          <h2 className="key-wait-title"><i className="sec-dot lv-high" /> Your agent is waiting for</h2>
          <ul className="key-list">
            {asked.map((k) => {
              const ask = data.requests?.find((r) => r.name === k.name);
              return (
                <KeyRow key={k.name} k={k} onSaved={counts.reload} example={data.example} onAdded={setAdded}
                  note={ask ? `${ask.why} · asked ${ago(ask.at)}` : undefined} />
              );
            })}
          </ul>
        </section>
      )}
      {(missing.length > 0 || inEnv.length > 0) && (
        <div className="key-page"><KeyList keys={[...missing, ...inEnv]} onSaved={counts.reload} example={data.example} onAdded={setAdded} /></div>
      )}
      {(data.settings ?? []).length > 0 && (
        <section className="key-settings" aria-label="Your app also needs">
          <h2 className="key-wait-title">{Icons.gear(15)} Your app also needs</h2>
          <ul className="key-list">
            {data.settings!.map((st) => (
              <SettingRow key={st.name} st={st} example={data.example} onSaved={counts.reload} onAdded={setAdded} />
            ))}
          </ul>
        </section>
      )}
      {saved.length > 0 && (
        <details className="key-saved">
          <summary>{Icons.check(15)} {saved.length} saved · {saved.map((k) => k.name).join(", ")}</summary>
          <div className="key-page"><KeyList keys={saved} onSaved={counts.reload} example={data.example} onAdded={setAdded} /></div>
        </details>
      )}
      <AgentRuns />
      <p className="key-runrow">
        {Icons.code(14)} <b>Add to code</b> puts a key where your app reads it. Your agent only ever sees a mask.
        <Link className="key-vault-link" to="/vault">{Icons.lock(14)} See your keys in the Vault</Link>
      </p>
    </div>
  );
}
