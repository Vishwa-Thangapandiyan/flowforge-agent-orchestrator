// The "Add an app" form as plain data, and what it saves. A key is never part of it: the
// form asks for the *name* of the environment variable that holds the key (D16).
import type { Connector, ConnectorType, Preset } from "../api/types";

export interface Form {
  type: ConnectorType;
  id: string;
  name: string;
  role: string;
  provider: "openai_compatible" | "anthropic";
  baseUrl: string;
  model: string;
  command: string; // mcp: the program; local: program + fixed arguments
  args: string; // mcp arguments
  cwd: string;
  authHeader: string;
  authScheme: "bearer" | "basic" | "raw";
  keyVar: string;
  mode: "" | "test" | "live";
  rpm: string;
  color: string;
  logo: "letters" | "upload" | "none";
  letters: string;
  slot: string;
}

export const COLORS = ["#E4572E", "#F2A900", "#2E9E5B", "#0B7A70", "#2F6FD6", "#635BFF", "#C2398D", "#3A4756"];

export const TYPES: { id: ConnectorType; label: string; desc: string; needsKey: boolean }[] = [
  { id: "llm", label: "LLM", desc: "OpenAI-style APIs, Claude, Ollama on your own machine", needsKey: true },
  { id: "mcp", label: "MCP server", desc: "Any server. Its tools appear on their own.", needsKey: false },
  { id: "http", label: "HTTP API", desc: "Razorpay, Stripe, any REST API", needsKey: true },
  { id: "local", label: "Local command", desc: "Scripts, Sirius, models on your computer", needsKey: false },
];

export const EMPTY: Form = {
  type: "mcp", id: "", name: "", role: "", provider: "openai_compatible", baseUrl: "", model: "", command: "", args: "",
  cwd: "", authHeader: "Authorization", authScheme: "bearer", keyVar: "", mode: "", rpm: "", color: COLORS[0],
  logo: "letters", letters: "", slot: "",
};

// case-insensitive: the key-name field upper-cases what's typed, and a key must still be caught
const KEY_SHAPES = [/sk_(live|test)_/i, /rk_(live|test)_/i, /rzp_(live|test)_/i, /\bAIza[0-9A-Za-z_-]{10,}/i, /nvapi-/i, /sk-ant-/i,
  /\bsk-[A-Za-z0-9]{16,}/i,
  /eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\./, /-----BEGIN [A-Z ]*PRIVATE KEY-----/];
export const ENV_NAME = /^[A-Z_][A-Z0-9_]*$/;

/** True for anything shaped like a key, so it's refused before it can be shown or sent. */
export function looksLikeKey(text: string): boolean {
  return KEY_SHAPES.some((re) => re.test(text));
}

export function slug(name: string): string {
  const s = name.toLowerCase().normalize("NFKD").replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 40);
  return /^[a-z]/.test(s) ? s : s ? `app-${s}` : "";
}

export function initials(name: string): string {
  const words = name.trim().split(/\s+/).filter(Boolean);
  if (words.length >= 2) return (words[0][0] + words[1][0]).toUpperCase();
  return (words[0] ?? "").slice(0, 2).replace(/^./, (c) => c.toUpperCase());
}

/** Split a command line into argv, keeping "quoted parts" together. No shell is ever involved. */
export function splitArgs(line: string): string[] {
  return [...line.matchAll(/"([^"]*)"|'([^']*)'|(\S+)/g)].map((m) => m[1] ?? m[2] ?? m[3]);
}

export function problems(f: Form): Record<string, string> {
  const out: Record<string, string> = {};
  if (!f.name.trim()) out.name = "Give it a name.";
  const id = f.id || slug(f.name);
  if (f.name.trim() && !/^[A-Za-z][A-Za-z0-9_-]{0,63}$/.test(id)) out.id = "Use letters, numbers, - or _, starting with a letter.";
  if (["llm", "mcp", "http", "local", "mock"].includes(id)) out.id = `"${id}" is reserved. Pick another short name.`;
  if (f.keyVar && looksLikeKey(f.keyVar)) {
    out.keyVar = "That looks like a key itself. Put the key in your .env file and type only its name here, like GEMINI_API_KEY.";
  } else if (f.keyVar && !ENV_NAME.test(f.keyVar)) {
    out.keyVar = "Use the variable's name: capital letters, numbers and _, like GEMINI_API_KEY.";
  }
  for (const [field, value] of Object.entries(f)) {
    if (field !== "keyVar" && typeof value === "string" && looksLikeKey(value)) {
      out[field] = "That looks like a key. Keys go in your .env file, never in this form.";
    }
  }
  if (f.type === "llm") {
    if (!f.model.trim()) out.model = "Which model should it use?";
    if (f.provider === "openai_compatible" && !f.baseUrl.trim()) out.baseUrl = "Where is the API? For example https://api.example.com/v1";
  }
  if (f.type === "mcp" && !f.command.trim()) out.command = "Which program starts the server? For example npx or uvx";
  if (f.type === "local") {
    if (!f.command.trim()) out.command = "Which program should it run?";
    if (!f.cwd.trim()) out.cwd = "Which folder should it run in?";
  }
  if (f.rpm && !(Number(f.rpm) > 0)) out.rpm = "A number of calls a minute, or leave it empty for no limit.";
  if (f.logo === "letters" && f.letters.length > 2) out.letters = "Two letters at most.";
  return out;
}

/** What "Add to project" saves: the connector JSON, with a secret *reference* only. */
export function toConnector(f: Form, uploadedLogo?: { file: string } | null): Record<string, unknown> {
  const safe = (v: string) => (looksLikeKey(v) ? "" : v.trim());
  const id = safe(f.id) || slug(f.name);
  const keyRef = f.keyVar && ENV_NAME.test(f.keyVar) && !looksLikeKey(f.keyVar) ? `env:${f.keyVar}` : null;
  let connection: Record<string, unknown>;
  if (f.type === "llm") {
    connection = { provider: f.provider, model: safe(f.model), ...(f.provider === "openai_compatible" || f.baseUrl ? { base_url: safe(f.baseUrl) } : {}) };
  } else if (f.type === "mcp") {
    connection = { command: safe(f.command), args: splitArgs(safe(f.args)),
      ...(keyRef && f.keyVar ? { env_refs: { [f.keyVar]: keyRef } } : {}) };
  } else if (f.type === "http") {
    connection = { base_url: safe(f.baseUrl) || null, auth_header: keyRef ? safe(f.authHeader) || "Authorization" : null,
      auth_scheme: keyRef ? f.authScheme : null };
  } else {
    connection = { command: splitArgs(safe(f.command)), cwd: safe(f.cwd),
      ...(keyRef && f.keyVar ? { env_refs: { [f.keyVar]: keyRef } } : {}) };
  }
  const logo = f.logo === "upload" && uploadedLogo ? { type: "upload", file: uploadedLogo.file }
    : f.logo === "letters" ? { type: "letters", text: (safe(f.letters) || initials(f.name)).slice(0, 2) } : { type: "none" };
  const out: Record<string, unknown> = {
    id, type: f.type, name: safe(f.name), role: safe(f.role),
    style: { color: f.color, logo }, connection,
  };
  if (keyRef && (f.type === "llm" || f.type === "http")) out.secret_ref = keyRef;
  if (f.mode) out.mode = f.mode;
  if (f.slot.trim()) out.slot = safe(f.slot);
  if (Number(f.rpm) > 0) out.rate_limit_rpm = Number(f.rpm);
  return out;
}

/** Fill the form from a saved connector (Edit) or a preset (Add from a preset). */
export function fromConnector(c: Partial<Connector> | Preset, fallbackColor = COLORS[0]): Form {
  const conn = (c.connection ?? {}) as Record<string, unknown>;
  const refs = (conn.env_refs ?? {}) as Record<string, string>;
  const keyRef = c.secret_ref ?? Object.values(refs)[0] ?? null;
  const logo = c.style?.logo;
  return {
    ...EMPTY,
    type: c.type ?? "mcp",
    id: c.id ?? "",
    name: c.name ?? "",
    role: c.role ?? "",
    provider: (conn.provider as Form["provider"]) ?? "openai_compatible",
    baseUrl: String(conn.base_url ?? ""),
    model: String(conn.model ?? ""),
    command: Array.isArray(conn.command) ? (conn.command as string[]).join(" ") : String(conn.command ?? ""),
    args: Array.isArray(conn.args) ? (conn.args as string[]).join(" ") : "",
    cwd: String(conn.cwd ?? ""),
    authHeader: String(conn.auth_header ?? "Authorization"),
    authScheme: (conn.auth_scheme as Form["authScheme"]) ?? "bearer",
    keyVar: keyRef ? keyRef.replace(/^(env|vault):/, "") : "",
    mode: c.mode ?? "",
    rpm: c.rate_limit_rpm ? String(c.rate_limit_rpm) : "",
    color: c.style?.color ?? fallbackColor,
    logo: logo?.type ?? "letters",
    letters: logo?.type === "letters" ? logo.text : "",
    slot: c.slot ?? "",
  };
}
