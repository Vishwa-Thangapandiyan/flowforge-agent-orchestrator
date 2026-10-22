// The MCP Map as Mermaid (D26): the same shapes, branches and critical path, for a README or a pull request,
// where GitHub draws it. Mermaid has no lanes or time axis, so the times go in the labels.
import type { FlowView } from "../api/types";
import { type Block, layoutMap } from "./layout";

const SHAPE: Record<string, (label: string) => string> = {
  start: (t) => `((${t}))`, llm: (t) => `([${t}])`, mcp: (t) => `{{${t}}}`, api: (t) => `[${t}]`,
  local: (t) => `[/${t}/]`, decision: (t) => `{${t}}`, end: (t) => `[[${t}]]`,
};

const COLOUR: Record<string, string> = { llm: "#6B46C1", mcp: "#1E7A4A", api: "#2457C5", local: "#4A5E6A" };

// words Mermaid reads as syntax when used as an id
const RESERVED = new Set(["end", "graph", "flowchart", "subgraph", "style", "class", "classDef", "click", "linkStyle", "direction"]);

const idOf = (id: string) => {
  const clean = id.replace(/[^\w-]/g, "_");
  return RESERVED.has(clean) ? `n_${clean}` : clean;
};

const text = (s: string) => s.replace(/"/g, "#quot;").replace(/[<>]/g, (c) => (c === "<" ? "#lt;" : "#gt;"));

function label(b: Block): string {
  return `"${text(b.name)}${b.note ? `<br/>${text(b.note)}` : ""}${b.writes ? " ✎" : ""}${b.repeats ? " ↻" : ""}"`;
}

export function toMermaid(flow: FlowView, app: string): string {
  const map = layoutMap(flow);
  const files = map.files.length > 2 ? `${map.files.length} files` : map.files.join(", ");
  const lines = ["flowchart LR", `  %% MCP map of ${app}, read from ${files || "the repo"} by FlowForge (rules: docs/mcp-map.md)`];
  for (const b of map.blocks) {
    const shape = SHAPE[b.kind] ?? SHAPE.local;
    lines.push(`  ${idOf(b.id)}${shape(b.kind === "start" || b.kind === "end" ? `"${text(b.name)}"` : label(b))}`);
  }
  for (const l of map.lines) {
    const arrow = l.via ? "-.->" : l.critical ? "==>" : "-->";
    lines.push(`  ${idOf(l.from)} ${arrow}${l.when ? `|${text(l.when)}|` : ""} ${idOf(l.to)}`);
  }
  for (const [kind, colour] of Object.entries(COLOUR)) {
    const ids = map.blocks.filter((b) => b.kind === kind).map((b) => idOf(b.id));
    if (!ids.length) continue;
    lines.push(`  classDef ${kind} stroke:${colour},stroke-width:2px`, `  class ${ids.join(",")} ${kind}`);
  }
  return lines.join("\n");
}
