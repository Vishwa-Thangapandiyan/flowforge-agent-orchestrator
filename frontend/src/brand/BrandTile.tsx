import type { Connector } from "../api/types";
import { inkOn, markFor, monogram, tileColour } from "./marks";

type TileSource = Pick<Connector, "id" | "type" | "name"> &
  Partial<Pick<Connector, "style" | "connection" | "logo_url">>;

/** The square app tile: uploaded logo, brand mark, or a colour + monogram (D15). */
export function BrandTile({ c, size = 40 }: { c: TileSource; size?: number }) {
  const colour = tileColour(c);
  const ink = inkOn(colour);
  const radius = Math.round(size * 0.26);
  const box = {
    width: size, height: size, flex: `0 0 ${size}px`, borderRadius: radius, background: colour, color: ink,
    display: "grid", placeItems: "center", overflow: "hidden", position: "relative" as const,
    boxShadow: "inset 0 1px 0 rgb(255 255 255 / 25%), 0 2px 6px -2px rgb(15 29 38 / 35%)",
  };
  if (c.logo_url) {
    return (
      <span style={{ ...box, background: "var(--surface)" }} aria-hidden="true">
        <img src={c.logo_url} alt="" width={size} height={size} style={{ objectFit: "cover", width: "100%", height: "100%" }} />
      </span>
    );
  }
  const logo = c.style?.logo;
  const mark = markFor(c); // a preset brand shows its mark even when letters were saved
  if (mark && logo?.type !== "none") {
    const inner = Math.round(size * 0.56);
    return (
      <span style={box} aria-hidden="true" data-brand={mark.title}>
        <svg viewBox="0 0 24 24" width={inner} height={inner} fill={ink} role="img">
          <path d={mark.path} />
        </svg>
      </span>
    );
  }
  const text = logo?.type === "letters" ? logo.text : logo?.type === "none" ? "" : monogram(c.name);
  return (
    <span style={{ ...box, font: `500 ${Math.round(size * 0.36)}px/1 var(--mono)` }} aria-hidden="true">
      {text}
    </span>
  );
}
