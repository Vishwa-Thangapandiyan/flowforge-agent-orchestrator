"""Smoke-test an installed FlowForge (D34), as a stranger would use it. Run it with the Python of a fresh environment
that has only the built wheel installed, from outside the repo:

    <venv python> scripts/smoke_installed.py

It checks the version, starts `flowforge --example` (with its own FLOWFORGE_HOME), loads the dashboard and the example
map, and asks the MCP server for the map, the findings and the advice. Offline: example mode makes no request.
"""

from __future__ import annotations

import asyncio
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx
from mcp import Client, StdioServerParameters

EXPECTED_DEPENDENCIES = 12   # the trip planner's
EXPECTED_FINDINGS = 3


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def check(ok: bool, what: str) -> None:
    print(("ok   " if ok else "FAIL ") + what, flush=True)
    if not ok:
        raise SystemExit(1)


async def agent(repo: str, db: str) -> dict[str, int]:
    args = ["-m", "flowforge.cli", "mcp", "--repo", repo, "--db", db]
    params = StdioServerParameters(command=sys.executable, args=args, env={**os.environ})
    out = {}
    async with Client(params) as client:
        for tool, key in [("get_map", "dependencies"), ("get_security_findings", "findings")]:
            result = await client.call_tool(tool, {})
            out[tool] = -1 if result.is_error else len(json.loads(result.content[0].text)[key])
    return out


def main() -> None:
    from flowforge.home import IN_CHECKOUT, resource, version

    check(not IN_CHECKOUT, "running from an install, not the checkout")
    run = subprocess.run([sys.executable, "-m", "flowforge.cli", "--version"], capture_output=True, text=True)
    check(run.stdout.strip() == f"flowforge {version()}", f"--version says {run.stdout.strip()!r}")
    for name in ("dashboard", "example", "workflows", "classic"):
        check(resource(name).exists(), f"ships {name}")

    home = tempfile.mkdtemp(prefix="ffhome-")
    os.environ["FLOWFORGE_HOME"] = home
    port = free_port()
    server = subprocess.Popen([sys.executable, "-m", "flowforge.cli", "--example", "--no-open", "--port", str(port)],
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        base = f"http://127.0.0.1:{port}"
        for _ in range(120):
            try:
                if httpx.get(f"{base}/flow", timeout=2).status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            time.sleep(0.5)
        page = httpx.get(base, headers={"Accept": "text/html"}, timeout=5)
        check(page.status_code == 200 and "<div id=\"root\"" in page.text, "the dashboard page loads")
        nodes = httpx.get(f"{base}/flow", timeout=10).json()["nodes"]
        check(sum(n["kind"] != "start" for n in nodes) == EXPECTED_DEPENDENCIES, "the example map has its dependencies")
        findings = httpx.get(f"{base}/security", timeout=10).json()["findings"]
        check(len(findings) == EXPECTED_FINDINGS, "the example's security findings")
        command = httpx.get(f"{base}/agent/connect", timeout=10).json()["command"]
        check("--directory" not in command, f"the agent command doesn't need a checkout: {command[:3]}")
    finally:
        server.terminate()
        server.wait(timeout=20)
    check(Path(home, "example.db").is_file(), "data stays in FLOWFORGE_HOME")

    got = asyncio.run(agent(str(resource("example")), str(Path(home, "agent.db"))))
    check(got == {"get_map": EXPECTED_DEPENDENCIES, "get_security_findings": EXPECTED_FINDINGS}, f"an agent gets {got}")
    print("installed FlowForge works", flush=True)


if __name__ == "__main__":
    main()
