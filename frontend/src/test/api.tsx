// Test helpers: a mocked API (fetch) and rendering a route inside the real router + shell.
import { render } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { vi } from "vitest";
import { routes } from "../routes";

export type Routes = Record<string, unknown | ((init?: RequestInit) => unknown)>;

export function mockApi(routes: Routes) {
  const calls: { url: string; init?: RequestInit }[] = [];
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    // a project's request ("/p/test/flow") matches the mock written for its page ("/flow") (D39)
    const url = (typeof input === "string" ? input : input.toString()).replace(/^\/p\/[^/]+(?=\/|$)/, "") || "/";
    calls.push({ url, init });
    const path = url.split("?")[0];
    const key = Object.keys(routes).find((k) => k === url || k === path);
    if (key === undefined) return new Response(JSON.stringify({ detail: `no mock for ${url}` }), { status: 404 });
    const value = routes[key];
    const body = typeof value === "function" ? (value as (i?: RequestInit) => unknown)(init) : value;
    if (body instanceof Response) return body;
    return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
  });
  vi.stubGlobal("fetch", fetchMock);
  return calls;
}

/** A page of a project (D39): renderAt("/keys") opens project "test"'s Keys page, renderAt("/") its map. */
export function renderAt(path: string) {
  const inside = path.startsWith("/p/") || path === "/projects" || path.startsWith("/projects/");
  const at = inside ? path : `/p/test${path === "/" ? "" : path.startsWith("/?") ? path.slice(1) : path}`;
  const router = createMemoryRouter(routes, { initialEntries: [at] });
  return render(<RouterProvider router={router} />);
}

/** The home page: every project (D39). */
export function renderHome() {
  const router = createMemoryRouter(routes, { initialEntries: ["/"] });
  return render(<RouterProvider router={router} />);
}

export const META = { project: "Baby-care shop", example: true, version: "0.1.0" };
