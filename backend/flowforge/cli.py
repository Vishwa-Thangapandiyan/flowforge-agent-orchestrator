"""`flowforge`: start the app and open the dashboard (D15, D16).

    uv run flowforge                  your data (flowforge.db), opens http://127.0.0.1:8000
    uv run flowforge --repo PATH      the same, mapping the folder PATH; a different folder needs --replace (D21)
    uv run flowforge --example        example data in FLOWFORGE_HOME/example.db, no keys needed
    uv run flowforge scan PATH        print the folder's dependencies as JSON; nothing stored, nothing sent
    uv run flowforge mcp [--repo P]   an MCP server for your coding agent, over stdio (D29); P defaults to here
    uv run flowforge serve --reload   (used by `npm run dev`; `serve` is optional)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import webbrowser
from pathlib import Path

from flowforge.home import flowforge_home, resource, version

DIST = resource("dashboard") / "index.html"


def parse(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="flowforge", description="Run the FlowForge dashboard.")
    parser.add_argument("command", nargs="?", default="serve", choices=["serve", "scan", "mcp"])
    parser.add_argument("path", nargs="?", help="scan: the folder to read")
    parser.add_argument("--repo", help="serve: map this folder; mcp: the repo to answer about (default: here)")
    parser.add_argument("--db", help="mcp: the dashboard's database (default: FLOWFORGE_DB, else flowforge.db)")
    parser.add_argument("--replace", action="store_true",
                        help="serve: --repo names a different folder than last time, so start a fresh map")
    parser.add_argument("--example", action="store_true", help="use example data (no keys, no network)")
    parser.add_argument("--version", action="version", version=f"flowforge {version()}")
    parser.add_argument("--host", default=os.getenv("FLOWFORGE_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--no-open", action="store_true", help="don't open the browser")
    parser.add_argument("--reload", action="store_true", help="restart when Python files change (development)")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    import uvicorn

    args = parse(argv)
    if args.command == "scan":
        scan_folder(args.path)
        return
    if args.command == "mcp":
        serve_agent(args.repo, args.db)
        return
    if args.repo:
        if not Path(args.repo).expanduser().is_dir():
            raise SystemExit(f"flowforge: {args.repo} is not a folder")
        os.environ["FLOWFORGE_REPO"] = str(Path(args.repo).expanduser().resolve())
        if args.replace:
            os.environ["FLOWFORGE_REPO_REPLACE"] = "1"
    if args.example:
        os.environ["FLOWFORGE_EXAMPLE"] = "1"
        os.environ.setdefault("FLOWFORGE_DB", str(flowforge_home() / "example.db"))
        flowforge_home().mkdir(parents=True, exist_ok=True)
    url = f"http://{args.host}:{args.port}/"
    if not DIST.exists():
        print("The dashboard isn't built yet: run `npm run build` in frontend/ (the classic page is at /classic).")
    print(f"FlowForge{' (example data)' if args.example else ''} at {url}")
    if not args.no_open:
        threading.Timer(1.5, webbrowser.open, args=(url,)).start()
    uvicorn.run("flowforge.main:app", host=args.host, port=args.port, reload=args.reload,
                reload_dirs=[str(Path(__file__).parent)] if args.reload else None)


def serve_agent(repo: str | None, db: str | None = None) -> None:
    """The MCP server a coding agent starts (D29). stdout is the agent's pipe, so everything else goes to stderr."""
    import logging

    from flowforge.agent import build_server
    from flowforge.home import database_path
    from flowforge.security.logfilter import Redactor, install_log_redaction
    from flowforge.storage import Storage

    root = Path(repo or ".").expanduser().resolve()
    if not root.is_dir():
        print(f"flowforge mcp: {root} is not a folder", file=sys.stderr)
        raise SystemExit(2)
    logging.basicConfig(stream=sys.stderr, level=logging.WARNING)
    redactor = Redactor()
    install_log_redaction(redactor)
    path = Path(db).expanduser() if db else database_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    build_server(root, Storage(path, redact=redactor.redact)).run("stdio")


def scan_folder(path: str | None) -> None:
    """Read-only and offline (D20): print what the folder depends on, with evidence."""
    from flowforge.scan import scan

    if not path:
        print("flowforge scan: name the folder to scan, for example `flowforge scan .`", file=sys.stderr)
        raise SystemExit(2)
    if not Path(path).expanduser().is_dir():
        print(f"flowforge scan: {path} is not a folder", file=sys.stderr)
        raise SystemExit(2)
    print(json.dumps(scan(Path(path).expanduser()).model_dump(mode="json"), indent=2))


if __name__ == "__main__":
    main()
