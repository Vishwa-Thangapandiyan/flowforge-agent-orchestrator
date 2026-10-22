"""LLM chat completion for any provider (D8, D10).

params: prompt (str) | messages (list), model?, temperature?, max_tokens?
output: {"text": str, "model": str, "usage": {"prompt_tokens", "completion_tokens"[, "credits"]}}

`LLMNode()` is the V1 node: NVIDIA NIM from env (D8), output unchanged.
`LLMNode.from_connector(c)` builds a node for one connector (D10):
  openai_compatible — NIM, Gemini's OpenAI endpoint, Ollama, vLLM, OpenRouter (openai SDK)
  anthropic         — Claude via the official anthropic SDK; `system` messages move to the
                      `system` parameter, sampling parameters are not sent (current Claude
                      models reject them), and server-side refusal fallback is enabled on
                      the models that support it
Connector nodes add usage.credits (0 until a provider reports credits; no invented prices).

429 / 5xx / timeouts / connection errors → TransientNodeError (with Retry-After);
everything else (bad request, auth, refusal) → NodeError. The SDKs' own retries are off —
the executor owns retries so they go through the rate limiter.
"""

from __future__ import annotations

import os
from typing import Any

import anthropic
import openai

from flowforge.connectors.models import LLMConnector
from flowforge.connectors.secrets import SecretRefError, resolve_secret
from flowforge.nodes.base import Node, NodeError, TransientNodeError, parse_retry_after

ANTHROPIC_DEFAULT_MAX_TOKENS = 16000  # thinking is always on; a small budget truncates answers
# Models that accept the server-side refusal fallback ("default" routing by refusal category).
ANTHROPIC_SERVER_FALLBACK_MODELS = {"claude-fable-5-1", "claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5"}
ANTHROPIC_FALLBACK_BETA = "server-side-fallback-2026-07-01"


class LLMNode(Node):
    type = "llm"
    rate_limit_key = "nim"

    def __init__(self, client: Any | None = None) -> None:
        """The V1 default: NVIDIA NIM configured from env (D8)."""
        self.provider = "openai_compatible"
        self.label = "NIM"
        self.base_url: str | None = os.getenv("NIM_BASE_URL", "https://integrate.api.nvidia.com/v1")
        self.default_model = os.getenv("NIM_DEFAULT_MODEL", "meta/llama-3.1-8b-instruct")
        self.temperature_default = 0.0
        self.secret_ref: str | None = None  # None here = the V1 NVIDIA_API_KEY lookup
        self.report_credits = False
        self._client = client

    @classmethod
    def from_connector(cls, connector: LLMConnector, client: Any | None = None) -> LLMNode:
        node = cls(client)
        conn = connector.connection
        node.connector_id = connector.id
        node.rate_limit_key = connector.id
        node.fallback = connector.fallback
        node.provider = conn.provider
        node.label = f"{connector.id} ({conn.provider})"
        node.base_url = conn.base_url
        node.default_model = conn.model
        node.temperature_default = conn.temperature_default
        node.secret_ref = connector.secret_ref
        node.report_credits = True
        return node

    @property
    def client(self) -> Any:
        if self._client is None:
            self._client = self._make_client()
        return self._client

    def _make_client(self) -> Any:
        if self.connector_id is None:
            api_key = os.getenv("NVIDIA_API_KEY")
            if not api_key:
                raise NodeError("NVIDIA_API_KEY is not set — get a free key at build.nvidia.com and put it in .env")
            return openai.AsyncOpenAI(api_key=api_key, base_url=self.base_url, max_retries=0)
        try:
            api_key = resolve_secret(self.secret_ref)
        except SecretRefError as exc:
            raise NodeError(f"{self.label}: {exc}") from exc
        if self.provider == "anthropic":
            # no key configured → the SDK resolves its own credentials (env, `ant auth login` profile)
            return anthropic.AsyncAnthropic(**({"api_key": api_key} if api_key else {}), max_retries=0)
        # keyless local servers (Ollama) still need a non-empty value for the client
        return openai.AsyncOpenAI(api_key=api_key or "unused", base_url=self.base_url, max_retries=0)

    def cacheable_across_runs(self, params: dict[str, Any]) -> bool:
        return params.get("temperature", self.temperature_default) == 0

    async def run(self, params: dict[str, Any]) -> Any:
        if "messages" in params:
            messages = params["messages"]
        elif "prompt" in params:
            messages = [{"role": "user", "content": str(params["prompt"])}]
        else:
            raise NodeError("llm step needs params.prompt or params.messages")

        sdk = anthropic if self.provider == "anthropic" else openai
        try:
            if self.provider == "anthropic":
                text, model, prompt_tokens, completion_tokens = await self._anthropic(params, messages)
            else:
                text, model, prompt_tokens, completion_tokens = await self._openai(params, messages)
        except sdk.RateLimitError as exc:
            raise TransientNodeError(
                f"{self.label} rate limit: {exc}", parse_retry_after(exc.response.headers.get("retry-after"))
            ) from exc
        except sdk.APIStatusError as exc:
            if exc.status_code >= 500:
                raise TransientNodeError(
                    f"{self.label} {exc.status_code}: {exc}", parse_retry_after(exc.response.headers.get("retry-after"))
                ) from exc
            raise NodeError(f"{self.label} {exc.status_code}: {exc}") from exc
        except sdk.APIConnectionError as exc:  # includes APITimeoutError
            raise TransientNodeError(f"{self.label} connection: {exc}") from exc

        usage: dict[str, Any] = {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens}
        if self.report_credits:
            usage["credits"] = 0
        return {"text": text, "model": model, "usage": usage}

    async def _openai(self, params: dict[str, Any], messages: list[Any]) -> tuple[str, str, int, int]:
        completion = await self.client.chat.completions.create(
            model=params.get("model", self.default_model),
            messages=messages,
            temperature=params.get("temperature", self.temperature_default),
            max_tokens=params.get("max_tokens", 512),
        )
        usage = completion.usage
        return (
            completion.choices[0].message.content or "",
            completion.model,
            usage.prompt_tokens if usage else 0,
            usage.completion_tokens if usage else 0,
        )

    async def _anthropic(self, params: dict[str, Any], messages: list[Any]) -> tuple[str, str, int, int]:
        system = "\n\n".join(str(m["content"]) for m in messages if m.get("role") == "system")
        model = params.get("model", self.default_model)
        request: dict[str, Any] = {
            "model": model,
            "max_tokens": params.get("max_tokens", ANTHROPIC_DEFAULT_MAX_TOKENS),
            "messages": [m for m in messages if m.get("role") != "system"],
        }
        if system:
            request["system"] = system
        if model in ANTHROPIC_SERVER_FALLBACK_MODELS:
            request |= {"betas": [ANTHROPIC_FALLBACK_BETA], "fallbacks": "default"}
        message = await self.client.beta.messages.create(**request)
        if message.stop_reason == "refusal":
            category = getattr(message.stop_details, "category", None) if message.stop_details else None
            raise NodeError(f"{self.label} refused the request" + (f" ({category})" if category else ""))
        text = "".join(block.text for block in message.content if block.type == "text")
        return text, message.model, message.usage.input_tokens, message.usage.output_tokens
