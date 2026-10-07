// `npm run dev`: the API (example data, auto-reload) and the Vite dev server together.
// No shell and no extra dependency: each process is spawned directly, and Ctrl+C stops both.
import { spawn } from "node:child_process";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

// Vite's CLI entry, from the "bin" field of its package.json (newer Vite doesn't export the path)
const viteDir = join(dirname(fileURLToPath(import.meta.url)), "..", "node_modules", "vite");
const viteBin = JSON.parse(readFileSync(join(viteDir, "package.json"), "utf8")).bin;
const vite = join(viteDir, typeof viteBin === "string" ? viteBin : viteBin.vite);
const children = [
  ["api", "uv", ["run", "flowforge", "serve", "--example", "--reload", "--no-open", "--port", "8000"]],
  // the browser opens on the dashboard unless FLOWFORGE_NO_OPEN is set (CI, scripted checks)
  ["web", process.execPath, process.env.FLOWFORGE_NO_OPEN ? [vite] : [vite, "--open"]],
].map(([name, command, args]) => {
  const child = spawn(command, args, { stdio: "inherit", env: process.env });
  child.on("exit", (code) => {
    console.log(`[${name}] exited with code ${code}; stopping the other process`);
    stopAll(code ?? 0);
  });
  child.on("error", (err) => {
    console.error(`[${name}] could not start "${command}": ${err.message}`);
    if (name === "api") console.error("Install uv (https://docs.astral.sh/uv/) and run `uv sync` in the repo root.");
    stopAll(1);
  });
  return child;
});

let stopping = false;
function stopAll(code) {
  if (stopping) return;
  stopping = true;
  for (const child of children) if (child.exitCode === null) child.kill();
  process.exit(code);
}
process.on("SIGINT", () => stopAll(0));
process.on("SIGTERM", () => stopAll(0));
