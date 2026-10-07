// Brand marks for preset integrations: CC0 SVGs from the simple-icons package, used only to
// identify the integration (nominative use, D15). Anything else gets a monogram tile.
import { siClaude, siGooglegemini, siNvidia, siOllama, siRazorpay, siStripe } from "simple-icons";
import type { Connector } from "../api/types";

export interface Mark {
  title: string;
  path: string;
  /** tile background, from the design tokens where the design names one */
  tile: string;
}

const MARKS: Record<string, Mark> = {
  razorpay: { title: siRazorpay.title, path: siRazorpay.path, tile: "#3395FF" },
  stripe: { title: siStripe.title, path: siStripe.path, tile: "#635BFF" },
  gemini: { title: siGooglegemini.title, path: siGooglegemini.path, tile: "#4285F4" },
  nim: { title: siNvidia.title, path: siNvidia.path, tile: "#76B900" },
  claude: { title: siClaude.title, path: siClaude.path, tile: "#D97757" },
  ollama: { title: siOllama.title, path: siOllama.path, tile: "#1F2328" },
};

type BrandSource = Pick<Connector, "id" | "type"> & { connection?: Record<string, unknown> };

/** The preset brand this connector is, by id, provider or API address; undefined for custom apps. */
export function brandOf(c: BrandSource): string | undefined {
  if (MARKS[c.id]) return c.id;
  const conn = c.connection ?? {};
  const url = String(conn.base_url ?? "").toLowerCase();
  if (c.type === "llm" && conn.provider === "anthropic") return "claude";
  if (url.includes("nvidia.com")) return "nim";
  if (url.includes("googleapis.com")) return "gemini";
  if (url.includes(":11434")) return "ollama";
  if (url.includes("razorpay.com")) return "razorpay";
  if (url.includes("stripe.com")) return "stripe";
  return undefined;
}

export function markFor(c: BrandSource): Mark | undefined {
  const brand = brandOf(c);
  return brand ? MARKS[brand] : undefined;
}

const TYPE_COLOURS: Record<string, string> = { llm: "#6B46C1", mcp: "#2E9E5B", http: "#2F6FD6", local: "#3A4756" };

export function tileColour(c: BrandSource & { style?: Connector["style"] }): string {
  return c.style?.color ?? markFor(c)?.tile ?? TYPE_COLOURS[c.type] ?? "#3A4756";
}

/** Dark or white ink for text on `hex`: whichever has the higher WCAG contrast. */
export function inkOn(hex: string): string {
  const n = parseInt(hex.replace("#", "").slice(0, 6), 16);
  if (Number.isNaN(n)) return "#FFFFFF";
  const channel = (c: number) => {
    const v = c / 255;
    return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4;
  };
  const lum = 0.2126 * channel((n >> 16) & 255) + 0.7152 * channel((n >> 8) & 255) + 0.0722 * channel(n & 255);
  const DARK = 0.0122; // relative luminance of #0F1D26
  const vsWhite = 1.05 / (lum + 0.05);
  const vsDark = (lum + 0.05) / (DARK + 0.05);
  return vsDark > vsWhite ? "#0F1D26" : "#FFFFFF";
}

export function monogram(name: string): string {
  const words = name.trim().split(/\s+/).filter(Boolean);
  if (words.length >= 2) return (words[0][0] + words[1][0]).toUpperCase();
  const w = words[0] ?? "?";
  return (w[0].toUpperCase() + (w[1] ?? "")).slice(0, 2);
}
