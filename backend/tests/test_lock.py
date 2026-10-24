"""The lock on the key view (D37): a password and an authenticator code (RFC 6238). The phone's secret is stored only
encrypted by the password; wrong tries lock it; a code works once; sessions end; a forced reset leaves a mark."""

import base64
import json
from urllib.parse import parse_qs, urlparse

import pytest

from flowforge.security import lock as lock_module
from flowforge.security.lock import Lock, LockError, totp

RFC_SECRET = b"12345678901234567890"   # RFC 6238 appendix B, SHA-1


@pytest.mark.parametrize("at, code", [(59, "287082"), (1111111109, "081804"), (1111111111, "050471"),
                                      (1234567890, "005924"), (2000000000, "279037")])
def test_totp_matches_the_rfc_6238_test_vectors(at, code):
    assert totp(RFC_SECRET, at) == code


class Clock:
    def __init__(self, at: float = 1_700_000_000.0):
        self.at = at

    def __call__(self) -> float:
        return self.at


def secret_of(uri: str) -> bytes:
    raw = parse_qs(urlparse(uri).query)["secret"][0]
    return base64.b32decode(raw + "=" * (-len(raw) % 8))


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def lock(clock):
    return Lock(clock=clock)


def turned_on(lock: Lock, clock: Clock, password: str = "correct horse") -> bytes:
    secret = secret_of(lock.setup(password))
    lock.confirm(password, totp(secret, clock()))
    clock.at += 60   # two steps on: the code used to turn it on works once, and the step before is unused
    return secret


def test_set_up_shows_a_secret_once_and_the_first_code_turns_it_on(lock, clock):
    assert lock.state() == "none"
    uri = lock.setup("correct horse")
    assert uri.startswith("otpauth://totp/FlowForge:") and "issuer=FlowForge" in uri
    assert lock.state() == "pending"
    with pytest.raises(LockError):
        lock.confirm("correct horse", "000000")
    lock.confirm("correct horse", totp(secret_of(uri), clock()))
    assert lock.state() == "on"
    with pytest.raises(LockError, match="already on"):
        lock.setup("another password")


def test_a_short_password_is_refused(lock):
    with pytest.raises(LockError, match="8"):
        lock.setup("short")


def test_nothing_on_disk_holds_the_phone_secret_or_the_password_in_the_clear(lock, clock):
    secret = turned_on(lock, clock)
    raw = (lock_module.flowforge_home() / "lock.json").read_bytes()
    assert b"correct horse" not in raw
    assert base64.b32encode(secret).rstrip(b"=") not in raw and secret not in raw
    assert set(json.loads(raw)) >= {"password_hash", "secret_sealed"}


def test_open_needs_both_the_password_and_the_current_code(lock, clock):
    secret = turned_on(lock, clock)
    with pytest.raises(LockError):
        lock.open("wrong password", totp(secret, clock()))
    with pytest.raises(LockError):
        lock.open("correct horse", "123456")
    token = lock.open("correct horse", totp(secret, clock()))
    assert lock.valid(token) and not lock.valid("made-up")


def test_a_code_from_the_step_before_works_but_not_twice(lock, clock):
    secret = turned_on(lock, clock)
    earlier = totp(secret, clock() - 30)
    assert lock.valid(lock.open("correct horse", earlier))
    with pytest.raises(LockError):
        lock.open("correct horse", earlier)            # used already
    with pytest.raises(LockError):
        lock.open("correct horse", totp(secret, clock() - 90))   # too old


def test_five_wrong_tries_lock_it_for_fifteen_minutes(lock, clock):
    secret = turned_on(lock, clock)
    for _ in range(5):
        with pytest.raises(LockError):
            lock.open("correct horse", "000000")
    with pytest.raises(LockError, match="Locked"):
        lock.open("correct horse", totp(secret, clock()))   # even the right code
    clock.at += 15 * 60 + 1
    assert lock.valid(lock.open("correct horse", totp(secret, clock())))


def test_a_session_ends_after_five_minutes_or_when_closed(lock, clock):
    secret = turned_on(lock, clock)
    token = lock.open("correct horse", totp(secret, clock()))
    assert 290 < lock.seconds_left(token) <= 300
    clock.at += 301
    assert not lock.valid(token)
    clock.at += 30
    token = lock.open("correct horse", totp(secret, clock()))
    lock.close(token)
    assert not lock.valid(token)


def test_sessions_live_in_this_process_only(lock, clock):
    secret = turned_on(lock, clock)
    token = lock.open("correct horse", totp(secret, clock()))
    assert token not in (lock_module.flowforge_home() / "lock.json").read_text()
    assert not Lock(clock=clock, sessions={}).valid(token)


def test_reset_with_password_and_code_turns_it_off(lock, clock):
    secret = turned_on(lock, clock)
    with pytest.raises(LockError):
        lock.reset("wrong password", totp(secret, clock()))
    lock.reset("correct horse", totp(secret, clock()))
    assert lock.state() == "none" and lock.reset_at() is None


def test_a_forced_reset_leaves_a_mark_until_the_next_unlock(lock, clock):
    turned_on(lock, clock)
    lock.forget()
    assert lock.state() == "none"
    assert lock.reset_at() is not None             # the dashboard shows "Key view was reset at …"
    secret = turned_on(lock, clock, "a new password")
    assert lock.reset_at() is not None             # still shown: setting up again isn't proof it was you
    lock.open("a new password", totp(secret, clock()))
    assert lock.reset_at() is None


def test_a_damaged_lock_file_is_treated_as_on_and_unopenable(lock, clock):
    turned_on(lock, clock)
    (lock_module.flowforge_home() / "lock.json").write_text("{not json")
    assert lock.state() == "on"                    # never "none": that would let anyone set a new lock silently
    with pytest.raises(LockError, match="reset"):
        lock.open("correct horse", "000000")
