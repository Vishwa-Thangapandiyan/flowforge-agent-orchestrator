"""Connectors → runtime nodes and rate-limit buckets (D10, D16)."""

from __future__ import annotations

import os

from flowforge.connectors.models import Connector
from flowforge.connectors.presets import with_env_overrides
from flowforge.nodes.base import Node
from flowforge.nodes.http_node import HTTPNode
from flowforge.nodes.llm_node import LLMNode
from flowforge.nodes.local_node import LocalNode
from flowforge.nodes.mcp_node import MCPNode
from flowforge.nodes.mock_node import MockNode
from flowforge.scheduler.rate_limit import TokenBucket

NODE_BUILDERS = {"llm": LLMNode.from_connector, "mcp": MCPNode.from_connector,
                 "http": HTTPNode.from_connector, "local": LocalNode.from_connector}


def build_node(connector: Connector) -> tuple[Node, TokenBucket | None]:
    """The node for one connector, and its own bucket if it has a rate limit."""
    connector = with_env_overrides(connector)
    node = NODE_BUILDERS[connector.type](connector)
    if connector.id == "nim" and isinstance(node, LLMNode):
        node.default_for_type = True  # the default llm keeps the V1 cache namespace
    bucket = TokenBucket(connector.rate_limit_rpm) if connector.rate_limit_rpm and node.rate_limit_key else None
    return node, bucket


def build_nodes(connectors: list[Connector]) -> tuple[dict[str, Node], dict[str, TokenBucket]]:
    """One node per connector, keyed by id, plus each type's default under the type name (D10).

    The default llm is the `nim` connector; it keeps the V1 cache namespace and the "nim"
    bucket. mcp and http keep their V1 nodes as defaults (a step may still pass params.server).
    """
    nodes: dict[str, Node] = {"http": HTTPNode(), "mcp": MCPNode(), "mock": MockNode()}
    buckets: dict[str, TokenBucket] = {}
    for connector in connectors:
        node, bucket = build_node(connector)
        nodes[connector.id] = node
        if bucket is not None and node.rate_limit_key:
            buckets[node.rate_limit_key] = bucket
    nodes["llm"] = nodes["nim"] if isinstance(nodes.get("nim"), LLMNode) else LLMNode()
    buckets.setdefault("nim", TokenBucket(float(os.getenv("NIM_RPM", "40"))))
    return nodes, buckets
