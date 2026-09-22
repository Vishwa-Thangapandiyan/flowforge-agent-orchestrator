"""NVIDIA NIM chat completion via the OpenAI-compatible API (D8). Owner: Person C.

params: prompt (str) | messages (list), model?, temperature? (default 0), max_tokens? (default 512)
output: {"text": str, "model": str, "usage": {"prompt_tokens", "completion_tokens"}}

Map openai.RateLimitError (429) / APIStatusError 5xx / APITimeoutError / APIConnectionError
→ TransientNodeError (read Retry-After from the response headers when present);
everything else → NodeError.
"""

from __future__ import annotations

import os
from typing import Any

from flowforge.nodes.base import Node


class LLMNode(Node):
    type = "llm"
    rate_limit_key = "nim"

    def __init__(self) -> None:
        self.base_url = os.getenv("NIM_BASE_URL", "https://integrate.api.nvidia.com/v1")
        self.default_model = os.getenv("NIM_DEFAULT_MODEL", "meta/llama-3.1-8b-instruct")
        self.api_key = os.getenv("NVIDIA_API_KEY")

    def cacheable_across_runs(self, params: dict[str, Any]) -> bool:
        return params.get("temperature", 0) == 0

    async def run(self, params: dict[str, Any]) -> Any:
        raise NotImplementedError
