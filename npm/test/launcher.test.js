// `npx flowforge-map` (D49): the launcher finds, downloads, verifies and runs FlowForge's frozen program, offline in
// tests: a local server stands in for GitHub Releases and a small script stands in for the program.
"use strict";
const { test } = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const http = require("node:http");
const os = require("node:os");
const path = require("node:path");
const crypto = require("node:crypto");
const L = require("../lib/launcher");

const WIN = process.platform === "win32";

/** A stand-in for FlowForge: prints its arguments as JSON, exits with the code in FAKE_EXIT. */
function fakeProgram() {
  if (WIN) return Buffer.from(`@echo off\r\nnode -e "console.log(JSON.stringify(process.argv.slice(1)))" -- %*\r\nexit /b %FAKE_EXIT%\r\n`);
  return Buffer.from(`#!/usr/bin/env node\nconsole.log(JSON.stringify(process.argv.slice(2)));\nprocess.exit(Number(process.env.FAKE_EXIT || 0));\n`);
}

function sha(buf) { return crypto.createHash("sha256").update(buf).digest("hex"); }

/** A local "release": serves the program and SHA256SUMS; counts requests; can redirect elsewhere. */
async function release({ body = fakeProgram(), sums, redirectTo } = {}) {
  const asset = L.assetFor(process.platform, process.arch);
  const requests = [];
  const server = http.createServer((req, res) => {
    requests.push(req.url);
    if (redirectTo) { res.writeHead(302, { location: redirectTo }); return res.end(); }
    if (req.url.endsWith("/SHA256SUMS")) return res.end(sums ?? `${sha(body)}  ${asset}\n`);
    if (req.url.endsWith(`/${asset}`)) return res.end(body);
    res.writeHead(404); res.end();
  });
  await new Promise((r) => server.listen(0, "127.0.0.1", r));
  const base = `http://127.0.0.1:${server.address().port}/v9.9.9/`;
  return { base, requests, close: () => new Promise((r) => server.close(r)) };
}

function home() { return fs.mkdtempSync(path.join(os.tmpdir(), "ffnpx-")); }

test("each computer gets its own build, and an unknown one gets none", () => {
  assert.equal(L.assetFor("linux", "x64"), "flowforge-linux-x64");
  assert.equal(L.assetFor("darwin", "arm64"), "flowforge-darwin-arm64");
  assert.equal(L.assetFor("darwin", "x64"), "flowforge-darwin-x64");
  assert.equal(L.assetFor("win32", "x64"), "flowforge-windows-x64.exe");
  assert.equal(L.assetFor("linux", "arm64"), null);
  assert.equal(L.assetFor("freebsd", "x64"), null);
});

test("SHA256SUMS is read line by line", () => {
  const sums = L.parseSums("aa".repeat(32) + "  flowforge-linux-x64\n" + "bb".repeat(32) + " *flowforge-windows-x64.exe\n\n");
  assert.equal(sums.get("flowforge-linux-x64"), "aa".repeat(32));
  assert.equal(sums.get("flowforge-windows-x64.exe"), "bb".repeat(32));
});

test("the first run downloads and checks the program; the next runs use it without a download", async () => {
  const r = await release();
  const h = home();
  try {
    const first = await L.ensureProgram({ version: "9.9.9", home: h, base: r.base });
    assert.ok(first.path && fs.existsSync(first.path), first.reason);
    if (!WIN) assert.ok(fs.statSync(first.path).mode & 0o100, "executable");
    const asked = r.requests.length;
    const again = await L.ensureProgram({ version: "9.9.9", home: h, base: r.base });
    assert.equal(again.path, first.path);
    assert.equal(r.requests.length, asked, "no second download");
  } finally { await r.close(); }
});

test("a program whose checksum doesn't match never runs and is not kept", async () => {
  const r = await release({ sums: `${"00".repeat(32)}  ${L.assetFor(process.platform, process.arch)}\n` });
  const h = home();
  try {
    const got = await L.ensureProgram({ version: "9.9.9", home: h, base: r.base });
    assert.equal(got.path, null);
    assert.match(got.reason, /checksum/);
    const dir = path.join(h, "bin", "9.9.9");
    assert.deepEqual(fs.existsSync(dir) ? fs.readdirSync(dir) : [], []);
  } finally { await r.close(); }
});

test("a release with no checksum for the program is refused", async () => {
  const r = await release({ sums: "" });
  try {
    const got = await L.ensureProgram({ version: "9.9.9", home: home(), base: r.base });
    assert.equal(got.path, null);
    assert.match(got.reason, /checksum/);
  } finally { await r.close(); }
});

test("a redirect to a host that isn't the release's is refused", async () => {
  const r = await release({ redirectTo: "http://evil.test/flowforge" });
  try {
    const got = await L.ensureProgram({ version: "9.9.9", home: home(), base: r.base });
    assert.equal(got.path, null);
    assert.match(got.reason, /evil\.test/);
  } finally { await r.close(); }
});

test("only GitHub's own hosts are trusted for the real releases", () => {
  const ok = L.trustedHosts(L.releaseBase("1.2.3"));
  assert.ok(ok("github.com") && ok("objects.githubusercontent.com") && ok("release-assets.githubusercontent.com"));
  assert.ok(!ok("evil.test") && !ok("github.com.evil.test") && !ok("githubusercontent.com.evil.test"));
  assert.equal(L.releaseBase("1.2.3"),
    "https://github.com/Vishwa-Thangapandiyan/flowforge-agent-orchestrator/releases/download/v1.2.3/");
});

test("the program runs with your arguments as they are, no shell, and its exit code is yours", async () => {
  const h = home();
  const program = path.join(h, WIN ? "fake.cmd" : "fake");
  fs.writeFileSync(program, fakeProgram(), { mode: 0o755 });
  const marker = path.join(h, "shell-ran");
  const out = await L.runProgram(program, ["key", "add", "A_KEY", `; touch ${marker}`], { ...process.env, FAKE_EXIT: "7" },
                                 { capture: true });
  assert.equal(out.code, 7);
  assert.ok(!fs.existsSync(marker), "no shell");
  if (!WIN) assert.deepEqual(JSON.parse(out.stdout), ["key", "add", "A_KEY", `; touch ${marker}`]);
});

test("the program knows it was started by npx, for the agent's command", () => {
  const env = L.programEnv({ PATH: "/bin" }, "0.4.0");
  assert.equal(env.FLOWFORGE_LAUNCHER, "npx");
  assert.equal(env.FLOWFORGE_NPX_VERSION, "0.4.0");
  assert.equal(env.PATH, "/bin");
});

test("with no build for this computer, uv runs the same version; with no uv either, one clear line", async () => {
  const h = home();
  const bin = path.join(h, "bin");
  fs.mkdirSync(bin);
  const uvx = path.join(bin, WIN ? "uvx.cmd" : "uvx");
  fs.writeFileSync(uvx, fakeProgram(), { mode: 0o755 });
  const plan = L.fallback("0.4.0", ["--repo", "."], { PATH: bin, PATHEXT: process.env.PATHEXT });
  assert.equal(plan.command, uvx);
  assert.deepEqual(plan.args, ["flowforge-map==0.4.0", "--repo", "."]);
  const none = L.fallback("0.4.0", [], { PATH: path.join(h, "empty") });
  assert.equal(none.command, null);
  assert.match(none.message, /uv|desktop app/);
});
