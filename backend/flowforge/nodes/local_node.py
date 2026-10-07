"""Local command step (D13). The connector fixes the program and the folder; the step adds arguments.

params: args (list[str], appended to the connector's command), stdin? (str),
        subdir? (str, must stay inside the connector's cwd), ok_exit_codes? (default [0])
output: {"kind": "text", "stdout": str, "stderr": str, "exit_code": int}

Safety rules, all enforced here:
  - no shell: the program starts from an argv list; step values are separate arguments,
    never pasted into a command string. .bat/.cmd are refused, because Windows runs them
    through cmd.exe, which would bring shell parsing back
  - subdir is resolved (`..`, symlinks) and must stay inside cwd
  - the environment is explicit: connector env + resolved env_refs + the minimum the OS
    needs to start a program; nothing else is inherited
  - on timeout or cancellation (the executor's wait_for) the process is killed and reaped
  - stdout/stderr are capped at max_output_bytes; the rest is read and discarded
An exit code outside ok_exit_codes is a permanent error. Never cached across runs by default.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import sys
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

from flowforge.connectors.models import LocalConnector
from flowforge.connectors.secrets import SecretRefError, resolve_env
from flowforge.nodes.base import Node, NodeError

# What a process needs to start at all; everything else must be configured explicitly.
_OS_ENV = ("PATH", "SYSTEMROOT", "TEMP", "TMP") if sys.platform == "win32" else ("PATH",)
_SHELL_SCRIPTS = {".bat", ".cmd"}
_CHUNK = 64 * 1024


class LocalNode(Node):
    type = "local"

    def __init__(self, connector: LocalConnector) -> None:
        self.connector = connector
        self.connector_id = connector.id
        self.rate_limit_key = connector.id
        self.fallback = connector.fallback

    @classmethod
    def from_connector(cls, connector: LocalConnector) -> LocalNode:
        return cls(connector)

    @property
    def _label(self) -> str:
        return f"local '{self.connector.id}'"

    def _env(self) -> dict[str, str]:
        conn = self.connector.connection
        env = {name: os.environ[name] for name in _OS_ENV if name in os.environ}
        try:
            env.update(resolve_env(conn.env, conn.env_refs))
        except SecretRefError as exc:
            raise NodeError(f"{self._label}: {exc}") from exc
        return env

    def _workdir(self, subdir: Any) -> Path:
        base = Path(self.connector.connection.cwd).resolve()
        if not base.is_dir():
            raise NodeError(f"{self._label}: working folder {base} does not exist")
        if subdir is None:
            return base
        if not isinstance(subdir, str):
            raise NodeError(f"{self._label}: params.subdir must be a string")
        # reject absolute or drive paths of either platform before joining
        win, posix = PureWindowsPath(subdir), PurePosixPath(subdir)
        if win.is_absolute() or win.drive or win.root or posix.is_absolute():
            raise NodeError(f"{self._label}: subdir '{subdir}' is outside the connector's folder")
        target = (base / subdir).resolve()
        if not target.is_relative_to(base):
            raise NodeError(f"{self._label}: subdir '{subdir}' is outside the connector's folder")
        if not target.is_dir():
            raise NodeError(f"{self._label}: subdir '{subdir}' does not exist")
        return target

    def _program(self, env: dict[str, str]) -> str:
        name = self.connector.connection.command[0]
        if os.path.dirname(name):
            program = name if Path(name).is_file() else None
        else:
            program = shutil.which(name, path=env.get("PATH", ""))
        if program is None:
            raise NodeError(f"{self._label}: program '{name}' not found")
        if Path(program).suffix.lower() in _SHELL_SCRIPTS:
            raise NodeError(f"{self._label}: '{name}' is a batch script, which Windows runs through cmd.exe "
                            "(shell parsing); point the connector at the real program instead")
        return program

    async def run(self, params: dict[str, Any]) -> Any:
        args = params.get("args", [])
        if not isinstance(args, list) or not all(isinstance(a, str) for a in args):
            raise NodeError(f"{self._label}: params.args must be a list of strings")
        stdin = params.get("stdin")
        if stdin is not None and not isinstance(stdin, str):
            raise NodeError(f"{self._label}: params.stdin must be a string")
        ok_codes = params.get("ok_exit_codes", [0])
        cwd = self._workdir(params.get("subdir"))
        env = self._env()
        program = self._program(env)
        cap = self.connector.connection.max_output_bytes

        try:
            proc = await asyncio.create_subprocess_exec(
                program, *self.connector.connection.command[1:], *args,
                cwd=cwd, env=env,
                stdin=asyncio.subprocess.PIPE if stdin is not None else asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
        except OSError as exc:
            raise NodeError(f"{self._label}: could not start '{program}': {exc}") from exc

        try:
            (out, out_cut), (err, err_cut), _ = await asyncio.gather(
                _read_capped(proc.stdout, cap), _read_capped(proc.stderr, cap), _feed(proc, stdin)
            )
            code = await proc.wait()
        except BaseException:  # timeout/cancellation from the executor, or anything else
            if proc.returncode is None:
                proc.kill()
                await proc.wait()
            raise

        stdout, stderr = _text(out, out_cut, cap), _text(err, err_cut, cap)
        if code not in ok_codes:
            raise NodeError(f"{self._label}: exit code {code}: {stderr[-500:].strip()}")
        return {"kind": "text", "stdout": stdout, "stderr": stderr, "exit_code": code}


async def _read_capped(stream: asyncio.StreamReader | None, cap: int) -> tuple[bytes, bool]:
    """Keep the first `cap` bytes; keep reading (and discarding) so the child never blocks."""
    kept = bytearray()
    truncated = False
    if stream is None:
        return b"", False
    while chunk := await stream.read(_CHUNK):
        room = cap - len(kept)
        if len(chunk) > room:
            truncated = True
        if room > 0:
            kept += chunk[:room]
    return bytes(kept), truncated


async def _feed(proc: asyncio.subprocess.Process, data: str | None) -> None:
    if data is None or proc.stdin is None:
        return
    try:
        proc.stdin.write(data.encode())
        await proc.stdin.drain()
        proc.stdin.close()
    except (BrokenPipeError, ConnectionResetError):
        pass  # the program exited without reading all of it


def _text(data: bytes, truncated: bool, cap: int) -> str:
    text = data.decode("utf-8", errors="replace")
    return text + f"\n[output truncated at {cap} bytes]" if truncated else text
