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

/** The release file built for this computer, or null when there is none (D49's four platforms). */
function assetFor(platform, arch) {
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

/** GET `url`, following redirects only to trusted hosts. Returns the body as a Buffer. */
async function fetchTrusted(url, trusted, maxRedirects = 5) {
  let current = url;
  for (let hop = 0; hop <= maxRedirects; hop++) {
    const host = new URL(current).host;
    if (!trusted(host)) throw new Error(`refused a download from ${host}: not this release's host`);
    const res = await fetch(current, { redirect: "manual", headers: { "user-agent": `${PACKAGE}-npx` } });
    if (res.status >= 300 && res.status < 400 && res.headers.get("location")) {
      current = new URL(res.headers.get("location"), current).toString();
      continue;
    }
    if (!res.ok) throw new Error(`${new URL(current).pathname.split("/").pop()}: HTTP ${res.status}`);
    return Buffer.from(await res.arrayBuffer());
  }
  throw new Error("too many redirects");
}

/** The program for `version`: already in ~/.flowforge/bin/<version>/, or downloaded and checked now.
 *  Returns { path } or { path: null, reason }. Nothing that fails its checksum is kept or run. */
async function ensureProgram({ version, home = flowforgeHome(), base = releaseBase(version),
                               platform = process.platform, arch = process.arch }) {
  const asset = assetFor(platform, arch);
  if (!asset) return { path: null, reason: `no FlowForge build for ${platform}-${arch} yet` };
  const dir = path.join(home, "bin", version);
  const target = path.join(dir, platform === "win32" ? "flowforge.exe" : "flowforge");
  if (fs.existsSync(target)) return { path: target };
  const trusted = trustedHosts(base);
  let body;
  let sums;
  try {
    sums = parseSums((await fetchTrusted(new URL("SHA256SUMS", base).toString(), trusted)).toString("utf8"));
    body = await fetchTrusted(new URL(asset, base).toString(), trusted);
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

function onPath(name, env) {
  const exts = process.platform === "win32" ? (env.PATHEXT || ".EXE;.CMD;.BAT").split(";").concat([""]) : [""];
  for (const dir of (env.PATH || "").split(path.delimiter)) {
    if (!dir) continue;
    for (const ext of exts) {
      const candidate = path.join(dir, name + ext.toLowerCase());
      if (fs.existsSync(candidate)) return candidate;
      const upper = path.join(dir, name + ext);
      if (ext && fs.existsSync(upper)) return upper;
    }
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
  return new Promise((resolve) => {
    const windowsScript = process.platform === "win32" && /\.(cmd|bat)$/i.test(program);   // tests' stand-ins only
    const child = spawn(program, args, {
      env, stdio: capture ? ["ignore", "pipe", "inherit"] : "inherit", shell: false, windowsHide: true,
      ...(windowsScript ? { shell: true } : {}),
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
  REPO, PACKAGE, assetFor, releaseBase, trustedHosts, flowforgeHome, parseSums, ensureProgram, programEnv, fallback,
  runProgram, main,
};
