"""Provider-agnostic LLM connectors (D10): openai_compatible and anthropic, with stubbed clients."""

from types import SimpleNamespace

import anthropic
import httpx2
import openai
import pytest

from flowforge.connectors.models import parse_connector
from flowforge.nodes import NodeError, TransientNodeError
from flowforge.nodes.llm_node import LLMNode

FAKE_KEY = "sk-ant-FAKEFAKEFAKE12345678"
REQ = httpx2.Request("POST", "https://llm.test/v1/x")


def connector(provider="openai_compatible", model="gemini-flash", **over):
    conn = {"provider": provider, "model": model}
    if provider == "openai_compatible":
        conn["base_url"] = "https://llm.test/v1"
    return parse_connector({"id": over.pop("id", "gem"), "type": "llm", "name": "LLM",
                            "connection": conn, "secret_ref": "env:TEST_LLM_KEY", **over})


def status_error(cls, code, retry_after=None):
    headers = {"retry-after": retry_after} if retry_after else {}
    return cls("err", response=httpx2.Response(code, headers=headers, request=REQ), body=None)


class FakeOpenAI:
    def __init__(self, result=None, error=None):
        self.calls, self.result, self.error = [], result, error
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return self.result


def completion(text="hi"):
    return SimpleNamespace(model="gemini-flash", choices=[SimpleNamespace(message=SimpleNamespace(content=text))],
                           usage=SimpleNamespace(prompt_tokens=4, completion_tokens=2))


class FakeAnthropic:
    def __init__(self, result=None, error=None):
        self.calls, self.result, self.error = [], result, error
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self.create))

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return self.result


def message(*blocks, stop_reason="end_turn", category=None):
    return SimpleNamespace(
        model="claude-opus-5-5", stop_reason=stop_reason,
        stop_details=SimpleNamespace(category=category) if stop_reason == "refusal" else None,
        content=list(blocks) or [SimpleNamespace(type="text", text="hello")],
        usage=SimpleNamespace(input_tokens=11, output_tokens=5))


# --- openai_compatible -------------------------------------------------------------------------

async def test_openai_compatible_connector_uses_its_own_settings():
    client = FakeOpenAI(completion("ok"))
    node = LLMNode.from_connector(connector(rate_limit_rpm=15, fallback="nim"), client=client)
    out = await node.run({"prompt": "q"})
    assert out == {"text": "ok", "model": "gemini-flash",
                   "usage": {"prompt_tokens": 4, "completion_tokens": 2, "credits": 0}}
    assert client.calls[0]["model"] == "gemini-flash"
    assert (node.connector_id, node.rate_limit_key, node.fallback, node.cache_namespace) == (
        "gem", "gem", "nim", "llm:gem")


async def test_errors_name_the_connector_and_provider():
    node = LLMNode.from_connector(connector(), client=FakeOpenAI(error=status_error(openai.RateLimitError, 429, "3")))
    with pytest.raises(TransientNodeError, match=r"gem \(openai_compatible\) rate limit") as exc:
        await node.run({"prompt": "q"})
    assert exc.value.retry_after_s == 3
    assert "NIM" not in str(exc.value)


async def test_temperature_default_comes_from_the_connector():
    node = LLMNode.from_connector(parse_connector({
        "id": "warm", "type": "llm", "name": "Warm",
        "connection": {"provider": "openai_compatible", "base_url": "https://llm.test/v1", "model": "m",
                       "temperature_default": 0.7}}), client=FakeOpenAI(completion()))
    await node.run({"prompt": "q"})
    assert node.client.calls[0]["temperature"] == 0.7
    assert not node.cacheable_across_runs({"prompt": "q"})
    assert node.cacheable_across_runs({"prompt": "q", "temperature": 0})


async def test_keyless_local_provider_needs_no_secret():
    node = LLMNode.from_connector(parse_connector({
        "id": "ollama", "type": "llm", "name": "Ollama",
        "connection": {"provider": "openai_compatible", "base_url": "http://localhost:11434/v1", "model": "llama3"}}))
    assert node.client.base_url.host == "localhost"  # built without a key, never called


# --- anthropic ---------------------------------------------------------------------------------

async def test_anthropic_maps_system_messages_and_omits_sampling_params():
    client = FakeAnthropic(message())
    node = LLMNode.from_connector(connector("anthropic", "claude-opus-5-5", id="claude"), client=client)
    out = await node.run({"messages": [{"role": "system", "content": "be brief"},
                                       {"role": "user", "content": "hi"}], "temperature": 0})
    call = client.calls[0]
    assert call["system"] == "be brief"
    assert call["messages"] == [{"role": "user", "content": "hi"}]
    assert "temperature" not in call  # current Claude models reject sampling parameters
    assert call["max_tokens"] == 16000  # thinking is always on; a small budget would truncate answers
    assert out == {"text": "hello", "model": "claude-opus-5-5",
                   "usage": {"prompt_tokens": 11, "completion_tokens": 5, "credits": 0}}


async def test_anthropic_enables_server_side_fallback_on_supported_models():
    client = FakeAnthropic(message())
    await LLMNode.from_connector(connector("anthropic", "claude-opus-5-5"), client=client).run({"prompt": "q"})
    assert client.calls[0]["fallbacks"] == "default"
    assert client.calls[0]["betas"] == ["server-side-fallback-2026-07-01"]

    client = FakeAnthropic(message())
    await LLMNode.from_connector(connector("anthropic", "claude-haiku-4-5"), client=client).run({"prompt": "q"})
    assert "fallbacks" not in client.calls[0] and "betas" not in client.calls[0]


async def test_anthropic_joins_text_blocks_only():
    client = FakeAnthropic(message(SimpleNamespace(type="thinking", thinking=""),
                                   SimpleNamespace(type="text", text="a"), SimpleNamespace(type="text", text="b")))
    out = await LLMNode.from_connector(connector("anthropic", "claude-opus-5-5"), client=client).run({"prompt": "q"})
    assert out["text"] == "ab"


async def test_anthropic_refusal_is_permanent():
    client = FakeAnthropic(message(stop_reason="refusal", category="cyber"))
    with pytest.raises(NodeError, match="refused") as exc:
        await LLMNode.from_connector(connector("anthropic", "claude-opus-5-5"), client=client).run({"prompt": "q"})
    assert not isinstance(exc.value, TransientNodeError)


@pytest.mark.parametrize("error, transient", [
    (status_error(anthropic.RateLimitError, 429, "9"), True),
    (status_error(anthropic.InternalServerError, 529), True),
    (anthropic.APITimeoutError(request=REQ), True),
    (anthropic.APIConnectionError(request=REQ), True),
    (status_error(anthropic.BadRequestError, 400), False),
    (status_error(anthropic.AuthenticationError, 401), False),
])
async def test_anthropic_error_mapping(error, transient):
    node = LLMNode.from_connector(connector("anthropic", "claude-opus-5-5", id="claude"),
                                  client=FakeAnthropic(error=error))
    with pytest.raises(NodeError, match=r"claude \(anthropic\)") as exc:
        await node.run({"prompt": "q"})
    assert isinstance(exc.value, TransientNodeError) is transient
    if transient and error.__class__ is anthropic.RateLimitError:
        assert exc.value.retry_after_s == 9


# --- secrets -----------------------------------------------------------------------------------

async def test_missing_secret_is_a_clear_permanent_error(monkeypatch):
    monkeypatch.delenv("TEST_LLM_KEY", raising=False)
    with pytest.raises(NodeError, match="TEST_LLM_KEY is not set") as exc:
        await LLMNode.from_connector(connector()).run({"prompt": "q"})
    assert not isinstance(exc.value, TransientNodeError)


async def test_vault_ref_fails_until_phase_3():
    with pytest.raises(NodeError, match="Phase 3"):
        await LLMNode.from_connector(connector(secret_ref="vault:TEST_LLM_KEY")).run({"prompt": "q"})


def test_secret_reaches_the_client_but_not_the_node(monkeypatch):
    monkeypatch.setenv("TEST_LLM_KEY", FAKE_KEY)
    node = LLMNode.from_connector(connector("anthropic", "claude-opus-5-5"))
    assert node.client.api_key == FAKE_KEY
    assert all(FAKE_KEY not in repr(value) for name, value in vars(node).items() if name != "_client")


async def test_errors_never_contain_the_key(monkeypatch):
    monkeypatch.setenv("TEST_LLM_KEY", FAKE_KEY)
    node = LLMNode.from_connector(connector(), client=FakeOpenAI(error=status_error(openai.AuthenticationError, 401)))
    with pytest.raises(NodeError) as exc:
        await node.run({"prompt": "q"})
    assert FAKE_KEY not in str(exc.value)


# --- the V1 default is untouched ----------------------------------------------------------------

def test_legacy_default_node_unchanged():
    node = LLMNode(FakeOpenAI())
    assert (node.rate_limit_key, node.connector_id, node.cache_namespace) == ("nim", None, "llm")
