"""The key view through the API (D37): set up the lock, open it with a password and a code, list the keys, reveal one
at a time. No session, no value; a value is never stored, logged or given to the agent. Fake keys only."""

import base64
import json
import logging
import textwrap
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient
from mcp import Client

from flowforge import main
from flowforge.agent import build_server
from flowforge.security.keystore import KeyStore
from flowforge.security.lock import totp
from flowforge.storage import Storage

FAKE = "sk_test_FAKEFAKE12345678"      # in code
SAVED = "rzp_test_FAKE1234567"         # saved in FlowForge
IN_ENV = "AIzaFAKEFAKEFAKEFAKEFAKE1234"  # in .env
LOCAL = "http://127.0.0.1:8000"
HERE = ("127.0.0.1", 50000)   # the caller's real address: this machine
PASSWORD = "correct horse battery"


@pytest.fixture
def shop(tmp_path, monkeypatch):
    root = tmp_path / "shop"
    root.mkdir()
    (root / "pay.py").write_text(textwrap.dedent(f"""\
        import os
        import httpx

        STRIPE_KEY = "{FAKE}"
        RAZORPAY = os.environ["RAZORPAY_KEY"]
    """))
    (root / ".env").write_text(f"GOOGLE_API_KEY={IN_ENV}\nOLLAMA_HOST=localhost\n")
    KeyStore(root).add("RAZORPAY_KEY", SAVED)
    monkeypatch.delenv("FLOWFORGE_EXAMPLE", raising=False)
    monkeypatch.setenv("FLOWFORGE_DB", str(tmp_path / "flowforge.db"))
    monkeypatch.setenv("FLOWFORGE_REPO", str(root))
    return root


def secret_of(uri: str) -> bytes:
    raw = parse_qs(urlparse(uri).query)["secret"][0]
    return base64.b32decode(raw + "=" * (-len(raw) % 8))


def set_up(c: TestClient) -> bytes:
    got = c.post("/lock/setup", json={"password": PASSWORD}).json()
    assert got["qr"].startswith("data:image/svg+xml;base64,")
    secret = secret_of(got["uri"])
    import time

    assert c.post("/lock/confirm", json={"password": PASSWORD, "code": totp(secret, time.time())}).json() == {"state": "on"}
    return secret


def unlocked(c: TestClient, secret: bytes) -> None:
    """Both steps (D38): the password, then the code."""
    import time

    first = c.post("/lock/password", json={"password": PASSWORD})
    assert first.status_code == 200 and first.json()["next"] == "code"
    assert "httponly" in first.headers["set-cookie"].lower()
    r = c.post("/lock/code", json={"code": totp(secret, time.time() + 30)})
    assert r.status_code == 200, r.text
    assert 290 < r.json()["seconds_left"] <= 300
    assert "httponly" in r.headers["set-cookie"].lower() and "samesite=strict" in r.headers["set-cookie"].lower()


def test_the_lock_starts_off_and_says_so(shop):
    with TestClient(main.app, base_url=LOCAL, client=HERE) as c:
        assert c.get("/lock").json() == {"state": "none", "open": False, "seconds_left": 0, "reset_at": None}
        assert c.get("/vault/keys").status_code == 401


def test_the_qr_is_an_image_a_browser_draws(shop):
    """An <img> only draws an SVG that names its namespace: the setup's QR showed as an empty box without it."""
    import xml.etree.ElementTree as ET

    with TestClient(main.app, base_url=LOCAL, client=HERE) as c:
        qr = c.post("/lock/setup", json={"password": PASSWORD}).json()["qr"]
    svg = ET.fromstring(base64.b64decode(qr.split(",", 1)[1]))
    assert svg.tag == "{http://www.w3.org/2000/svg}svg"
    assert svg.get("viewBox") or (svg.get("width") and svg.get("height"))
    assert svg.findall(".//{http://www.w3.org/2000/svg}path")   # the modules are drawn


def test_open_the_view_list_the_keys_and_reveal_one_at_a_time(shop):
    with TestClient(main.app, base_url=LOCAL, client=HERE) as c:
        secret = set_up(c)
        assert c.get("/vault/keys").status_code == 401             # set up isn't open
        unlocked(c, secret)
        listed = c.get("/vault/keys")
        assert listed.status_code == 200
        for value in (FAKE, SAVED, IN_ENV):
            assert value not in listed.text                          # the list holds no values
        rows = {r["name"]: r for r in listed.json()["keys"]}
        assert set(rows) == {"STRIPE_KEY", "RAZORPAY_KEY", "GOOGLE_API_KEY"}
        items = {(p["where"], name): p for name, r in rows.items() for p in r["places"]}
        assert set(items) == {("code", "STRIPE_KEY"), ("saved", "RAZORPAY_KEY"), ("env", "GOOGLE_API_KEY")}
        assert items[("code", "STRIPE_KEY")]["ref"] == "pay.py:4"
        for (where, name), value in {("code", "STRIPE_KEY"): FAKE, ("saved", "RAZORPAY_KEY"): SAVED,
                                     ("env", "GOOGLE_API_KEY"): IN_ENV}.items():
            r = c.post("/keys/reveal", json={"where": where, "name": name, "ref": items[(where, name)]["ref"]})
            assert r.status_code == 200 and r.json() == {"value": value}
            assert r.headers["cache-control"] == "no-store"
        assert c.post("/keys/reveal", json={"where": "saved", "name": "NOPE", "ref": None}).status_code == 404


def test_no_session_no_value(shop):
    with TestClient(main.app, base_url=LOCAL, client=HERE) as c:
        set_up(c)
        r = c.post("/keys/reveal", json={"where": "saved", "name": "RAZORPAY_KEY", "ref": None})
        assert r.status_code == 401 and SAVED not in r.text
        c.cookies.set("ff_keyview", "made-up-token")
        assert c.post("/keys/reveal", json={"where": "saved", "name": "RAZORPAY_KEY", "ref": None}).status_code == 401


def test_closing_ends_the_session(shop):
    with TestClient(main.app, base_url=LOCAL, client=HERE) as c:
        unlocked(c, set_up(c))
        assert c.get("/lock").json()["open"] is True
        c.post("/lock/close")
        assert c.get("/lock").json()["open"] is False
        assert c.get("/vault/keys").status_code == 401


def test_each_step_says_what_was_wrong_and_the_code_needs_step_one(shop):
    """D38: two screens, so each says which part was wrong; the code alone never opens the vault."""
    import time

    with TestClient(main.app, base_url=LOCAL, client=HERE) as c:
        secret = set_up(c)
        assert c.post("/lock/code", json={"code": totp(secret, time.time() + 30)}).status_code == 403   # no step 1
        wrong = c.post("/lock/password", json={"password": "not it at all"})
        assert wrong.status_code == 403 and "password" in wrong.json()["detail"].lower()
        c.post("/lock/password", json={"password": PASSWORD})
        bad = c.post("/lock/code", json={"code": "000000"})
        assert bad.status_code == 403 and "code" in bad.json()["detail"].lower()
        assert c.get("/vault/keys").status_code == 401


@pytest.mark.parametrize("path, body", [
    ("/lock/setup", {"password": PASSWORD}), ("/lock/password", {"password": PASSWORD}),
    ("/lock/code", {"code": "123456"}),
    ("/keys/reveal", {"where": "saved", "name": "RAZORPAY_KEY", "ref": None}),
])
def test_only_the_dashboard_on_this_machine_can_use_the_lock(shop, path, body):
    with TestClient(main.app, base_url=LOCAL, client=HERE) as c:
        assert c.post(path, json=body, headers={"host": "evil.test"}).status_code == 403
        assert c.post(path, json=body, headers={"origin": "http://evil.test"}).status_code == 403


def test_a_revealed_value_is_in_no_stored_row_and_no_log(shop, tmp_path, caplog):
    caplog.set_level(logging.DEBUG)
    with TestClient(main.app, base_url=LOCAL, client=HERE) as c:
        unlocked(c, set_up(c))
        for where, name in (("saved", "RAZORPAY_KEY"), ("env", "GOOGLE_API_KEY")):
            c.post("/keys/reveal", json={"where": where, "name": name, "ref": None})
    db = (tmp_path / "flowforge.db").read_bytes()
    for value in (SAVED, IN_ENV):
        assert value.encode() not in db and value not in caplog.text


async def test_the_agent_has_no_way_to_a_value(shop, tmp_path):
    async with Client(build_server(shop, Storage(tmp_path / "agent.db"))) as client:
        names = {t.name for t in (await client.list_tools()).tools}
        answers = [json.dumps((await client.call_tool(n, {})).content[0].text) for n in sorted(names - {"check_health"})]
    assert not any(word in n for n in names for word in ("reveal", "value", "lock", "unlock"))
    for value in (FAKE, SAVED, IN_ENV):
        assert all(value not in a for a in answers)


@pytest.mark.parametrize("path, body", [
    ("/lock/setup", {"password": PASSWORD}), ("/keys/reveal", {"where": "saved", "name": "RAZORPAY_KEY", "ref": None}),
])
def test_another_machine_is_refused_even_when_it_claims_to_be_localhost(shop, path, body):
    """Codex review (P1): with --host 0.0.0.0, Host and Origin can be faked; the caller's real address can't."""
    with TestClient(main.app, base_url="http://localhost:8000", client=("192.168.1.50", 40000)) as c:
        r = c.post(path, json=body, headers={"host": "localhost:8000", "origin": "http://localhost:8000"})
        assert r.status_code == 403
        assert c.put("/keys/A_KEY", json={"value": FAKE}, headers={"host": "localhost:8000"}).status_code == 403


@pytest.mark.parametrize("address, local", [("127.0.0.1", True), ("127.0.0.2", True), ("::1", True),
                                            ("::ffff:127.0.0.1", True), ("192.168.1.50", False), ("10.0.0.1", False),
                                            ("::ffff:192.168.1.50", False), ("testclient", False), (None, False)])
def test_what_counts_as_this_machine(address, local):
    from flowforge.api.keys import _loopback_peer

    assert _loopback_peer(address) is local
