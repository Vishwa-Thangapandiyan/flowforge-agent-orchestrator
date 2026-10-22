import { useState } from "react";

export type View = "table" | "text" | "image" | "json";
type Record_ = Record<string, unknown>;

const isObj = (v: unknown): v is Record_ => typeof v === "object" && v !== null && !Array.isArray(v);

function rowsOf(output: unknown): Record_[] | null {
  const candidates = [output, isObj(output) && output.rows, isObj(output) && output.body,
    isObj(output) && isObj(output.body) && (output.body as Record_).data,
    isObj(output) && isObj(output.structured) && (output.structured as Record_).rows];
  for (const c of candidates) {
    if (Array.isArray(c) && c.length > 0 && c.every(isObj)) return c as Record_[];
  }
  return null;
}

function textOf(output: unknown): string | null {
  if (typeof output === "string") return output;
  if (!isObj(output)) return null;
  for (const key of ["text", "stdout", "content", "body"]) {
    if (typeof output[key] === "string" && output[key]) return output[key] as string;
  }
  return null;
}

function imagesOf(output: unknown): { src: string; alt: string }[] {
  if (!isObj(output) || !Array.isArray(output.blocks)) return [];
  return (output.blocks as Record_[])
    .filter((b) => b.kind === "image" && typeof b.data_b64 === "string" && typeof b.mime === "string")
    .map((b, i) => ({ src: `data:${b.mime};base64,${b.data_b64}`, alt: `Image ${i + 1} from this step` }));
}

/** The viewers that fit this output, best first (CLAUDE.md §7.4). JSON always fits. */
export function viewsFor(output: unknown): View[] {
  const views: View[] = [];
  if (rowsOf(output)) views.push("table");
  if (imagesOf(output).length) views.push("image");
  if (textOf(output) !== null) views.push("text");
  views.push("json");
  return views;
}

function Table({ rows }: { rows: Record_[] }) {
  const columns = [...new Set(rows.flatMap((r) => Object.keys(r)))].slice(0, 8);
  return (
    <div className="table-wrap">
      <table className="data">
        <thead><tr>{columns.map((c) => <th key={c} scope="col">{c}</th>)}</tr></thead>
        <tbody>
          {rows.slice(0, 200).map((r, i) => (
            <tr key={i}>
              {columns.map((c) => {
                const v = r[c];
                const tone = v === "failed" ? "var(--coral)" : v === "captured" || v === "succeeded" ? "var(--teal)" : undefined;
                return <td key={c} style={tone ? { color: tone, fontWeight: 600 } : undefined}>{typeof v === "object" ? JSON.stringify(v) : String(v ?? "")}</td>;
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function OutputViewer({ output, title }: { output: unknown; title: string }) {
  const views = viewsFor(output);
  const [picked, setPicked] = useState<View | null>(null);
  const view = picked && views.includes(picked) ? picked : views[0];
  const empty = output === undefined || output === null;

  return (
    <section className="card slide-in" aria-label={`Output of ${title}`}>
      <div className="card-head" style={{ alignItems: "center" }}>
        <span className="eyebrow">Output · {title}</span>
        {!empty && (
          <div role="tablist" aria-label="How to show this output" style={{ display: "flex", gap: 6 }}>
            {views.map((v) => (
              <button key={v} type="button" role="tab" aria-selected={v === view} className="filter"
                style={{ minHeight: 34 }} onClick={() => setPicked(v)}>
                {{ table: "Table", text: "Text", image: "Image", json: "JSON" }[v]}
              </button>
            ))}
          </div>
        )}
      </div>
      {empty ? (
        <p className="card-note">No output yet. It appears here as soon as this step finishes.</p>
      ) : view === "table" ? (
        <Table rows={rowsOf(output)!} />
      ) : view === "image" ? (
        <div style={{ display: "flex", flexWrap: "wrap", gap: 12 }}>
          {imagesOf(output).map((img) => <img key={img.alt} src={img.src} alt={img.alt} style={{ maxWidth: "100%", borderRadius: 10 }} />)}
        </div>
      ) : view === "text" ? (
        <pre className="code" style={{ whiteSpace: "pre-wrap" }}>{textOf(output)}</pre>
      ) : (
        <pre className="code">{JSON.stringify(output, null, 2)}</pre>
      )}
      <span className="card-note">The viewer matches the output: table, text, image or JSON. Keys are shown as [REDACTED].</span>
    </section>
  );
}
