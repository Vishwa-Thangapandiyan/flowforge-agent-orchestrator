"""HTTP connectors (D10): base URL, auth header from a secret ref, key never sent elsewhere."""

import base64

import httpx
import pytest

from flowforge.connectors.models import parse_connector
from flowforge.nodes import NodeError, TransientNodeError
from flowforge.nodes.http_node import HTTPNode

FAKE_STRIPE = "sk_test_FAKEFAKE12345678"
FAKE_RAZORPAY = "rzp_test_FAKE1234567:FAKESECRET"


def connector(scheme="bearer", **over):
    return parse_connector({"id": "stripe", "type": "http", "name": "Stripe", "mode": "test",
                            "connection": {"base_url": "https://api.stripe.test/v1",
                                           "auth_header": "Authorization", "auth_scheme": scheme},
                            "secret_ref": "env:STRIPE_SECRET_KEY", **over})


def recording_node(c, seen):
    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={"ok": True})
    return HTTPNode.from_connector(c, client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))


async def test_relative_url_joins_base_and_adds_bearer(monkeypatch):
    monkeypatch.setenv("STRIPE_SECRET_KEY", FAKE_STRIPE)
    seen = []
    out = await recording_node(connector(), seen).run({"url": "customers?limit=1"})
    assert out == {"status": 200, "body": {"ok": True}}
    assert str(seen[0].url) == "https://api.stripe.test/v1/customers?limit=1"
    assert seen[0].headers["authorization"] == f"Bearer {FAKE_STRIPE}"


async def test_basic_auth(monkeypatch):
    monkeypatch.setenv("RAZORPAY_KEY", FAKE_RAZORPAY)
    seen = []
    c = connector("basic", id="razorpay", secret_ref="env:RAZORPAY_KEY")
    await recording_node(c, seen).run({"url": "/orders"})
    assert seen[0].headers["authorization"] == "Basic " + base64.b64encode(FAKE_RAZORPAY.encode()).decode()


async def test_key_is_never_sent_to_another_origin(monkeypatch):
    monkeypatch.setenv("STRIPE_SECRET_KEY", FAKE_STRIPE)
    seen = []
    node = recording_node(connector(), seen)
    for url in ["https://evil.test/collect", "http://api.stripe.test/v1/x", "https://api.stripe.test.evil.test/v1",
                "//evil.test/x"]:
        with pytest.raises(NodeError, match="only sends its key to"):
            await node.run({"url": url})
    assert seen == []
    await node.run({"url": "https://api.stripe.test/v1/charges"})  # same origin is fine
    assert len(seen) == 1


async def test_step_headers_cannot_replace_the_auth_header(monkeypatch):
    monkeypatch.setenv("STRIPE_SECRET_KEY", FAKE_STRIPE)
    seen = []
    await recording_node(connector(), seen).run({"url": "x", "headers": {"authorization": "Bearer other"}})
    assert seen[0].headers.get_list("authorization") == [f"Bearer {FAKE_STRIPE}"]


async def test_missing_secret_is_permanent(monkeypatch):
    monkeypatch.delenv("STRIPE_SECRET_KEY", raising=False)
    with pytest.raises(NodeError, match="STRIPE_SECRET_KEY is not set") as exc:
        await recording_node(connector(), []).run({"url": "x"})
    assert not isinstance(exc.value, TransientNodeError)


async def test_errors_never_contain_the_key(monkeypatch):
    monkeypatch.setenv("STRIPE_SECRET_KEY", FAKE_STRIPE)
    node = HTTPNode.from_connector(connector(), client=httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(401, text=f"bad key {r.headers['authorization']}"))))
    with pytest.raises(NodeError) as exc:
        await node.run({"url": "x"})
    assert FAKE_STRIPE not in str(exc.value)


async def test_key_straddling_the_error_cut_is_still_redacted(monkeypatch):
    monkeypatch.setenv("STRIPE_SECRET_KEY", FAKE_STRIPE)
    body = "x" * 190 + FAKE_STRIPE  # the key starts 10 characters before the 200-character cut
    node = HTTPNode.from_connector(connector(), client=httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(400, text=body))))
    with pytest.raises(NodeError) as exc:
        await node.run({"url": "x"})
    assert FAKE_STRIPE[:10] not in str(exc.value)


def test_namespaces_and_keys():
    node = HTTPNode.from_connector(connector())
    assert (node.connector_id, node.cache_namespace, node.rate_limit_key) == ("stripe", "http:stripe", "stripe")
    assert node.cacheable_across_runs({"url": "x"}) and not node.cacheable_across_runs({"url": "x", "method": "POST"})
