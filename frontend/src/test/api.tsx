// Test helpers: a mocked API (fetch) and rendering a route inside the real router + shell.
import { render } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { vi } from "vitest";
import { routes } from "../routes";

export type Routes = Record<string, unknown | ((init?: RequestInit) => unknown)>;

export function mockApi(routes: Routes) {
  const calls: { url: string; init?: RequestInit }[] = [];
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string" ? input : input.toString();
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

export function renderAt(path: string) {
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  return render(<RouterProvider router={router} />);
}

export const META = { project: "Baby-care shop", example: true, version: "0.1.0" };
