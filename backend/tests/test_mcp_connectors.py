"""MCP connectors (D12): tool discovery, argument validation, non-text results, pre-run checks."""

import base64
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from mcp.server.mcpserver import MCPServer
from mcp.types import BlobResourceContents, EmbeddedResource, ImageContent, ResourceLink, TextContent

from flowforge import main
from flowforge.connectors.models import parse_connector
from flowforge.nodes import NodeError, TransientNodeError
from flowforge.nodes.base import current_run_id
from flowforge.nodes.mcp_node import INLINE_LIMIT_BYTES, MCPNode

FAKE_KEY = "sk_test_FAKEFAKE12345678"


def make_server(calls):
    server = MCPServer("fake-tools")

    @server.tool()
    def add(a: int, b: int) -> int:
        """Add two numbers."""
        calls.append("add")
        return a + b

    @server.tool()
    def shout(text: str) -> str:
        """Uppercase text."""
        return text.upper()

    @server.tool()
    def picture(size: int):
        """An image of `size` bytes plus a caption."""
        data = base64.b64encode(b"\x89PNG" + b"x" * (size - 4)).decode()
        return [TextContent(type="text", text="a picture"), ImageContent(type="image", data=data, mime_type="image/png")]

    @server.tool()
    def links():
        """A resource link and an embedded blob."""
        blob = base64.b64encode(b"%PDF-1.7 fake").decode()
        return [ResourceLink(type="resource_link", name="spec", uri="https://example.test/spec.md"),
                EmbeddedResource(type="resource", resource=BlobResourceContents(
                    uri="file:///report.pdf", mime_type="application/pdf", blob=blob))]

    return server


@pytest.fixture
async def node():
    calls = []
    n = MCPNode(servers={"tools": make_server(calls)})
    n.calls = calls
    yield n
    await n.aclose()


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("FLOWFORGE_HOME", str(tmp_path))
    return tmp_path


# --- discovery ---------------------------------------------------------------------------------

async def test_list_tools_returns_names_and_schemas(node):
    tools = {t["name"]: t for t in await node.list_tools("tools")}
    assert {"add", "shout", "picture", "links"} <= tools.keys()
    assert tools["add"]["description"] == "Add two numbers."
    assert set(tools["add"]["input_schema"]["required"]) == {"a", "b"}


# --- validation before the call ----------------------------------------------------------------

async def test_bad_arguments_rejected_before_calling(node):
    with pytest.raises(NodeError, match=r"arguments for tool 'add'.*'a'") as exc:
        await node.run({"server": "tools", "tool": "add", "arguments": {"a": "two", "b": 3}})
    assert not isinstance(exc.value, TransientNodeError)
    assert node.calls == []


async def test_missing_required_argument_rejected(node):
    with pytest.raises(NodeError, match="'b' is a required property"):
        await node.run({"server": "tools", "tool": "add", "arguments": {"a": 1}})
    assert node.calls == []


async def test_unknown_tool_lists_what_exists(node):
    with pytest.raises(NodeError, match=r"Unknown tool 'nope'.*add"):
        await node.run({"server": "tools", "tool": "nope"})


# --- non-text results --------------------------------------------------------------------------

async def test_small_image_is_inlined(node, home):
    out = await node.run({"server": "tools", "tool": "picture", "arguments": {"size": 100}})
    assert out["content"] == "a picture"
    [block] = out["blocks"]
    assert block["kind"] == "image" and block["mime"] == "image/png"
    assert len(base64.b64decode(block["data_b64"])) == 100
    assert not (home / "artifacts").exists()


async def test_large_image_is_written_as_an_artifact(node, home):
    token = current_run_id.set("run123")
    try:
        out = await node.run({"server": "tools", "tool": "picture", "arguments": {"size": INLINE_LIMIT_BYTES + 1}})
    finally:
        current_run_id.reset(token)
    [block] = out["blocks"]
    assert "data_b64" not in block and block["kind"] == "image"
    path = Path(block["path"])
    assert path.parent == home / "artifacts" / "run123" and path.suffix == ".png"
    assert path.read_bytes().startswith(b"\x89PNG") and path.stat().st_size == INLINE_LIMIT_BYTES + 1


async def test_resource_link_and_embedded_blob(node, home):
    out = await node.run({"server": "tools", "tool": "links"})
    link, blob = out["blocks"]
    assert link == {"kind": "resource", "uri": "https://example.test/spec.md", "name": "spec"}
    assert blob["kind"] == "file" and blob["mime"] == "application/pdf"
    assert base64.b64decode(blob["data_b64"]) == b"%PDF-1.7 fake"


async def test_text_only_results_keep_their_shape(node):
    out = await node.run({"server": "tools", "tool": "shout", "arguments": {"text": "a"}})
    assert set(out) == {"content", "structured"}


# --- connector form ----------------------------------------------------------------------------

def mcp_connector(**conn):
    return parse_connector({"id": "files", "type": "mcp", "name": "Files",
                            "connection": {"command": "uvx", "args": ["some-mcp"], **conn}})


def test_connector_resolves_secret_env_only_at_spawn(monkeypatch):
    monkeypatch.setenv("FILES_TOKEN", FAKE_KEY)
    node = MCPNode.from_connector(mcp_connector(env={"MODE": "test"}, env_refs={"API_TOKEN": "env:FILES_TOKEN"}))
    assert FAKE_KEY not in repr(vars(node))
    params = node._connector_server()
    assert (params.command, params.args) == ("uvx", ["some-mcp"])
    assert params.env == {"MODE": "test", "API_TOKEN": FAKE_KEY}
    assert (node.connector_id, node.cache_namespace) == ("files", "mcp:files")


async def test_connector_missing_secret_is_permanent(monkeypatch):
    monkeypatch.delenv("FILES_TOKEN", raising=False)
    node = MCPNode.from_connector(mcp_connector(env_refs={"API_TOKEN": "env:FILES_TOKEN"}))
    with pytest.raises(NodeError, match="FILES_TOKEN is not set") as exc:
        await node.run({"tool": "x"})
    assert not isinstance(exc.value, TransientNodeError)


async def test_connector_fixes_the_server():
    with pytest.raises(NodeError, match="fixes the server"):
        await MCPNode.from_connector(mcp_connector()).run({"server": ["evil"], "tool": "x"})


# --- API: pre-run checks and tool listing ------------------------------------------------------

@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setenv("FLOWFORGE_DB", str(tmp_path / "api.db"))
    with TestClient(main.app) as c:
        main.state.nodes["mcp"] = MCPNode(default_server=make_server([]))
        yield c


def mcp_wf(arguments, tool="add"):
    return {"id": "m", "steps": [{"id": "s", "type": "mcp", "params": {"tool": tool, "arguments": arguments}}]}


def test_validate_rejects_bad_literal_arguments(api):
    r = api.post("/validate", json=mcp_wf({"a": "two", "b": 1}))
    assert r.status_code == 422 and "step 's'" in r.json()["detail"] and "'a'" in r.json()["detail"]
    assert api.post("/validate", json=mcp_wf({}, tool="nope")).status_code == 422
    assert api.post("/runs", json=mcp_wf({"a": "two", "b": 1})).status_code == 422


def test_validate_accepts_good_arguments(api):
    body = api.post("/validate", json=mcp_wf({"a": 1, "b": 2})).json()
    assert body["ok"] and body["warnings"] == []


def test_templated_arguments_are_left_for_run_time(api):
    wf = {"id": "m", "steps": [
        {"id": "src", "type": "mock", "params": {"duration_ms": 1}},
        {"id": "s", "type": "mcp", "depends_on": ["src"],
         "params": {"tool": "add", "arguments": {"a": "{{steps.src.output.n}}", "b": 1}}}]}
    assert api.post("/validate", json=wf).status_code == 200


def test_unreachable_server_warns_instead_of_failing(api):
    main.state.nodes["mcp"] = MCPNode(default_server=["flowforge-no-such-mcp-binary"])
    body = api.post("/validate", json=mcp_wf({"a": 1, "b": 2})).json()
    assert body["ok"] and "could not reach" in body["warnings"][0]


def test_connector_tools_endpoint(api):
    main.state.nodes["tools"] = MCPNode(default_server=make_server([]))
    names = {t["name"] for t in api.get("/connectors/tools/tools").json()}
    assert {"add", "shout"} <= names
    assert api.get("/connectors/ghost/tools").status_code == 404
    assert api.get("/connectors/llm/tools").status_code == 422  # not an MCP connector
