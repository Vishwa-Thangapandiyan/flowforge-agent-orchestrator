// `npx flowforge-map` (D49): run FlowForge with no Python. The launcher finds FlowForge's frozen program (the same one
// the desktop app carries, D42) in ~/.flowforge/bin/<version>/, or downloads it once from this repo's GitHub Release,
// checks it against the release's SHA256SUMS, and runs it with your arguments. No shell, no install script, no
// dependencies. With no build for this computer it runs `uvx flowforge-map==<version>` instead.
"use strict";
const crypto = require("node:crypto");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { spawn } = require("node:child_process");

const REPO = "Vishwa-Thangapandiyan/flowforge-agent-orchestrator";
const PACKAGE = "flowforge-map";
// the GitHub hosts a release download goes through (github.com redirects to its asset storage)
const GITHUB_HOSTS = ["github.com", "objects.githubusercontent.com", "release-assets.githubusercontent.com"];

/** Linux with musl (Alpine) rather than glibc: the glibc build can't start there (Codex review). */
function isMusl() {
  if (process.platform !== "linux") return false;
  try {
    return !process.report.getReport().header.glibcVersionRuntime;
  } catch {
    return false;
  }
}

/** The release file built for this computer, or null when there is none (D49's four platforms; not musl). */
function assetFor(platform, arch, { musl = platform === "linux" && isMusl() } = {}) {
  if (platform === "linux" && musl) return null;
  const builds = {
    "linux-x64": "flowforge-linux-x64",
    "darwin-arm64": "flowforge-darwin-arm64",
    "darwin-x64": "flowforge-darwin-x64",
    "win32-x64": "flowforge-windows-x64.exe",
  };
  return builds[`${platform}-${arch}`] ?? null;
}

function releaseBase(version) {
  return `https://github.com/${REPO}/releases/download/v${version}/`;
}

/** Which hosts a download may go to: GitHub's own for the real releases, or the one host of a mirror the user named
 *  (FLOWFORGE_RELEASES_URL; tests use a local server). */
function trustedHosts(base) {
  const own = new URL(base).host;
  if (own === "github.com") return (host) => GITHUB_HOSTS.includes(host);
  return (host) => host === own;
}

function flowforgeHome(env = process.env) {
  return env.FLOWFORGE_HOME || path.join(os.homedir(), ".flowforge");
}

/** `<sha256>  <file>` lines (`*file` for binary mode) → Map(file → sha256). */
function parseSums(text) {
  const out = new Map();
  for (const line of text.split(/\r?\n/)) {
    const m = line.trim().match(/^([0-9a-fA-F]{64})\s+\*?(.+)$/);
    if (m) out.set(m[2].trim(), m[1].toLowerCase());
  }
  return out;
}

const STALL_MS = 30000;   // no data for this long: the download has stalled (a slow one that moves goes on)

/** GET `url`, following redirects only to trusted hosts. Returns the body as a Buffer. Gives up when no data
 *  arrives for `stallMs`, so a stalled download reaches the fallback instead of waiting forever (Codex review). */
async function fetchTrusted(url, trusted, { stallMs = STALL_MS, maxRedirects = 5 } = {}) {
  let current = url;
  for (let hop = 0; hop <= maxRedirects; hop++) {
    const host = new URL(current).host;
    if (!trusted(host)) throw new Error(`refused a download from ${host}: not this release's host`);
    const abort = new AbortController();
    let timer = setTimeout(() => abort.abort(), stallMs);
    const alive = () => { clearTimeout(timer); timer = setTimeout(() => abort.abort(), stallMs); };
    try {
      const res = await fetch(current, { redirect: "manual", signal: abort.signal,
                                         headers: { "user-agent": `${PACKAGE}-npx` } });
      if (res.status >= 300 && res.status < 400 && res.headers.get("location")) {
        current = new URL(res.headers.get("location"), current).toString();
        await res.body?.cancel();
        continue;
      }
      if (!res.ok) throw new Error(`${new URL(current).pathname.split("/").pop()}: HTTP ${res.status}`);
      const chunks = [];
      const reader = res.body.getReader();
      for (;;) {
        alive();
        const { done, value } = await reader.read();
        if (done) break;
        chunks.push(Buffer.from(value));
      }
      return Buffer.concat(chunks);
    } catch (err) {
      if (abort.signal.aborted) throw new Error(`no data for ${Math.round(stallMs / 1000)} s: the download stalled`);
      throw err;
    } finally {
      clearTimeout(timer);
    }
  }
  throw new Error("too many redirects");
}

/** The program for `version`: already in ~/.flowforge/bin/<version>/, or downloaded and checked now.
 *  Returns { path } or { path: null, reason }. Nothing that fails its checksum is kept or run. */
async function ensureProgram({ version, home = flowforgeHome(), base = releaseBase(version),
                               platform = process.platform, arch = process.arch, stallMs = STALL_MS }) {
  const asset = assetFor(platform, arch);
  if (!asset) return { path: null, reason: `no FlowForge build for ${platform}-${arch} yet` };
  const dir = path.join(home, "bin", version);
  const target = path.join(dir, platform === "win32" ? "flowforge.exe" : "flowforge");
  if (fs.existsSync(target)) return { path: target };
  const trusted = trustedHosts(base);
  let body;
  let sums;
  try {
    sums = parseSums((await fetchTrusted(new URL("SHA256SUMS", base).toString(), trusted, { stallMs })).toString("utf8"));
    body = await fetchTrusted(new URL(asset, base).toString(), trusted, { stallMs });
  } catch (err) {
    return { path: null, reason: `couldn't download FlowForge ${version}: ${err.message}` };
  }
  const want = sums.get(asset);
  const got = crypto.createHash("sha256").update(body).digest("hex");
  if (!want || want !== got) {
    return { path: null, reason: `the download's checksum doesn't match the release's SHA256SUMS: not run` };
  }
  fs.mkdirSync(dir, { recursive: true });
  const temp = path.join(dir, `.${path.basename(target)}.${process.pid}.${Date.now()}.tmp`);
  fs.writeFileSync(temp, body, { mode: 0o755, flag: "wx" });   // a new file, never one already there
  fs.renameSync(temp, target);
  return { path: target };
}

/** The environment FlowForge runs with: yours, plus how it was started, so the agent's command says npx (D49). */
function programEnv(env, version) {
  return { ...env, FLOWFORGE_LAUNCHER: "npx", FLOWFORGE_NPX_VERSION: version };
}

/** A real program on PATH: on Windows only `name.exe`, never a .cmd/.bat wrapper, which would need a shell. */
function onPath(name, env) {
  const file = process.platform === "win32" ? `${name}.exe` : name;
  for (const dir of (env.PATH || "").split(path.delimiter)) {
    if (dir && fs.existsSync(path.join(dir, file))) return path.join(dir, file);
  }
  return null;
}

/** With no build for this computer: uv runs the same version from PyPI; with no uv, one line on what to install. */
function fallback(version, args, env = process.env) {
  const uvx = onPath("uvx", env);
  if (uvx) return { command: uvx, args: [`${PACKAGE}==${version}`, ...args] };
  return {
    command: null,
    message: "To run FlowForge another way, install uv (https://docs.astral.sh/uv/) and run this again, or use " +
      "the desktop app.",
  };
}

/** Run `program` with `args` (a list, never a shell). Resolves to { code } (and stdout when `capture`). */
function runProgram(program, args, env, { capture = false } = {}) {
  if (/\.(cmd|bat)$/i.test(program)) {   // a script wrapper runs through a shell: never (Codex review)
    return Promise.resolve({ code: 127, stdout: "", error: "a script wrapper needs a shell: not run" });
  }
  return new Promise((resolve) => {
    const child = spawn(program, args, {
      env, stdio: capture ? ["ignore", "pipe", "inherit"] : "inherit", shell: false, windowsHide: true,
    });
    let stdout = "";
    if (capture) child.stdout.on("data", (d) => { stdout += d; });
    const forward = (signal) => () => child.kill(signal);
    const handlers = ["SIGINT", "SIGTERM"].map((s) => [s, forward(s)]);
    for (const [s, h] of handlers) process.on(s, h);
    child.on("error", (err) => {
      for (const [s, h] of handlers) process.off(s, h);
      resolve({ code: 127, stdout, error: err.message });
    });
    child.on("exit", (code, signal) => {
      for (const [s, h] of handlers) process.off(s, h);
      resolve({ code: code ?? (signal ? 128 + (os.constants.signals[signal] || 1) : 1), stdout });
    });
  });
}

async function main(argv = process.argv.slice(2), env = process.env) {
  const version = require("../package.json").version;
  const base = env.FLOWFORGE_RELEASES_URL || releaseBase(version);
  const got = await ensureProgram({ version, home: flowforgeHome(env), base });
  if (got.path) return (await runProgram(got.path, argv, programEnv(env, version))).code;
  process.stderr.write(`flowforge-map: ${got.reason}\n`);
  const plan = fallback(version, argv, env);
  if (!plan.command) {
    process.stderr.write(`flowforge-map: ${plan.message}\n`);
    return 1;
  }
  process.stderr.write(`flowforge-map: running it with uv instead\n`);
  return (await runProgram(plan.command, plan.args, env)).code;
}

module.exports = {
  REPO, PACKAGE, isMusl, assetFor, releaseBase, trustedHosts, flowforgeHome, parseSums, ensureProgram, programEnv, fallback,
  runProgram, main,
};
