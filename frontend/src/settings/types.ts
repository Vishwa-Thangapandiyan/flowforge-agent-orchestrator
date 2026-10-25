// What GET /settings answers (D40): settings for every project. Nothing in it is secret.
import type { AgentSetup, Call } from "../agent/ConnectAgent";
import type { GraphTheme } from "../flowmap/themes";

export interface ProjectData {
  id: string;
  name: string;
  path: string;
  size_bytes: number;
  confirmed: string[];
  checks: number;
}

export interface SettingsData {
  welcome_done: boolean;
  approve_runs: boolean;
  map_style: GraphTheme | null;
  version: string;
  install: "checkout" | "desktop" | "uvx" | "pip";
  home: string;
  total_bytes: number;
  projects: ProjectData[];
  agent: { connected: boolean; last_call: Call | null; command: string[]; agents: Record<string, AgentSetup> };
  vault: { lock: "none" | "pending" | "on"; store: "keychain" | "file" };
}

export function size(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}
