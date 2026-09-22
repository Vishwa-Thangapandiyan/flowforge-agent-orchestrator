"""NVIDIA NIM chat completion via the OpenAI-compatible API (D8). Owner: Person C.

params: prompt (str) | messages (list), model?, temperature? (default 0), max_tokens? (default 512)
output: {"text": str, "model": str, "usage": {"prompt_tokens", "completion_tokens"}}

429 / 5xx / timeouts / connection errors → TransientNodeError (with Retry-After);
everything else (bad request, auth) → NodeError. The SDK's own retries are off —
the executor owns retries so they go through the rate limiter.
"""

from __future__ import annotations

import os
from typing import Any

import openai

from flowforge.nodes.base import Node, NodeError, TransientNodeError, parse_retry_after


class LLMNode(Node):
    type = "llm"
    rate_limit_key = "nim"

    def __init__(self, client: Any | None = None) -> None:
        self.base_url = os.getenv("NIM_BASE_URL", "https://integrate.api.nvidia.com/v1")
        self.default_model = os.getenv("NIM_DEFAULT_MODEL", "meta/llama-3.1-8b-instruct")
        self._client = client

    @property
    def client(self) -> Any:
        if self._client is None:
            api_key = os.getenv("NVIDIA_API_KEY")
            if not api_key:
                raise NodeError("NVIDIA_API_KEY is not set — get a free key at build.nvidia.com and put it in .env")
            self._client = openai.AsyncOpenAI(api_key=api_key, base_url=self.base_url, max_retries=0)
        return self._client

    def cacheable_across_runs(self, params: dict[str, Any]) -> bool:
        return params.get("temperature", 0) == 0

    async def run(self, params: dict[str, Any]) -> Any:
        if "messages" in params:
            messages = params["messages"]
        elif "prompt" in params:
            messages = [{"role": "user", "content": str(params["prompt"])}]
        else:
            raise NodeError("llm step needs params.prompt or params.messages")

        try:
            completion = await self.client.chat.completions.create(
                model=params.get("model", self.default_model),
                messages=messages,
                temperature=params.get("temperature", 0),
                max_tokens=params.get("max_tokens", 512),
            )
        except openai.RateLimitError as exc:
            raise TransientNodeError(
                f"NIM rate limit: {exc}", parse_retry_after(exc.response.headers.get("retry-after"))
            ) from exc
        except openai.APIStatusError as exc:
            if exc.status_code >= 500:
                raise TransientNodeError(
                    f"NIM {exc.status_code}: {exc}", parse_retry_after(exc.response.headers.get("retry-after"))
                ) from exc
            raise NodeError(f"NIM {exc.status_code}: {exc}") from exc
        except openai.APIConnectionError as exc:  # includes APITimeoutError
            raise TransientNodeError(f"NIM connection: {exc}") from exc

        usage = completion.usage
        return {
            "text": completion.choices[0].message.content or "",
            "model": completion.model,
            "usage": {
                "prompt_tokens": usage.prompt_tokens if usage else 0,
                "completion_tokens": usage.completion_tokens if usage else 0,
            },
        }
