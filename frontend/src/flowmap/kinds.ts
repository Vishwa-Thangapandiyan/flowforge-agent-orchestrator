// What a flow's blocks are (D21, D25), in one place: the call kinds and their words, the blocks reached through a
// server, a call's name in the code's own words, and when each call could start.
import type { FlowNode, FlowView, NodeKind } from "../api/types";

export const CALL_KINDS = new Set<NodeKind>(["llm", "api", "mcp", "local"]);

/** A call kind in words: "Open-Meteo · API". */
export const SERVICE_WORD: Record<string, string> = { llm: "LLM", api: "API", mcp: "MCP server", local: "local program" };

/** A block reached through another server (D21's via, "through fetch"): it makes no call of its own. */
export const isThrough = (n: FlowNode): boolean => n.what?.startsWith("through ") ?? false;

/** What a call does, in the code's own words ("Today's weather"); a block reached through a server, or one with no
 * words, keeps its service's name. */
export const actionName = (n: FlowNode): string =>
  n.what && !isThrough(n) ? n.what.charAt(0).toUpperCase() + n.what.slice(1) : n.title;

/** Each call's earliest start: when every block it waits for is done (weights from the map). */
export function earliest(flow: FlowView): Record<string, number> {
  const into: Record<string, string[]> = {};
  for (const e of flow.edges) (into[e.target] ||= []).push(e.source);
  const weight = Object.fromEntries(flow.nodes.map((n) => [n.id, n.estimate_ms ?? 0]));
  const start: Record<string, number> = {};
  const at = (id: string, seen = new Set<string>()): number => {
    if (id in start) return start[id];
    if (seen.has(id)) return 0;
    seen.add(id);
    start[id] = Math.max(0, ...(into[id] ?? []).map((p) => at(p, seen) + weight[p]));
    return start[id];
  };
  for (const n of flow.nodes) at(n.id);
  return start;
}
