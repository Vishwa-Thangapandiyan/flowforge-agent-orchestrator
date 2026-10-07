/// <reference types="vitest/config" />
import react from "@vitejs/plugin-react";
import { defineConfig, type ProxyOptions } from "vite";

const API = "http://127.0.0.1:8000";
// Page routes and API paths overlap (/runs/:id, /connectors/:id). Browser navigations ask for
// HTML and get the app; fetches ask for JSON and go to the API (D15).
const api: ProxyOptions = {
  target: API,
  bypass: (req) => (req.headers.accept?.includes("text/html") ? "/index.html" : undefined),
};

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    strictPort: true,
    proxy: Object.fromEntries(
      ["/runs", "/connectors", "/validate", "/workflows", "/health", "/stats", "/meta", "/presets"].map((p) => [p, api]),
    ),
  },
  build: { outDir: "dist", emptyOutDir: true, sourcemap: false },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    css: false,
  },
});
