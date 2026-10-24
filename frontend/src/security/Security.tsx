// Security on the map (D31, D37): the findings' types, and the ⚠ chip in the map's header that opens the Issues page.
// No key value is ever shown.
import { useState } from "react";
import { Link } from "react-router-dom";
import { Icons } from "../components/icons";
import "./security.css";

export type Level = "high" | "medium" | "low";

export interface Finding {
  id: string;
  kind: string;
  level: Level;
  title: string;
  ref: string;
  line: number;
  dep_id: string | null;
  first_line: number | null;
  excerpt: string[];
  fix: string;
  prompt: string;
}

export interface SecurityResponse {
  repo: string | null;
  scanned: boolean;
  summary: Partial<Record<Level, number>>;
  findings: Finding[];
}

export const LEVELS: Level[] = ["high", "medium", "low"];

/** The worst level among a dependency's findings, for the map's badge. */
export function worst(findings: Finding[]): Level | undefined {
  return LEVELS.find((l) => findings.some((f) => f.level === l));
}

export function useCopy(): [string | undefined, (text: string) => void] {
  const [said, setSaid] = useState<string>();
  const copy = (text: string) => {
    navigator.clipboard.writeText(text).then(() => setSaid("Copied"), () => setSaid("Couldn't copy"));
    window.setTimeout(() => setSaid(undefined), 2500);
  };
  return [said, copy];
}

/** "⚠ 3 to fix" on the map: opens the Issues page, or the Keys page when only keys need you (D37). Hidden when there
 *  is nothing to fix. */
export function SecurityChip({ issues, keys, level }: { issues: number; keys: number; level?: Level }) {
  if (issues + keys === 0) return null;
  return (
    <Link to={issues > 0 ? "/issues" : "/keys"} className={`sec-chip lv-${level ?? "medium"}`}>
      {Icons.shield(16)} {issues + keys} to fix
    </Link>
  );
}
