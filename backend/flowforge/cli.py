"""`flowforge`: start the app and open the dashboard (D15, D16).

    uv run flowforge                  your data (flowforge.db), opens http://127.0.0.1:8000
    uv run flowforge --example        example data in FLOWFORGE_HOME/example.db, no keys needed
    uv run flowforge serve --reload   (used by `npm run dev`; `serve` is optional)
"""

from __future__ import annotations

import argparse
import os
import threading
import webbrowser
from pathlib import Path

from flowforge.home import flowforge_home

DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist" / "index.html"


def parse(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="flowforge", description="Run the FlowForge dashboard.")
    parser.add_argument("command", nargs="?", default="serve", choices=["serve"])
    parser.add_argument("--example", action="store_true", help="use example data (no keys, no network)")
    parser.add_argument("--host", default=os.getenv("FLOWFORGE_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--no-open", action="store_true", help="don't open the browser")
    parser.add_argument("--reload", action="store_true", help="restart when Python files change (development)")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    import uvicorn

    args = parse(argv)
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


if __name__ == "__main__":
    main()
