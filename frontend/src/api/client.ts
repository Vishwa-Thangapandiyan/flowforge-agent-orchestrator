import { useCallback, useEffect, useRef, useState } from "react";

/** Raised for any non-2xx answer; `message` is the API's plain-words `detail` when there is one. */
export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

// The open project (D39): a page asks for "/flow"; the request goes to "/p/<id>/flow". Set by the shell from the
// address before any page renders. "/projects…" is the home page's own and is never prefixed.
let projectBase = "";

export function setProject(id: string | null | undefined): void {
  projectBase = id ? `/p/${encodeURIComponent(id)}` : "";
}

export function projectPath(path: string): string {
  if (!projectBase || !path.startsWith("/") || path.startsWith("/p/") || path === "/projects" || path.startsWith("/projects/")) return path;
  return projectBase + path;
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  path = projectPath(path);
  const headers = new Headers(init.headers);
  headers.set("Accept", "application/json"); // HTML would get the app, not the API (D15)
  if (init.body && !(init.body instanceof FormData)) headers.set("Content-Type", "application/json");
  const res = await fetch(path, { ...init, headers });
  if (!res.ok) {
    let detail = res.statusText || `HTTP ${res.status}`;
    try {
      const body = await res.json();
      if (typeof body?.detail === "string") detail = body.detail;
    } catch {
      /* not JSON */
    }
    throw new ApiError(res.status, detail);
  }
  return (res.status === 204 ? undefined : await res.json()) as T;
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: "POST", body: body instanceof FormData ? body : JSON.stringify(body ?? {}) }),
  put: <T>(path: string, body: unknown) => request<T>(path, { method: "PUT", body: JSON.stringify(body) }),
  patch: <T>(path: string, body: unknown) => request<T>(path, { method: "PATCH", body: JSON.stringify(body) }),
  del: (path: string) => request<void>(path, { method: "DELETE" }),
};

export interface Loadable<T> {
  data: T | undefined;
  error: ApiError | Error | undefined;
  loading: boolean;
  reload: () => void;
}

/** Fetch `path` (and re-fetch every `refreshMs` while mounted). `null` skips the request. */
export function useApi<T>(path: string | null, refreshMs?: number): Loadable<T> {
  const url = path === null ? null : projectPath(path);   // another project's same page is another request
  const [data, setData] = useState<T>();
  const [error, setError] = useState<Error>();
  const [loading, setLoading] = useState(path !== null);
  const [tick, setTick] = useState(0);
  const reload = useCallback(() => setTick((t) => t + 1), []);
  const first = useRef(true);

  useEffect(() => {
    if (url === null) return;
    let cancelled = false;
    if (first.current) setLoading(true);
    api
      .get<T>(url)
      .then((d) => !cancelled && (setData(d), setError(undefined)))
      .catch((e) => !cancelled && setError(e))
      .finally(() => {
        if (!cancelled) {
          setLoading(false);
          first.current = false;
        }
      });
    return () => {
      cancelled = true;
    };
  }, [url, tick]);

  useEffect(() => {
    if (!refreshMs || url === null) return;
    const id = window.setInterval(reload, refreshMs);
    return () => window.clearInterval(id);
  }, [refreshMs, url, reload]);

  return { data, error, loading, reload };
}
