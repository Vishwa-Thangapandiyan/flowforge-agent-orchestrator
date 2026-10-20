// Which map a page shows (D21): the dependency map from a scan (the default) or the flow map (`?map=flow`).
import { useSearchParams } from "react-router-dom";

export type MapId = "deps" | "flow";

/** `?map=flow` picks the flow map; no parameter means the dependency map. */
export function useMapId(): MapId {
  const [params] = useSearchParams();
  return params.get("map") === "flow" ? "flow" : "deps";
}

/** The query part that names a map in URLs: empty for the default dependency map. */
export function mapQuery(map: MapId, joiner = "?"): string {
  return map === "flow" ? `${joiner}map=flow` : "";
}
