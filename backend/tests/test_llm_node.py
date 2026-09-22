from types import SimpleNamespace

import httpx2
import openai
import pytest

from flowforge.nodes import NodeError, TransientNodeError
from flowforge.nodes.llm_node import LLMNode

REQ = httpx2.Request("POST", "https://integrate.api.nvidia.com/v1/chat/completions")


class FakeClient:
    """Stands in for openai.AsyncOpenAI: records calls, returns or raises what it's given."""

    def __init__(self, result=None, error=None):
        self.calls = []
        self.result, self.error = result, error
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return self.result


def completion(text="hi"):
    return SimpleNamespace(
        model="meta/llama-3.1-8b-instruct",
        choices=[SimpleNamespace(message=SimpleNamespace(content=text))],
        usage=SimpleNamespace(prompt_tokens=10, completion_tokens=3),
    )


def status_error(cls, code, retry_after=None):
    headers = {"retry-after": retry_after} if retry_after else {}
    return cls("err", response=httpx2.Response(code, headers=headers, request=REQ), body=None)


async def test_prompt_becomes_user_message_with_defaults():
    client = FakeClient(completion("hello"))
    out = await LLMNode(client).run({"prompt": "Say hi"})
    assert out == {"text": "hello", "model": "meta/llama-3.1-8b-instruct",
                   "usage": {"prompt_tokens": 10, "completion_tokens": 3}}
    call = client.calls[0]
    assert call["messages"] == [{"role": "user", "content": "Say hi"}]
    assert call["temperature"] == 0 and call["max_tokens"] == 512


async def test_model_override_and_messages():
    client = FakeClient(completion())
    msgs = [{"role": "system", "content": "s"}, {"role": "user", "content": "u"}]
    await LLMNode(client).run({"messages": msgs, "model": "mistralai/mixtral-8x7b-instruct-v0.1"})
    assert client.calls[0]["model"] == "mistralai/mixtral-8x7b-instruct-v0.1" and client.calls[0]["messages"] == msgs


async def test_rate_limit_is_transient_with_retry_after():
    node = LLMNode(FakeClient(error=status_error(openai.RateLimitError, 429, "7")))
    with pytest.raises(TransientNodeError) as exc:
        await node.run({"prompt": "x"})
    assert exc.value.retry_after_s == 7


async def test_server_errors_transient_client_errors_permanent():
    with pytest.raises(TransientNodeError):
        await LLMNode(FakeClient(error=status_error(openai.InternalServerError, 503))).run({"prompt": "x"})
    with pytest.raises(NodeError) as exc:
        await LLMNode(FakeClient(error=status_error(openai.BadRequestError, 400))).run({"prompt": "x"})
    assert not isinstance(exc.value, TransientNodeError)


async def test_timeout_is_transient():
    with pytest.raises(TransientNodeError):
        await LLMNode(FakeClient(error=openai.APITimeoutError(request=REQ))).run({"prompt": "x"})


async def test_missing_key_is_a_clear_permanent_error(monkeypatch):
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
    with pytest.raises(NodeError, match="NVIDIA_API_KEY"):
        await LLMNode().run({"prompt": "x"})


def test_cache_policy():
    assert LLMNode(FakeClient()).cacheable_across_runs({"prompt": "x"})
    assert not LLMNode(FakeClient()).cacheable_across_runs({"prompt": "x", "temperature": 0.7})
