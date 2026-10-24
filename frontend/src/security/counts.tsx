// How many issues and keys need you, for the rail's counts and the map's ⚠ chip (D37). One fetch, shared; a page
// that fixes something calls reload so every count moves at once.
import { createContext, type ReactNode, useContext, useMemo } from "react";
import { useApi } from "../api/client";
import type { IssuesResponse } from "./IssuesPage";
import { type KeysResponse, needsAction } from "./Keys";

export interface Counts {
  issues: number;
  keys: number;
  issuesData?: IssuesResponse;
  keysData?: KeysResponse;
  issuesError?: Error;
  keysError?: Error;
  reload: () => void;
}

const CountsContext = createContext<Counts>({ issues: 0, keys: 0, reload: () => {} });

export function CountsProvider({ children }: { children: ReactNode }) {
  const issues = useApi<IssuesResponse>("/issues");
  const keys = useApi<KeysResponse>("/keys");
  const { reload: reloadIssues } = issues;
  const { reload: reloadKeys } = keys;
  const value = useMemo<Counts>(() => ({
    issues: (issues.data?.issues ?? []).filter((i) => i.state !== "fixed").length,
    keys: needsAction(keys.data?.keys ?? []).length,
    issuesData: issues.data,
    keysData: keys.data,
    issuesError: issues.error,
    keysError: keys.error,
    reload: () => { reloadIssues(); reloadKeys(); },
  }), [issues.data, keys.data, issues.error, keys.error, reloadIssues, reloadKeys]);
  return <CountsContext.Provider value={value}>{children}</CountsContext.Provider>;
}

export function useCounts(): Counts {
  return useContext(CountsContext);
}
