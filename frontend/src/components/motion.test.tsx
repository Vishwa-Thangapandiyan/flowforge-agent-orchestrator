import { render, screen } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { CountUp, prefersReducedMotion } from "./ui";

afterEach(() => vi.unstubAllGlobals());

function reducedMotion(on: boolean) {
  vi.stubGlobal("matchMedia", (query: string) => ({
    matches: on && query.includes("prefers-reduced-motion"), media: query, onchange: null,
    addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {}, dispatchEvent: () => false,
  }));
}

test("with reduced motion, numbers appear at once instead of counting up", () => {
  reducedMotion(true);
  expect(prefersReducedMotion()).toBe(true);
  render(<CountUp value={4210} format={(n) => Math.round(n).toLocaleString("en-US")} />);
  expect(screen.getByText("4,210")).toBeInTheDocument();
});

test("without it, the count starts from zero and animates", () => {
  reducedMotion(false);
  render(<CountUp value={4210} format={(n) => Math.round(n).toLocaleString("en-US")} />);
  expect(screen.getByText("0")).toBeInTheDocument();
});
