"""The agent's app runs (D43): plain code doing what you would do by hand. A command (a list, never a shell) starts in
the project's folder with the project's keys filled in (`security/masks.py`); its output is kept masked by the
redactor, which knows every saved value. Runs live in FlowForge's process and stop when it does."""

from __future__ import annotations

import os
import subprocess
import threading
import time
import uuid
from collections import deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

from flowforge.security.masks import fill, masks_in

KEEP_LINES = 2000
STOP_WAIT_S = 5


@dataclass
class AppRun:
    id: str
    project: str
    argv: list[str]            # as the agent wrote it: masks, never values
    keys: list[str]            # the names given to the app, never values
    cwd: str
    started: float = field(default_factory=time.time)
    status: str = "running"    # running · exited · stopped · failed
    code: int | None = None
    ended: float | None = None
    _lines: deque = field(default_factory=lambda: deque(maxlen=KEEP_LINES), repr=False)
    _seq: int = 0
    _proc: subprocess.Popen | None = field(default=None, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def add(self, line: str) -> None:
        with self._lock:
            self._seq += 1
            self._lines.append((self._seq, line))

    def output(self, since: int = 0) -> list[tuple[int, str]]:
        """Masked lines after `since`, oldest first."""
        with self._lock:
            return [(n, line) for n, line in self._lines if n > since]

    def summary(self) -> dict[str, object]:
        return {"id": self.id, "argv": self.argv, "keys": self.keys, "status": self.status, "code": self.code,
                "started": self.started, "ended": self.ended}


class Runs:
    """Every app run in this FlowForge, by id."""

    def __init__(self) -> None:
        self._runs: dict[str, AppRun] = {}
        self._lock = threading.Lock()

    def start(self, project: str, argv: list[str], cwd: Path, values: Mapping[str, str],
              redact: Callable[[str], str]) -> AppRun:
        """Start `argv` with the keys filled in. Raises MissingKeys, before anything starts, for a mask whose key
        isn't saved."""
        command, env = fill(argv, dict(os.environ), values)
        named = masks_in(argv, {})
        run = AppRun(id=uuid.uuid4().hex[:12], project=project, argv=list(argv),
                     keys=sorted(set(values) | named), cwd=str(cwd))
        with self._lock:
            self._runs[run.id] = run
        try:
            run._proc = subprocess.Popen(command, cwd=cwd, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                         stderr=subprocess.STDOUT, text=True, errors="replace", bufsize=1)
        except OSError as e:
            run.status, run.ended = "failed", time.time()
            run.add(redact(f"FlowForge couldn't start it: {argv[0]} not found ({e.strerror})"
                           if isinstance(e, FileNotFoundError) else f"FlowForge couldn't start it: {e.strerror}"))
            return run
        threading.Thread(target=self._read, args=(run, redact), name=f"app-{run.id}", daemon=True).start()
        return run

    @staticmethod
    def _read(run: AppRun, redact: Callable[[str], str]) -> None:
        proc = run._proc
        assert proc is not None and proc.stdout is not None
        for line in proc.stdout:
            run.add(redact(line.rstrip("\r\n")))
        run.code = proc.wait()
        run.ended = time.time()
        if run.status == "running":
            run.status = "exited"

    def get(self, run_id: str) -> AppRun | None:
        with self._lock:
            return self._runs.get(run_id)

    def list(self, project: str) -> list[AppRun]:
        with self._lock:
            return sorted((r for r in self._runs.values() if r.project == project), key=lambda r: -r.started)

    def stop(self, run_id: str) -> bool:
        run = self.get(run_id)
        if run is None or run._proc is None or run.status != "running":
            return False
        run.status = "stopped"
        run._proc.terminate()
        try:
            run._proc.wait(timeout=STOP_WAIT_S)
        except subprocess.TimeoutExpired:
            run._proc.kill()
        return True

    def stop_all(self) -> None:
        with self._lock:
            running = [r.id for r in self._runs.values() if r.status == "running"]
        for run_id in running:
            self.stop(run_id)
