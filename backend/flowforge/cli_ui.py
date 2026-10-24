"""Offline terminal views and encoding-safe Rich presentation (D41)."""

from __future__ import annotations

import argparse
import os
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from rich import box
from rich.console import Console
from rich.table import Table
from rich.text import Text

# Camel-cased, shadowed block letters: tall F's and lower-case companions (D41).
BANNER = """███████╗██╗                ███████╗
██╔════╝██║                ██╔════╝
█████╗  ██║ ████╗ ██╗  ██╗ █████╗  ████╗ ████╗  ████╗  ████╗
██╔══╝  ██║██╔═██╗██║  ██║ ██╔══╝ ██╔═██╗██╔═╝ ██╔═██╗██╔═██╗
██║     ██║██║ ██║██║█╗██║ ██║    ██║ ██║██║   ██║ ██║█████╔╝
╚═╝     ╚═╝╚████╔╝╚██╔██╔╝ ╚═╝    ╚████╔╝╚═╝   ╚████║╚████╗
            ╚═══╝  ╚═╝╚═╝          ╚═══╝        ╚══██║ ╚═══╝
                                               █████╔╝
                                               ╚════╝"""

STYLES = {"up": "green", "warn": "yellow", "down": "red", "unchecked": "bright_black",
          "high": "red", "medium": "yellow", "low": "blue", "saved": "green", "missing": "yellow",
          "unreadable": "red", "env_file": "bright_black"}
KEY_LABELS = {"saved": "saved", "missing": "missing", "unreadable": "can't read", "env_file": "in .env"}


class TerminalConsole(Console):
    """Replace unencodable text, including user paths, on Windows pipes (D41)."""

    def _render_buffer(self, buffer: list[Any]) -> str:
        rendered = super()._render_buffer(buffer)
        encoding = self.file.encoding or "ascii"
        return rendered.encode(encoding, errors="replace").decode(encoding)


def utf8(out: Console) -> bool:
    """Whether Unicode decorations are safe (D41)."""
    return (out.file.encoding or "").lower().replace("-", "") in ("utf8", "utf8sig")


def console(plain: bool = False) -> Console:
    """No colour or animation outside an opted-in terminal (D41)."""
    colour = not plain and "NO_COLOR" not in os.environ and sys.stdout.isatty()
    return TerminalConsole(file=sys.stdout, force_terminal=colour, color_system="truecolor" if colour else None,
                           no_color=not colour, markup=False, highlight=False, safe_box=True)


def banner(out: Console) -> None:
    """The blue FlowForge wordmark, only on colourful terminals (D41)."""
    if not out.is_terminal or out.no_color or not utf8(out):
        return
    width = max(map(len, BANNER.splitlines()))
    art = Text()
    for row in BANNER.splitlines():
        for i, char in enumerate(row):
            ratio = i / (width - 1)
            rgb = tuple(round(a + (b - a) * ratio) for a, b in zip((36, 87, 197), (127, 168, 255), strict=True))
            art.append(char, style=f"rgb({rgb[0]},{rgb[1]},{rgb[2]})")
        art.append("\n")
    out.print(art, crop=False, overflow="ignore")
    out.print("FlowForge", style="bold #7FA8FF")


def level(value: str) -> Text:
    """A coloured, literal status or severity (D41)."""
    return Text(value, style=STYLES.get(value, ""))


def dot(out: Console, status: str) -> Text:
    """Health keeps its label even without colour (D41)."""
    return Text(f"{'●' if utf8(out) else '*'} {status}", style=STYLES.get(status, "bright_black"))


def table(out: Console, title: str, columns: list[str], rows: list[list[Any]], *, border: bool = True) -> None:
    """Tables use ASCII borders on non-UTF-8 output (D41)."""
    edges = (box.ROUNDED if utf8(out) else box.ASCII) if border else None
    view = Table(title=title, box=edges, expand=False)
    for name in columns:
        view.add_column(name, overflow="fold")
    for row in rows:
        view.add_row(*(cell if isinstance(cell, Text) else Text(str(cell)) for cell in row))
    out.print(view)


def findings(out: Console, result: Any) -> None:
    """Show only the scanner's masked finding fields (D41)."""
    counts = Counter(f.level for f in result.findings)
    out.print(f"Issues: {len(result.findings)} ({counts['high']} high, {counts['medium']} medium, {counts['low']} low)")
    table(out, "Issues", ["Level", "Title", "File:line", "Fix"],
          [[level(f.level), f.title, f.ref, f.fix] for f in result.findings])


def scan_summary(out: Console, result: Any) -> None:
    """The interactive scan view; JSON stays in the old path (D41)."""
    counts = Counter(d.kind for d in result.dependencies)
    out.print(f"{result.root}: {len(result.dependencies)} dependencies, {result.files_scanned} files")
    out.print(", ".join(f"{counts[k]} {k}" for k in ("llm", "api", "mcp", "local")))
    table(out, "Dependencies", ["Name", "Kind", "File:line"],
          [[d.name, d.kind, d.evidence[0].ref if d.evidence else ""] for d in result.dependencies])
    findings(out, result)


def key_table(out: Console, found: list[dict[str, Any]]) -> None:
    """Key names and statuses, never values (D41)."""
    table(out, "Keys", ["Name", "Status", "File:line"],
          [[k["name"], Text(KEY_LABELS[k["status"]], style=STYLES[k["status"]]), k["ref"] or ""] for k in found],
          border=False)
    if not found:
        out.print("No keys: the code reads none, and none are saved.")
    for key in found:
        if key["command"]:
            out.print(key["command"])


def project_command(command: str, argv: list[str], plain: bool = False) -> None:
    """Route the offline project commands without starting the API (D41)."""
    from flowforge import home, settings
    from flowforge.api.projects import summary
    from flowforge.projects import Projects
    from flowforge.scan import ScanResult
    from flowforge.security.keystore import KeyStore, report
    from flowforge.storage import Storage

    parser = argparse.ArgumentParser(prog=f"flowforge {command}")
    parser.add_argument("--plain", action="store_true", help="no colour, animation or banner")
    if command in ("status", "issues", "check"):
        parser.add_argument("project", nargs="?", help="project id or name (default: here, else last opened)")
    args = parser.parse_args(argv)
    out = console(plain or args.plain)
    if command == "status":
        banner(out)
    if command == "settings":
        saved = settings.load()
        table(out, "Settings", ["Setting", "Value"], [
            ["Welcome done", str(saved.welcome_done).lower()], ["Map style", saved.map_style or "studio"],
            ["Data", str(home.flowforge_home())], ["Version", home.version()], ["Install", home.install_kind()]])
        return
    registry = Projects()
    projects = sorted(registry.list(), key=lambda p: p.opened or p.added, reverse=True)
    if command != "projects":
        selected = (registry.find(args.project) if args.project else
                    registry.for_folder(Path.cwd()) or
                    max(projects, key=lambda p: (p.opened is not None, p.opened or p.added), default=None))
        if selected is None:
            if args.project:
                parser.error("No such project. Run flowforge projects to see project names.")
            out.print("No projects yet. Next: flowforge --repo .")
            return
        projects = [selected]
    rows = []
    for project in projects:
        storage = Storage(Path(project.db)) if Path(project.db).is_file() else None
        try:
            counts = summary(storage, Path(project.path)) if storage else {
                "dependencies": 0, "issues": 0, "keys_missing": 0}
            if command == "projects":
                rows.append([project.name, project.path, counts["dependencies"], counts["issues"],
                             counts["keys_missing"], project.opened or "never"])
                continue
            out.print(f"{project.name} ({project.path})")
            saved = storage.latest_flow_version("deps") if storage else None
            raw = (saved or {}).get("analysis") or {}
            if not raw.get("scan"):
                out.print("No saved scan. Next: open this project in the dashboard and re-scan.")
                continue
            try:
                result = ScanResult.model_validate(raw["scan"])
            except ValueError:
                out.print("The saved scan is unreadable. Next: re-scan from the dashboard.")
                continue
            if command == "issues":
                findings(out, result)
            elif command == "check":
                table(out, "Check plan (nothing runs)", ["Dependency", "Kind", "Would check"],
                      [[d.name, d.kind, " ".join(d.command or []) or d.target or "not configured"]
                       for d in result.dependencies])
                if any(d.kind == "mcp" for d in result.dependencies):
                    out.print("MCP servers need your yes to their exact commands in the dashboard (D24).")
                out.print("Next: run checks from the dashboard (flowforge).")
            else:
                health = {r["dep_id"]: r["status"] for r in storage.check_history(limit=1)}
                table(out, f"Dependencies: {counts['dependencies']}", ["Name", "Kind", "Health"],
                      [[d.name, d.kind, dot(out, health.get(d.id, "unchecked"))] for d in result.dependencies])
                by_level = Counter(f.level for f in result.findings)
                out.print(f"Issues: {len(result.findings)} ({by_level['high']} high, "
                          f"{by_level['medium']} medium, {by_level['low']} low)")
                keys = report(KeyStore(Path(project.path)), result, verify=False)
                missing = [k for k in keys if k["status"] in ("missing", "unreadable")]
                out.print(f"Keys missing: {len(missing)}")
                for key in missing:
                    out.print(key["name"])
                out.print(f"Next: {missing[0]['command']}" if missing else
                          "Next: flowforge issues" if result.findings else "Next: flowforge check")
        finally:
            if storage:
                storage.conn.close()
    if command == "projects":
        table(out, "Projects", ["Name", "Folder", "Dependencies", "Issues", "Keys missing", "Last opened"], rows)
        if not rows:
            out.print("No projects yet. Next: flowforge --repo .")
