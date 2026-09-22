import httpx
import pytest

from flowforge.nodes import NodeError, TransientNodeError
from flowforge.nodes.base import parse_retry_after
from flowforge.nodes.http_node import HTTPNode, html_to_text


def node_returning(response_fn):
    return HTTPNode(httpx.AsyncClient(transport=httpx.MockTransport(response_fn)))


async def test_json_body():
    node = node_returning(lambda req: httpx.Response(200, json={"ok": True}))
    assert await node.run({"url": "https://x/api"}) == {"status": 200, "body": {"ok": True}}


async def test_html_is_reduced_to_text_and_truncated():
    html = "<html><head><title>t</title><script>var junk=1</script></head><body><h1>Charges</h1><p>Create a charge.</p></body></html>"
    node = node_returning(lambda req: httpx.Response(200, text=html, headers={"content-type": "text/html"}))
    out = await node.run({"url": "https://x/docs"})
    assert out["body"] == "Charges\nCreate a charge." and "junk" not in out["body"]
    assert (await node.run({"url": "https://x/docs", "max_chars": 7}))["body"] == "Charges"
    raw = await node.run({"url": "https://x/docs", "extract_text": False})
    assert raw["body"].startswith("<html>")


@pytest.mark.parametrize("status", [429, 500, 503])
async def test_transient_statuses(status):
    node = node_returning(lambda req: httpx.Response(status, headers={"retry-after": "2"}))
    with pytest.raises(TransientNodeError) as exc:
        await node.run({"url": "https://x"})
    assert exc.value.retry_after_s == 2


async def test_client_errors_are_permanent():
    node = node_returning(lambda req: httpx.Response(404, text="nope"))
    with pytest.raises(NodeError) as exc:
        await node.run({"url": "https://x"})
    assert not isinstance(exc.value, TransientNodeError)


async def test_connection_error_is_transient():
    def fail(req):
        raise httpx.ConnectError("refused")

    with pytest.raises(TransientNodeError):
        await node_returning(fail).run({"url": "https://x"})


async def test_post_json_sent():
    seen = {}

    def handler(req):
        seen["method"], seen["body"] = req.method, req.content
        return httpx.Response(201, json={})

    await node_returning(handler).run({"method": "post", "url": "https://x", "json": {"a": 1}})
    assert seen == {"method": "POST", "body": b'{"a":1}'}


def test_cache_policy():
    assert HTTPNode().cacheable_across_runs({"url": "u"})
    assert not HTTPNode().cacheable_across_runs({"url": "u", "method": "POST"})


def test_parse_retry_after():
    assert parse_retry_after("5") == 5 and parse_retry_after(None) is None
    assert parse_retry_after("Wed, 21 Oct 2015 07:28:00 GMT") == 0  # in the past
    assert parse_retry_after("garbage") is None


def test_html_to_text_handles_entities():
    assert html_to_text("<p>a &amp; b</p><p>c</p>") == "a & b\nc"
