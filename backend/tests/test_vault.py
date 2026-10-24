"""The open Vault's list (D38): every key with where it lives, what uses it, live or test, and its health. No value
in the list. Fake keys only."""

import json
import textwrap
import time
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from flowforge import main
from flowforge.security import keystore
from flowforge.security.keystore import KeyStore
from flowforge.security.lock import Lock, totp
from tests.test_key_view import secret_of

LOCAL, HERE = "http://127.0.0.1:8000", ("127.0.0.1", 50000)
LIVE = "sk_live_FAKEFAKE12345678"
TEST = "rzp_test_FAKE1234567"
OTHER = "AIzaFAKEFAKEFAKEFAKEFAKE1234"


@pytest.fixture
def shop(tmp_path, monkeypatch):
    root = tmp_path / "shop"
    root.mkdir()
    (root / "pay.py").write_text(textwrap.dedent(f"""\
        import os
        import httpx

        GOOGLE_KEY = "{OTHER}"
        STRIPE = os.environ["STRIPE_SECRET_KEY"]
        RAZORPAY = os.environ["RAZORPAY_KEY"]
        OPENAI = os.environ["OPENAI_API_KEY"]
        MISSING = os.environ["NOT_SAVED_TOKEN"]

        def pay():
            return httpx.post("https://api.stripe.com/v1/charges", headers={{"Authorization": STRIPE}})
    """))
    (root / ".env").write_text("OPENAI_API_KEY=sk-FAKEFAKEFAKEFAKEFAKE123\n")
    store = KeyStore(root)
    store.add("STRIPE_SECRET_KEY", LIVE)
    store.add("RAZORPAY_KEY", TEST)
    store.add("OLD_TOKEN", "plainvalue-FAKE-0000-1111")          # no code reads it
    entries = json.loads((keystore.flowforge_home() / "keys.json").read_text())
    old = (datetime.now(UTC) - timedelta(days=120)).isoformat(timespec="seconds")
    entries[str(root.resolve())]["RAZORPAY_KEY"]["added"] = old
    (keystore.flowforge_home() / "keys.json").write_text(json.dumps(entries))
    monkeypatch.delenv("FLOWFORGE_EXAMPLE", raising=False)
    monkeypatch.setenv("FLOWFORGE_DB", str(tmp_path / "flowforge.db"))
    monkeypatch.setenv("FLOWFORGE_REPO", str(root))
    return root


def opened(c: TestClient) -> None:
    lock = Lock()
    secret = secret_of(c.post("/lock/setup", json={"password": "correct horse"}).json()["uri"])
    c.post("/lock/confirm", json={"password": "correct horse", "code": totp(secret, time.time())})
    c.post("/lock/password", json={"password": "correct horse"})
    assert c.post("/lock/code", json={"code": totp(secret, time.time() + 30)}).status_code == 200
    assert lock.state() == "on"


def test_every_key_with_its_health_and_details_but_no_value(shop):
    with TestClient(main.app, base_url=LOCAL, client=HERE) as c:
        opened(c)
        got = c.get("/vault/keys")
    assert all(v not in got.text for v in (LIVE, TEST, OTHER, "plainvalue-FAKE", "sk-FAKEFAKE"))
    rows = {r["name"]: r for r in got.json()["keys"]}
    assert rows["STRIPE_SECRET_KEY"]["health"] == ["healthy"]
    assert rows["STRIPE_SECRET_KEY"]["kind"] == "live"
    assert rows["STRIPE_SECRET_KEY"]["deps"] == [{"id": "api-stripe", "name": "Stripe"}]
    assert rows["STRIPE_SECRET_KEY"]["places"] == [{"where": "saved", "ref": None, "store": "file"}]
    assert rows["RAZORPAY_KEY"]["kind"] == "test" and rows["RAZORPAY_KEY"]["health"] == ["120 days old"]
    assert rows["GOOGLE_KEY"]["health"] == ["in code"]
    assert rows["GOOGLE_KEY"]["places"] == [{"where": "code", "ref": "pay.py:4", "store": None}]
    assert rows["OPENAI_API_KEY"]["health"] == ["in .env"]
    assert rows["OLD_TOKEN"]["health"] == ["unused"]
    assert rows["NOT_SAVED_TOKEN"]["health"] == ["missing"] and rows["NOT_SAVED_TOKEN"]["places"] == []


def test_a_saved_key_that_cant_be_read_says_so(shop):
    KeyStore(shop)._file_path().write_bytes(b"damaged")
    with TestClient(main.app, base_url=LOCAL, client=HERE) as c:
        opened(c)
        rows = {r["name"]: r for r in c.get("/vault/keys").json()["keys"]}
    assert rows["STRIPE_SECRET_KEY"]["health"] == ["can't read"]
