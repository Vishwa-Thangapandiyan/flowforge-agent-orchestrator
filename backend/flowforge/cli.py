"""`flowforge`: start the app and open the dashboard (D15, D16).

    uv run flowforge                  your data (flowforge.db), opens http://127.0.0.1:8000
    uv run flowforge --repo PATH      the same, mapping the folder PATH; a different folder needs --replace (D21)
    uv run flowforge --example        example data in FLOWFORGE_HOME/example.db, no keys needed
    uv run flowforge scan PATH        summarise dependencies (pipe or --json for JSON); nothing stored or sent
    uv run flowforge mcp [--repo P]   an MCP server for your coding agent, over stdio (D29); P defaults to here
    uv run flowforge serve --reload   (used by `npm run dev`; `serve` is optional)
    uv run flowforge key add NAME     save a key for this folder, typed hidden (D36); also: list, remove, import
    uv run flowforge run -- CMD ...   start your app with the saved keys in its environment (D36)
    uv run flowforge lock reset       turn off the key view's lock with its password and code (D37); --forget without
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
    parser = argparse.ArgumentParser(
        prog="flowforge", description="Run the FlowForge dashboard.",
        epilog="Commands: status [PROJECT], projects, issues [PROJECT], check [PROJECT], settings, "
               "scan PATH, key add|list|remove|import, run -- CMD, mcp, lock reset, serve.")
    parser.add_argument("command", nargs="?", default="serve", choices=["serve", "scan", "mcp"])
    parser.add_argument("path", nargs="?", help="scan: the folder to read")
    parser.add_argument("--plain", action="store_true", help="no colour, animation or banner")
    parser.add_argument("--json", action="store_true", help="scan: print JSON even on a terminal")
    parser.add_argument("--repo", help="serve: map this folder; mcp: only this folder (default: every project)")
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
    argv = sys.argv[1:] if argv is None else argv
    from flowforge.cli_ui import banner, console, project_command

    # Leave every argument after -- untouched: those belong to the user's program (D36, D41).
    boundary = argv.index("--") if "--" in argv else len(argv)
    plain = "--plain" in argv[:boundary]
    argv = [a for a in argv[:boundary] if a != "--plain"] + argv[boundary:]
    if argv[:1] in (["status"], ["projects"], ["issues"], ["check"], ["settings"]):
        project_command(argv[0], argv[1:], plain=plain)
        return
    if argv[:1] == ["key"]:
        keys_command(argv[1:], plain=plain)
        return
    if argv[:1] == ["run"]:
        run_with_keys(argv[1:])
        return
    if argv[:1] == ["lock"]:
        lock_command(argv[1:])
        return

    import uvicorn

    if "--help" in argv or "-h" in argv:
        banner(console(plain))
    args = parse(argv)
    if args.command == "scan":
        scan_folder(args.path, json_output=args.json, plain=plain)
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
    banner(console(plain))
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

    root = Path(repo).expanduser().resolve() if repo else None   # no --repo: every project (D39)
    if root is not None and not root.is_dir():
        print(f"flowforge mcp: {root} is not a folder", file=sys.stderr)
        raise SystemExit(2)
    logging.basicConfig(stream=sys.stderr, level=logging.WARNING)
    redactor = Redactor()
    install_log_redaction(redactor)
    if root is None:
        build_server(None, None).run("stdio")
        return
    path = Path(db).expanduser() if db else database_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    build_server(root, Storage(path, redact=redactor.redact)).run("stdio")


def scan_folder(path: str | None, json_output: bool = False, plain: bool = False) -> None:
    """Read-only and offline (D20): print what the folder depends on, with evidence."""
    from flowforge.scan import scan

    if not path:
        print("flowforge scan: name the folder to scan, for example `flowforge scan .`", file=sys.stderr)
        raise SystemExit(2)
    if not Path(path).expanduser().is_dir():
        print(f"flowforge scan: {path} is not a folder", file=sys.stderr)
        raise SystemExit(2)
    result = scan(Path(path).expanduser())
    if json_output or not sys.stdout.isatty():
        print(json.dumps(result.model_dump(mode="json"), indent=2))
    else:
        from flowforge.cli_ui import console, scan_summary

        scan_summary(console(plain), result)


def keys_command(argv: list[str], plain: bool = False) -> None:
    """`flowforge key add|list|remove|import`: keys for one folder, which only `flowforge run` hands out (D36).
    Values are never printed."""
    from flowforge.security.keystore import NAME, BadKey, KeyStore, report

    parser = argparse.ArgumentParser(prog="flowforge key", description="Keep your app's keys out of files and away "
                                     "from your coding agent. Values are never shown.")
    parser.add_argument("action", choices=["add", "list", "remove", "import"])
    parser.add_argument("name", nargs="?", help="add/remove: the env var name, e.g. STRIPE_SECRET_KEY; "
                                                "import: the file (default .env in the folder)")
    parser.add_argument("--repo", default=".", help="the app's folder (default: here)")
    args = parser.parse_args(argv)
    repo = Path(args.repo).expanduser()
    if not repo.is_dir():
        parser.error(f"{args.repo} is not a folder")
    store = KeyStore(repo)
    if args.action in ("add", "remove") and not (args.name and NAME.fullmatch(args.name)):
        parser.error("name the key as an env var name, e.g. STRIPE_SECRET_KEY")

    if args.action == "add":
        value = _read_value(args.name)
        try:
            where = store.add(args.name, value)
        except BadKey as e:
            parser.error(str(e))
        print(f"Saved {args.name} in {'your keychain' if where == 'keychain' else 'FlowForge (encrypted file)'}.")
        print("  Your app gets it with: flowforge run -- <the command that starts it>")
    elif args.action == "remove":
        print(f"Removed {args.name}." if store.remove(args.name) else f"{args.name} wasn't saved.")
    elif args.action == "import":
        source = Path(args.name).expanduser() if args.name else repo / ".env"
        if not source.is_file():
            parser.error(f"{source} isn't a file")
        names = store.import_env(source)
        print(f"Saved {len(names)} from {source.name}: {', '.join(names) or 'nothing to save'}.")
        if names:
            print(f"  Delete {source.name} once your app runs with `flowforge run -- ...`: a coding agent can read it.")
    else:
        from flowforge.scan import scan

        found = report(store, scan(repo))
        from flowforge.cli_ui import console, key_table

        key_table(console(plain), found)


def _read_value(name: str) -> str:
    """The key, typed hidden; or one line from a pipe (`pass show x | flowforge key add X`). Never echoed."""
    import getpass

    if sys.stdin.isatty():
        return getpass.getpass(f"{name} (typed hidden): ")
    return sys.stdin.readline().rstrip("\r\n")


def run_with_keys(argv: list[str]) -> None:
    """`flowforge run [--repo P] -- CMD ...`: CMD starts with this folder's saved keys added to its environment.
    The command is a list (never a shell), and its exit code is FlowForge's (D36)."""
    import subprocess

    from flowforge.security.keystore import KeyStore

    parser = argparse.ArgumentParser(prog="flowforge run", description="Start your app with its saved keys.")
    parser.add_argument("--repo", default=".", help="the folder whose keys to use (default: here)")
    parser.add_argument("command", nargs=argparse.REMAINDER, help="-- then the command that starts your app")
    args = parser.parse_args(argv)
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        parser.error("give the command after --, e.g. flowforge run -- python app.py")
    if not Path(args.repo).expanduser().is_dir():
        parser.error(f"{args.repo} is not a folder")
    env = {**os.environ, **KeyStore(Path(args.repo)).env()}
    try:
        code = subprocess.call(command, env=env)
    except FileNotFoundError:
        print(f"flowforge run: {command[0]} not found", file=sys.stderr)
        code = 127
    except KeyboardInterrupt:
        code = 130
    raise SystemExit(code)


def lock_command(argv: list[str]) -> None:
    """`flowforge lock reset [--forget]`: turn off the key view's lock (D37). Saved keys stay either way."""
    import getpass

    from flowforge.security.lock import Lock, LockError

    parser = argparse.ArgumentParser(prog="flowforge lock", description="The key view's lock. Your saved keys stay.")
    parser.add_argument("action", choices=["reset"])
    parser.add_argument("--forget", action="store_true",
                        help="you forgot the password: drop the lock without it (the dashboard will say so)")
    args = parser.parse_args(argv)
    lock = Lock()
    if lock.state() == "none":
        print("The key view has no lock.")
        return
    if args.forget:
        if input("Drop the key view's lock without its password? Your keys stay. [y/N] ").strip().lower() != "y":
            print("Nothing changed.")
            return
        lock.forget()
        print("The lock is off. The dashboard shows that it was reset until you unlock it again.")
        return
    try:
        lock.reset(getpass.getpass("Password (typed hidden): "), input("Code from your phone: "))
    except LockError as e:
        print(f"flowforge lock: {e}", file=sys.stderr)
        raise SystemExit(1) from None
    print("The lock is off. Set a new one on the Keys page.")


if __name__ == "__main__":
    main()
