// One colour meaning everywhere: teal = success, blue = running, amber = waiting on you,
// coral = failed, violet = AI / Planner, slate = waiting / neutral.
export type Tone = "teal" | "blue" | "amber" | "coral" | "violet" | "slate";

const RUN: Record<string, [Tone, string]> = {
  running: ["blue", "running"],
  succeeded: ["teal", "succeeded"],
  failed: ["coral", "failed"],
  error: ["coral", "error"],
  stopped: ["slate", "stopped"],
  interrupted: ["slate", "interrupted"],
  waiting: ["amber", "waiting for you"],
};

const STEP: Record<string, [Tone, string]> = {
  pending: ["slate", "waiting"],
  ready: ["slate", "ready"],
  running: ["blue", "running"],
  succeeded: ["teal", "done"],
  failed: ["coral", "failed"],
  skipped: ["slate", "skipped"],
};

const HEALTH: Record<string, Tone> = { ok: "teal", failing: "coral", missing_key: "amber", idle: "slate" };

export const runTone = (status: string): [Tone, string] => RUN[status] ?? ["slate", status];
export const stepTone = (state: string): [Tone, string] => STEP[state] ?? ["slate", state];
export const healthTone = (status: string): Tone => HEALTH[status] ?? "slate";

export const TYPE_TAG: Record<string, { label: string; tone: Tone }> = {
  llm: { label: "llm", tone: "violet" },
  mcp: { label: "mcp", tone: "teal" },
  http: { label: "http", tone: "blue" },
  local: { label: "script", tone: "slate" },
  mock: { label: "demo", tone: "slate" },
  gate: { label: "gate", tone: "amber" },
};
