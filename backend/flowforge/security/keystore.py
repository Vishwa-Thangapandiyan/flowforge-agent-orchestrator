"""Keys the coding agent never sees (D36).

A key goes in once (typed hidden, the dashboard's password box, or `.env` imported) and comes out only as the
environment of the app `flowforge run` starts, and as values the redactor masks. Values live in the OS keychain
(`keyring`), or in a Fernet-encrypted file in FLOWFORGE_HOME when no keychain works (§6.3). Keychains can't list
their entries, so `keys.json` keeps the names, never a value. Keys belong to one repo folder.
"""

from __future__ import annotations

import json
import os
import re
import threading
from collections.abc import Iterable
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Literal

from flowforge.home import flowforge_home
from flowforge.scan.models import ScanResult

Store = Literal["keychain", "file"]
Status = Literal["saved", "unreadable", "env_file", "missing"]

NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_lock = threading.RLock()   # the dashboard's routes run in a threadpool


class BadKey(ValueError):
    """A name that isn't an env var name, or a value an environment can't hold."""


def env_file_names(path: Path) -> list[str]:
    """The names a `.env` file sets, in order. Each value is dropped as soon as its line is parsed."""
    from dotenv import dotenv_values

    if not path.is_file():
        return []
    return [name for name in dotenv_values(path) if NAME.fullmatch(name)]


def _write_private(path: Path, data: bytes, mode: int = 0o600) -> None:
    """Write a file (only its owner can read it, by default), replacing it in one step. The temporary file has a new,
    unpredictable name and is created, never opened through a link someone planted (Codex review)."""
    import tempfile

    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def _keychain_works() -> bool:
    """Is there a keychain to use? `FLOWFORGE_KEYSTORE=file` says no, `=keychain` yes; otherwise ask keyring."""
    choice = os.getenv("FLOWFORGE_KEYSTORE", "auto").lower()
    if choice in ("file", "keychain"):
        return choice == "keychain"
    try:
        import keyring
        from keyring.backends import fail

        backend = keyring.get_keyring()
        return not isinstance(backend, fail.Keyring) and getattr(backend, "priority", 0) > 0
    except Exception:   # a broken keyring install means the file
        return False


class KeyStore:
    def __init__(self, repo: Path) -> None:
        self.repo = str(Path(repo).expanduser().resolve())
        self.home = flowforge_home()
        self.service = f"flowforge:{self.repo}"

    # names (keys.json): {repo: {name: {"store": "keychain" | "file", "added": iso}}}

    def _index(self) -> dict[str, dict[str, dict[str, str]]]:
        try:
            return json.loads((self.home / "keys.json").read_text())
        except (OSError, ValueError):
            return {}

    def _entries(self) -> dict[str, dict[str, str]]:
        return self._index().get(self.repo, {})

    def _save_entries(self, entries: dict[str, dict[str, str]]) -> None:
        index = self._index()
        if entries:
            index[self.repo] = entries
        else:
            index.pop(self.repo, None)
        _write_private(self.home / "keys.json", json.dumps(index, indent=2, sort_keys=True).encode())

    def names(self) -> list[str]:
        return sorted(self._entries())

    def saved(self) -> dict[str, dict[str, str]]:
        """Each saved name with where it went and when (no values): {name: {"store", "added"}}."""
        return {name: dict(entry) for name, entry in self._entries().items()}

    # the encrypted file: FLOWFORGE_HOME/keys/<repo hash>.enc holds {name: value}

    def _fernet(self):
        from cryptography.fernet import Fernet

        given = os.getenv("FLOWFORGE_MASTER_KEY")
        if given:
            return Fernet(given.encode())
        path = self.home / "master.key"
        if not path.is_file():
            _write_private(path, Fernet.generate_key())
        return Fernet(path.read_bytes().strip())

    def _file_path(self) -> Path:
        return self.home / "keys" / f"{sha256(self.repo.encode()).hexdigest()[:24]}.enc"

    def _file_values(self) -> dict[str, str]:
        path = self._file_path()
        if not path.is_file():
            return {}
        return json.loads(self._fernet().decrypt(path.read_bytes()))

    def _file_values_to_change(self) -> dict[str, str]:
        """The file's values before a change. A file that can't be read (damaged, or another master key) is moved
        aside, never overwritten, so the right master key could still open it; its keys stay listed as unreadable."""
        try:
            return self._file_values()
        except Exception:
            path = self._file_path()
            stamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
            aside, n = path.with_name(f"{path.name}.unreadable-{stamp}"), 1
            while aside.exists():   # never over an earlier one
                aside, n = path.with_name(f"{path.name}.unreadable-{stamp}{n}"), n + 1
            path.replace(aside)
            return {}

    def _save_file_values(self, values: dict[str, str]) -> None:
        if values:
            _write_private(self._file_path(), self._fernet().encrypt(json.dumps(values).encode()))
        else:
            self._file_path().unlink(missing_ok=True)

    # what callers use

    def add(self, name: str, value: str) -> Store:
        """Save one key; returns where it went. Saving a name again replaces its value."""
        value = value.strip()
        if not NAME.fullmatch(name):
            raise BadKey("A key's name is an env var name: letters, digits and _, not starting with a digit.")
        if not value or "\x00" in value:
            raise BadKey("The value is empty.")
        with _lock:
            self.remove(name)
            store: Store = "file"
            if _keychain_works():
                try:
                    import keyring

                    keyring.set_password(self.service, name, value)
                    store = "keychain"
                except Exception:   # locked or refused: the encrypted file instead
                    store = "file"
            if store == "file":
                self._save_file_values({**self._file_values_to_change(), name: value})
            entries = self._entries()
            entries[name] = {"store": store, "added": datetime.now(UTC).isoformat(timespec="seconds")}
            self._save_entries(entries)
            return store

    def remove(self, name: str) -> bool:
        with _lock:
            entries = self._entries()
            entry = entries.pop(name, None)
            if entry is None:
                return False
            if entry.get("store") == "keychain":
                try:
                    import keyring

                    keyring.delete_password(self.service, name)
                except Exception:   # already gone from the keychain
                    pass
            else:
                values = self._file_values_to_change()
                values.pop(name, None)
                self._save_file_values(values)
            self._save_entries(entries)
            return True

    def env(self) -> dict[str, str]:
        """Every saved value, by name. Only for `flowforge run` and the redactor: never an API, tool or page."""
        out: dict[str, str] = {}
        with _lock:
            entries = self._entries()
            from_file: dict[str, str] = {}
            if any(e.get("store") != "keychain" for e in entries.values()):
                try:
                    from_file = self._file_values()
                except Exception:   # a damaged file or a changed master key: those keys can't be read
                    from_file = {}
            for name, entry in entries.items():
                if entry.get("store") == "keychain":
                    try:
                        import keyring

                        value = keyring.get_password(self.service, name)
                    except Exception:
                        value = None
                else:
                    value = from_file.get(name)
                if value:
                    out[name] = value
        return out

    def status(self, names: Iterable[str], verify: bool = True) -> dict[str, Status]:
        """For each name: saved (in FlowForge, and readable when `verify`), unreadable (saved, but the keychain or the
        file won't give it back, so `flowforge run` can't pass it on), env_file (only named in the repo's .env) or
        missing. `verify=False` reads no value: the agent's MCP server (D36)."""
        saved = set(self._entries())
        readable = set(self.env()) if verify and saved else saved
        in_env_file = set(env_file_names(Path(self.repo) / ".env"))

        def one(n: str) -> Status:
            if n in saved:
                return "saved" if n in readable else "unreadable"
            return "env_file" if n in in_env_file else "missing"

        return {n: one(n) for n in names}

    def import_env(self, path: Path) -> list[str]:
        """Save every value a `.env` file sets; returns the names. The file stays: deleting it is the user's call."""
        from dotenv import dotenv_values

        saved = []
        for name, value in dotenv_values(path).items():
            if value and value.strip() and NAME.fullmatch(name):
                self.add(name, value)
                saved.append(name)
        return saved


def report(store: KeyStore, scan: ScanResult, verify: bool = True, also: Iterable[str] = ()) -> list[dict[str, object]]:
    """Each key the code reads (an env name that looks secret, D31), plus each saved one: its status, where it is
    read, the dependencies that use it, and the command that fixes it. Names only (D36). `verify=False` (the agent's
    MCP server) reports a saved key as saved without reading it back."""
    from flowforge.home import command_line
    from flowforge.security.finders import is_secret_name

    reads = {e.name: e.ref for e in scan.env_names if is_secret_name(e.name)}
    names = sorted({*reads, *store.names(), *also})   # `also`: names your agent asked for, not in the code yet
    status = store.status(names, verify=verify)
    out = []
    for name in names:
        command = None
        if status[name] in ("missing", "unreadable"):
            command = command_line("key", "add", name, "--repo", store.repo)
        elif status[name] == "env_file":
            command = command_line("key", "import", "--repo", store.repo)
        out.append({"name": name, "status": status[name], "ref": reads.get(name),
                    "deps": _users(name, reads.get(name), scan), "command": command})
    return out


# words in a key's name that say nothing about which service it is for
_GENERIC = {"api", "key", "keys", "secret", "token", "access", "private", "public", "client", "service", "role",
            "anon", "auth", "password", "passwd", "credential", "credentials", "app", "id", "the", "live", "test",
            "prod", "dev"}


def _users(name: str, ref: str | None, scan: ScanResult) -> list[str]:
    """The dependencies that use a key: those the scan saw reading it on their own lines; else those whose service
    the name names (STRIPE_SECRET_KEY → Stripe); else the only dependency in the file that reads it."""
    direct = [d.id for d in scan.dependencies if name in d.env_names]
    if direct:
        return direct
    words = {w for w in re.split(r"[^a-z0-9]+", name.lower()) if len(w) > 2 and w not in _GENERIC}
    named = [d.id for d in scan.dependencies
             if words & {w for w in re.split(r"[^a-z0-9]+", f"{d.catalog or ''} {d.name}".lower()) if w}]
    if named:
        return named
    path = ref.rsplit(":", 1)[0] if ref else None
    in_file = [d.id for d in scan.dependencies if any(e.ref.rsplit(":", 1)[0] == path for e in d.evidence)]
    return in_file if len(in_file) == 1 else []
