"""Projects (D39): every folder FlowForge maps is a project with its own database, listed in
`FLOWFORGE_HOME/projects.json` (id, name, folder, database, when added and last opened). A database made before
projects keeps its place: it is listed as it is. Example data is a built-in project that is never stored here.
"""

from __future__ import annotations

import json
import re
import threading
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from flowforge.home import flowforge_home

EXAMPLE_ID = "example"
_ID = re.compile(r"[a-z0-9][a-z0-9-]{0,62}")
_lock = threading.RLock()


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


@dataclass
class Project:
    id: str
    name: str
    path: str        # the folder, resolved
    db: str          # its database
    added: str
    opened: str | None = None


def valid_id(text: str) -> bool:
    return bool(_ID.fullmatch(text))


def _slug(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:50]
    return slug if valid_id(slug) and slug != EXAMPLE_ID else f"project-{slug}".strip("-")[:50] or "project"


class Projects:
    """The list of projects, on disk. Thread-safe within one process."""

    def __init__(self) -> None:
        self.home = flowforge_home()
        self.path = self.home / "projects.json"

    def _load(self) -> list[Project]:
        try:
            raw = json.loads(self.path.read_text())
        except (OSError, ValueError):
            return []
        out = []
        for item in raw if isinstance(raw, list) else []:
            try:
                out.append(Project(**{k: item.get(k) for k in Project.__dataclass_fields__}))
            except TypeError:
                continue
        return [p for p in out if p.id and p.path and p.db]

    def _save(self, projects: list[Project]) -> None:
        self.home.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name("projects.json.tmp")
        tmp.write_text(json.dumps([asdict(p) for p in projects], indent=2))
        tmp.replace(self.path)

    def list(self) -> list[Project]:
        return self._load()

    def get(self, project_id: str) -> Project | None:
        return next((p for p in self._load() if p.id == project_id), None)

    def find(self, id_or_name: str) -> Project | None:
        """By id, else by name (ignoring case)."""
        found = self._load()
        return next((p for p in found if p.id == id_or_name), None) or \
            next((p for p in found if p.name.lower() == id_or_name.lower()), None)

    def by_folder(self, folder: Path) -> Project | None:
        here = str(Path(folder).expanduser().resolve())
        return next((p for p in self._load() if p.path == here), None)

    def for_folder(self, folder: Path) -> Project | None:
        """The project whose folder holds `folder` (the deepest one), e.g. where a coding agent works."""
        here = Path(folder).expanduser().resolve()
        holders = [p for p in self._load() if here == Path(p.path) or Path(p.path) in here.parents]
        return max(holders, key=lambda p: len(p.path), default=None)

    def add(self, folder: Path, db: Path | None = None, name: str | None = None) -> Project:
        """The folder's project, added if new. A new project gets its own database unless `db` is given (a database
        that already maps this folder: D39's migration)."""
        with _lock:
            here = Path(folder).expanduser().resolve()
            found = self._load()
            existing = next((p for p in found if p.path == str(here)), None)
            if existing:
                return existing
            base, taken = _slug(here.name or "project"), {p.id for p in found}
            pid, n = base, 2
            while pid in taken or pid == EXAMPLE_ID:
                pid, n = f"{base}-{n}", n + 1
            project = Project(id=pid, name=name or here.name or pid, path=str(here),
                              db=str((db or self.home / "projects" / f"{pid}.db").expanduser().resolve()),
                              added=now())
            self._save([*found, project])
            return project

    def touch(self, project_id: str) -> None:
        with _lock:
            found = self._load()
            for p in found:
                if p.id == project_id:
                    p.opened = now()
            self._save(found)

    def rename(self, project_id: str, name: str) -> Project | None:
        with _lock:
            found = self._load()
            hit = next((p for p in found if p.id == project_id), None)
            if hit:
                hit.name = name.strip()[:80] or hit.name
                self._save(found)
            return hit

    def remove(self, project_id: str) -> Project | None:
        with _lock:
            found = self._load()
            hit = next((p for p in found if p.id == project_id), None)
            if hit:
                self._save([p for p in found if p.id != project_id])
            return hit
