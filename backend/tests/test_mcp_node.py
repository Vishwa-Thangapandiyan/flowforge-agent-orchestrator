import pytest
from mcp.server.mcpserver import MCPServer

from flowforge.nodes import NodeError
from flowforge.nodes.mcp_node import MCPNode
from flowforge.nodes.mock_node import MockNode
from flowforge.schema import Workflow
from flowforge.scheduler.executor import run_workflow


def make_server():
    server = MCPServer("test-tools")

    @server.tool()
    def add(a: int, b: int) -> int:
        """Add two numbers."""
        return a + b

    @server.tool()
    def shout(text: str) -> str:
        """Uppercase text."""
        return text.upper()

    @server.tool()
    def broken() -> str:
        """Always fails."""
        raise ValueError("nope")

    return server


@pytest.fixture
async def node():
    n = MCPNode(servers={"tools": make_server()})
    yield n
    await n.aclose()


async def test_call_tool(node):
    out = await node.run({"server": "tools", "tool": "add", "arguments": {"a": 2, "b": 3}})
    assert out == {"content": "5", "structured": {"result": 5}}


async def test_connection_is_reused(node):
    await node.run({"server": "tools", "tool": "shout", "arguments": {"text": "a"}})
    await node.run({"server": "tools", "tool": "shout", "arguments": {"text": "b"}})
    assert len(node._connections) == 1


async def test_tool_error_fails_step(node):
    with pytest.raises(NodeError, match="broken"):
        await node.run({"server": "tools", "tool": "broken"})
    with pytest.raises(NodeError, match="Unknown tool"):
        await node.run({"server": "tools", "tool": "missing"})


async def test_bad_server_spec(node):
    with pytest.raises(NodeError, match="unknown MCP server"):
        await node.run({"server": "nope", "tool": "add"})


async def test_mcp_step_inside_a_workflow(node):
    wf = Workflow.model_validate({"id": "m", "steps": [
        {"id": "src", "type": "mock", "params": {"duration_ms": 1, "output": {"word": "flow"}}},
        {"id": "loud", "type": "mcp", "depends_on": ["src"],
         "params": {"server": "tools", "tool": "shout", "arguments": {"text": "{{steps.src.output.word}}"}}},
    ]})
    result = await run_workflow(wf, {"mock": MockNode(), "mcp": node})
    assert result.status == "succeeded" and result.steps["loud"].output["content"] == "FLOW"
