"""The lock on the key view (D37): a password and the code from an authenticator app (RFC 6238 TOTP: SHA-1, 30 s,
6 digits), so only the person with both can see a key's value. A coding agent on this machine has no phone.

`FLOWFORGE_HOME/lock.json` (0600) holds a scrypt hash of the password and the phone's secret sealed with a key derived
from the password, never either in the clear. Wrong tries lock the view; a code works once; sessions live only in
this process and end after five minutes. `forget()` (a reset without the password) leaves a mark the dashboard shows.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import struct
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Literal
from urllib.parse import quote

from flowforge.home import flowforge_home
from flowforge.security.keystore import _write_private

STEP_S = 30
DIGITS = 6
SESSION_S = 300
MAX_TRIES = 5
LOCKOUT_S = 15 * 60
MIN_PASSWORD = 8
_SCRYPT = {"n": 2 ** 14, "r": 8, "p": 1, "dklen": 32}

State = Literal["none", "pending", "on"]

_SESSIONS: dict[str, float] = {}   # token -> when it ends; this process only, never on disk
_lock = threading.RLock()


class LockError(Exception):
    """Why the lock said no, in one sentence for the page."""


def totp(secret: bytes, at: float, step: int = STEP_S, digits: int = DIGITS) -> str:
    """RFC 6238: the code for the time step that holds `at`."""
    return _code(secret, int(at // step), digits)


def _code(secret: bytes, counter: int, digits: int = DIGITS) -> str:
    digest = hmac.new(secret, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    number = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return str(number % 10 ** digits).zfill(digits)


def _scrypt(password: str, salt: bytes) -> bytes:
    return hashlib.scrypt(password.encode(), salt=salt, **_SCRYPT)


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode()


def _unb64(text: str) -> bytes:
    return base64.b64decode(text)


class Lock:
    def __init__(self, clock: Callable[[], float] = time.time, sessions: dict[str, float] | None = None) -> None:
        self.clock = clock
        self.sessions = _SESSIONS if sessions is None else sessions
        self.home = flowforge_home()

    # the lock file and the events log

    @property
    def _path(self):
        return self.home / "lock.json"

    def _read(self) -> dict[str, Any] | None:
        """The lock file; None when there is none. A damaged file reads as on and unopenable, never as none:
        "none" would let anyone set a new lock without a word."""
        if not self._path.exists():
            return None
        try:
            data = json.loads(self._path.read_text())
            return data if isinstance(data, dict) and data.get("state") in ("pending", "on") else {"state": "damaged"}
        except (OSError, ValueError):
            return {"state": "damaged"}

    def _write(self, data: dict[str, Any]) -> None:
        _write_private(self._path, json.dumps(data, indent=2).encode())

    def _event(self, what: str) -> None:
        line = json.dumps({"at": datetime.now(UTC).isoformat(timespec="seconds"), "event": what}) + "\n"
        path = self.home / "lock-events.log"
        old = path.read_bytes() if path.exists() else b""
        _write_private(path, old + line.encode())

    def _events(self) -> list[dict[str, str]]:
        path = self.home / "lock-events.log"
        out = []
        for line in path.read_text().splitlines() if path.exists() else []:
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
        return out

    # what callers use

    def state(self) -> State:
        data = self._read()
        if data is None:
            return "none"
        return "pending" if data["state"] == "pending" else "on"

    def setup(self, password: str) -> str:
        """Start the lock: returns the otpauth:// address for the phone (shown once, as a QR). The lock is on only
        after the first code (`confirm`)."""
        with _lock:
            if self.state() == "on":
                raise LockError("The key view lock is already on. Reset it first to set a new one.")
            if len(password) < MIN_PASSWORD:
                raise LockError(f"Use a password of at least {MIN_PASSWORD} characters.")
            secret = secrets.token_bytes(20)
            pw_salt, key_salt = secrets.token_bytes(16), secrets.token_bytes(16)
            from cryptography.fernet import Fernet

            sealed = Fernet(base64.urlsafe_b64encode(_scrypt(password, key_salt))).encrypt(secret)
            self._write({"version": 1, "state": "pending", "password_salt": _b64(pw_salt),
                         "password_hash": _b64(_scrypt(password, pw_salt)), "key_salt": _b64(key_salt),
                         "secret_sealed": sealed.decode(), "last_step": None, "failures": 0, "locked_until": 0,
                         "made": datetime.now(UTC).isoformat(timespec="seconds")})
            label = quote("FlowForge:key view", safe=":")
            code = base64.b32encode(secret).decode().rstrip("=")
            return f"otpauth://totp/{label}?secret={code}&issuer=FlowForge&algorithm=SHA1&digits={DIGITS}&period={STEP_S}"

    def _check(self, password: str, code: str) -> dict[str, Any]:
        """Password and code both right, within the attempts left; the code's step can't be used again. Raises
        LockError with the same words for any wrong part, so a try tells nothing about which was wrong."""
        data = self._read()
        if data is None:
            raise LockError("The key view has no lock yet: set one up first.")
        if data["state"] == "damaged":
            raise LockError("The lock file can't be read: reset it with `flowforge lock reset --forget`.")
        now = self.clock()
        if data.get("locked_until", 0) > now:
            minutes = int((data["locked_until"] - now) // 60) + 1
            raise LockError(f"Locked after {MAX_TRIES} wrong tries: try again in {minutes} min.")
        step = self._match(data, password, code, now)
        if step is None:
            data["failures"] = data.get("failures", 0) + 1
            if data["failures"] >= MAX_TRIES:
                data["failures"], data["locked_until"] = 0, now + LOCKOUT_S
            self._write(data)
            raise LockError("Wrong password or code.")
        data.update(failures=0, locked_until=0, last_step=step)
        self._write(data)
        return data

    def _match(self, data: dict[str, Any], password: str, code: str, now: float) -> int | None:
        """The time step the code belongs to (this one or the one before or after), or None."""
        try:
            salt, want = _unb64(data["password_salt"]), _unb64(data["password_hash"])
            if not hmac.compare_digest(_scrypt(password, salt), want):
                return None
            from cryptography.fernet import Fernet, InvalidToken

            key = base64.urlsafe_b64encode(_scrypt(password, _unb64(data["key_salt"])))
            secret = Fernet(key).decrypt(data["secret_sealed"].encode())
        except (KeyError, ValueError, InvalidToken):
            return None
        code = code.strip().replace(" ", "")
        here, last = int(now // STEP_S), data.get("last_step")
        for step in (here - 1, here, here + 1):
            if (last is None or step > last) and hmac.compare_digest(_code(secret, step), code):
                return step
        return None

    def confirm(self, password: str, code: str) -> None:
        """The first code from the phone: the lock is on."""
        with _lock:
            data = self._check(password, code)
            data["state"] = "on"
            self._write(data)

    def open(self, password: str, code: str) -> str:
        """Open the key view for five minutes: a session token, kept in this process only."""
        with _lock:
            if self.state() == "pending":
                raise LockError("Finish setting up the lock first: type the code your phone shows.")
            self._check(password, code)
            token = secrets.token_urlsafe(32)
            now = self.clock()
            for t in [t for t, end in self.sessions.items() if end <= now]:   # ended ones
                del self.sessions[t]
            self.sessions[token] = now + SESSION_S
            self._event("opened")
            return token

    def valid(self, token: str | None) -> bool:
        return bool(token) and self.sessions.get(token, 0) > self.clock()

    def seconds_left(self, token: str | None) -> int:
        return max(0, int(self.sessions.get(token or "", 0) - self.clock())) if self.valid(token) else 0

    def close(self, token: str | None) -> None:
        self.sessions.pop(token or "", None)

    def reset(self, password: str, code: str) -> None:
        """Turn the lock off with the password and a code. Saved keys stay."""
        with _lock:
            self._check(password, code)
            self._path.unlink(missing_ok=True)
            self.sessions.clear()
            self._event("reset")

    def forget(self) -> None:
        """Drop the lock without the password (it was forgotten). Saved keys stay. The dashboard shows that this
        happened until the next unlock, in case it wasn't you."""
        with _lock:
            self._path.unlink(missing_ok=True)
            self.sessions.clear()
            self._event("forgotten")

    def reset_at(self) -> str | None:
        """When the lock was last dropped without its password, unless it has been opened since."""
        for e in reversed(self._events()):
            if e.get("event") == "opened":
                return None
            if e.get("event") == "forgotten":
                return e.get("at")
        return None

