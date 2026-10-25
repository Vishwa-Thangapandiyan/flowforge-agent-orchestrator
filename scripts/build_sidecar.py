"""Build the desktop app's server (D42): FlowForge's wheel, frozen by PyInstaller into one file named the way Tauri
expects a sidecar (`flowforge-<target triple>`; installed as the `flowforge` command, D50), then smoke-tested.

    uv run python scripts/build_sidecar.py           # needs frontend/dist (npm run build in frontend/)
    uv run python scripts/build_sidecar.py --skip-smoke
"""

from __future__ import annotations

import argparse
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / "build" / "sidecar"
BINARIES = ROOT / "desktop" / "src-tauri" / "binaries"
EXE = ".exe" if sys.platform == "win32" else ""


def run(*cmd: str | Path, **kwargs) -> None:
    print("$", " ".join(map(str, cmd)), flush=True)
    subprocess.run(list(map(str, cmd)), check=True, **kwargs)


def target_triple() -> str:
    """The Rust host triple, e.g. x86_64-unknown-linux-gnu: Tauri finds a sidecar by it."""
    out = subprocess.run(["rustc", "-vV"], capture_output=True, text=True, check=True).stdout
    return next(line.split(": ", 1)[1] for line in out.splitlines() if line.startswith("host: "))


def build() -> Path:
    if not (ROOT / "frontend" / "dist" / "index.html").is_file():
        raise SystemExit("frontend/dist is missing: run `npm run build` in frontend/ first")
    shutil.rmtree(WORK, ignore_errors=True)
    run("uv", "build", "--wheel", "-o", WORK / "wheel", cwd=ROOT)
    venv = WORK / "venv"
    run("uv", "venv", "-q", venv)
    python = venv / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    wheel = next((WORK / "wheel").glob("*.whl"))
    run("uv", "pip", "install", "-q", "--python", python, wheel, "pyinstaller>=6")
    run(python, "-m", "PyInstaller", ROOT / "scripts" / "desktop_entry.py", "--name", "flowforge", "--onefile",
        "--noconfirm", "--distpath", WORK / "dist", "--workpath", WORK / "work", "--specpath", WORK,
        "--collect-all", "flowforge", "--copy-metadata", "flowforge-map",   # home.version() reads the metadata
        "--collect-submodules", "uvicorn", "--collect-submodules", "keyring")   # mcp: from imports (not its cli)
    BINARIES.mkdir(parents=True, exist_ok=True)
    target = BINARIES / f"flowforge-{target_triple()}{EXE}"
    shutil.copy2(WORK / "dist" / f"flowforge{EXE}", target)
    print(f"built {target} ({target.stat().st_size // 2**20} MB)", flush=True)
    return target


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def smoke(binary: Path) -> None:
    """The frozen server says its version, starts, and serves the dashboard's data, with a fresh FLOWFORGE_HOME."""
    version = subprocess.run([binary, "--version"], capture_output=True, text=True, timeout=120)
    print(version.stdout.strip(), flush=True)
    assert version.returncode == 0 and version.stdout.startswith("flowforge "), version.stderr[-500:]
    home, port = tempfile.mkdtemp(prefix="ffdesk-"), free_port()
    env = {**os.environ, "FLOWFORGE_HOME": home}
    env.pop("FLOWFORGE_DB", None)
    server = subprocess.Popen([binary, "serve", "--no-open", "--port", str(port)], env=env,
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        for _ in range(120):
            if server.poll() is not None:
                raise SystemExit(f"the server stopped: {server.stdout.read() if server.stdout else ''}")
            try:
                if httpx.get(f"http://127.0.0.1:{port}/meta", timeout=2).status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            time.sleep(0.5)
        else:
            raise SystemExit("no answer from /meta")
        settings = httpx.get(f"http://127.0.0.1:{port}/settings", timeout=10).json()
        assert settings["install"] == "desktop", settings["install"]
        assert settings["agent"]["command"][-1] == "mcp", settings["agent"]["command"]
        page = httpx.get(f"http://127.0.0.1:{port}/", headers={"Accept": "text/html"}, timeout=10)
        assert '<div id="root"' in page.text, "the dashboard page isn't served"
        print("ok   the bundled server serves the dashboard, /meta and /settings (install: desktop)", flush=True)
    finally:
        server.terminate()
        server.wait(timeout=20)


def agent_smoke(binary: Path) -> None:
    """A coding agent can start the bundled server the way Settings pairs it (`<binary> mcp`) and list its tools."""
    import asyncio
    import json

    from mcp import Client, StdioServerParameters

    async def tools() -> list[str]:
        env = {**os.environ, "FLOWFORGE_HOME": tempfile.mkdtemp(prefix="ffdesk-mcp-")}
        async with Client(StdioServerParameters(command=str(binary), args=["mcp"], env=env)) as client:
            found = [t.name for t in (await client.list_tools()).tools]
            listed = await client.call_tool("list_projects", {})
            json.loads(listed.content[0].text)
            return found

    found = asyncio.run(tools())
    assert "get_map" in found and "list_projects" in found, found
    print(f"ok   an agent pairs with the bundled server: {len(found)} tools", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--skip-smoke", action="store_true")
    args = parser.parse_args()
    binary = build()
    if not args.skip_smoke:
        smoke(binary)
        agent_smoke(binary)


if __name__ == "__main__":
    main()
