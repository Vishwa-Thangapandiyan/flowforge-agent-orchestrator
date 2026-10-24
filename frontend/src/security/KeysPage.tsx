// The Keys page (D36, D37, docs/design/issues-keys): each key the code reads and the one thing that fixes it, with
// nothing to copy. The values never come back to this page.
import { Link } from "react-router-dom";
import { Icons } from "../components/icons";
import { EmptyState, ErrorBox } from "../components/ui";
import { useCounts } from "./counts";
import { KeyList, type KeyStatus } from "./Keys";
import { useCopy } from "./Security";
import "./security.css";

export function KeysPage() {
  const counts = useCounts();
  const data = counts.keysData;
  const [said, copy] = useCopy();
  const n = (...s: KeyStatus[]) => (data?.keys ?? []).filter((k) => s.includes(k.status)).length;
  const head = (
    <div className="page-head">
      <div className="titles">
        <h1>Keys</h1>
        <p className="lede">Paste each key once. Your coding agent only ever sees its name.</p>
      </div>
      {data && data.keys.length > 0 && (
        <span className="is-chips">
          {n("missing", "unreadable") > 0 && <span className="chip lv-medium">{n("missing", "unreadable")} missing</span>}
          {n("env_file") > 0 && <span className="chip grey">{n("env_file")} in .env</span>}
          {n("saved") > 0 && <span className="chip ok">{n("saved")} saved</span>}
        </span>
      )}
    </div>
  );
  if (counts.keysError && !data) return <div className="sec-page">{head}<ErrorBox error={counts.keysError} what="the keys" /></div>;
  if (!data) return <div className="sec-page" aria-busy="true">{head}</div>;
  if (data.keys.length === 0) {
    return (
      <div className="sec-page">{head}
        <EmptyState tone="teal" icon={Icons.key(28)} title={data.repo ? "Your code reads no keys" : "No folder mapped yet"}
          action={data.repo ? undefined : <Link className="btn primary" to="/">Scan a folder</Link>}>
          {data.repo ? "Keys show here when the code reads one from its environment." : "Keys come from the scan of a folder."}
        </EmptyState>
      </div>
    );
  }
  const run = `${data.run ?? "flowforge run --"} <how you start your app>`;
  return (
    <div className="sec-page">{head}
      <div className="key-page"><KeyList keys={data.keys} onSaved={counts.reload} /></div>
      <p className="key-run">
        {Icons.play(16)} Your app gets them: <code>{run}</code>
        <button type="button" className="btn sm" onClick={() => copy(run)}>{Icons.copy(14)} Copy</button>
        <span className="key-hint">no .env needed</span>
        <span aria-live="polite">{said}</span>
      </p>
    </div>
  );
}
