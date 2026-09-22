import pytest

from flowforge.nodes import NodeError, TransientNodeError
from flowforge.nodes.mock_node import MockNode


async def test_returns_output():
    assert await MockNode().run({"duration_ms": 1, "output": 42}) == 42


async def test_transient_then_success():
    node = MockNode()
    params = {"duration_ms": 1, "fail": "transient", "fail_times": 1}
    with pytest.raises(TransientNodeError):
        await node.run(params)
    assert await node.run(params) == {"step_done": True}


async def test_permanent_failure():
    with pytest.raises(NodeError):
        await MockNode().run({"duration_ms": 1, "fail": "permanent"})
