// Brand marks for preset and catalog integrations: CC0 SVGs from the simple-icons package, used only
// to identify the integration (nominative use, D15). Anything not in the package gets a monogram tile.
import {
  siAdyen, siAirtable, siClaude, siDeepgram, siDeepseek, siDiscord, siDocker, siElevenlabs, siFirebase, siGithub, siGitlab,
  siGmail, siGoogledrive, siGooglegemini, siGooglesheets, siHuggingface, siJira, siLinear, siMistralai, siModelcontextprotocol,
  siMongodb, siNotion, siNvidia, siOllama, siOpenrouter, siPaypal, siPerplexity, siPostgresql, siRazorpay, siRedis, siReplicate,
  siResend, siSentry, siShopify, siSquare, siStripe, siSupabase, siTelegram, siVercel, siWhatsapp,
  type SimpleIcon,
} from "simple-icons";
import type { Connector } from "../api/types";

export interface Mark {
  title: string;
  path: string;
  /** tile background, from the design tokens where the design names one */
  tile: string;
}

const m = (icon: SimpleIcon, tile?: string): Mark => ({
  title: icon.title, path: icon.path, tile: tile ?? (icon.hex === "000000" ? "#16191D" : `#${icon.hex}`),
});

/** By connector or catalog id. Tile colours follow the design tokens where the design names one. */
const MARKS: Record<string, Mark> = {
  razorpay: m(siRazorpay, "#3395FF"), stripe: m(siStripe, "#635BFF"), gemini: m(siGooglegemini, "#4285F4"),
  nim: m(siNvidia, "#76B900"), claude: m(siClaude, "#D97757"), ollama: m(siOllama, "#1F2328"),
  mistral: m(siMistralai), openrouter: m(siOpenrouter), deepseek: m(siDeepseek), perplexity: m(siPerplexity),
  huggingface: m(siHuggingface), paypal: m(siPaypal), square: m(siSquare), adyen: m(siAdyen), github: m(siGithub),
  gitlab: m(siGitlab), docker: m(siDocker), sentry: m(siSentry), vercel: m(siVercel), linear: m(siLinear), jira: m(siJira),
  postgres: m(siPostgresql), supabase: m(siSupabase), mongodb: m(siMongodb), redis: m(siRedis), notion: m(siNotion),
  gdrive: m(siGoogledrive), gmail: m(siGmail), gsheets: m(siGooglesheets), airtable: m(siAirtable), discord: m(siDiscord),
  telegram: m(siTelegram), whatsapp: m(siWhatsapp), resend: m(siResend), shopify: m(siShopify), firebase: m(siFirebase),
  elevenlabs: m(siElevenlabs), replicate: m(siReplicate), deepgram: m(siDeepgram), custom_mcp: m(siModelcontextprotocol),
};

/** Monogram tiles for catalog apps simple-icons doesn't carry (a colour, never a drawn logo). */
const MONO_TILES: Record<string, string> = {
  openai: "#10A37F", groq: "#F55036", together: "#0B5FE0", cohere: "#39594D", sirius: "#0B7A70", playwright: "#2EAD33",
  slack: "#4A154B", twilio: "#C81E34", higgsfield: "#2A2A30", stability: "#5B3FD1", runway: "#16191D", assemblyai: "#2545D3",
  inventory: "#2F6FD6",
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
  return c.style?.color ?? markFor(c)?.tile ?? MONO_TILES[c.id] ?? TYPE_COLOURS[c.type] ?? "#3A4756";
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
