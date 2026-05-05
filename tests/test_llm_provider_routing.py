import json

import pytest
import ouroboros.pricing as pricing_module
from ouroboros.llm import LLMClient
from ouroboros.demo_llm import DEMO_LLM_MODEL


def test_chat_uses_fixed_demo_llm_url_and_mtls(monkeypatch):
    monkeypatch.setenv("LLM_URL", "https://demo.example/v1/chat/completions")
    captured = {}

    class _Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "choices": [{"message": {"role": "assistant", "content": "ok"}}],
                "model": "GigaChat-3-Ultra-preview:32.3.7.3",
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            }

    def fake_post(url, **kwargs):
        captured["url"] = url
        captured["kwargs"] = kwargs
        return _Response()

    monkeypatch.setattr("requests.post", fake_post)

    msg, usage = LLMClient().chat(
        messages=[{"role": "user", "content": "hi"}],
        model="openai::ignored",
        max_tokens=123,
    )

    assert captured["url"] == "https://demo.example/v1/chat/completions"
    assert captured["kwargs"]["headers"] == {"Content-Type": "application/json"}
    assert captured["kwargs"]["json"]["model"] == DEMO_LLM_MODEL
    assert captured["kwargs"]["json"]["messages"] == [{"role": "user", "content": "hi"}]
    assert captured["kwargs"]["json"]["max_tokens"] == 123
    cert_path, key_path = captured["kwargs"]["cert"]
    assert cert_path.endswith("/crt/giga.pem")
    assert key_path.endswith("/crt/giga.key")
    assert captured["kwargs"]["verify"] is False
    assert msg["content"] == "ok"
    assert usage["provider"] == "gigachat"
    assert usage["resolved_model"] == "GigaChat-3-Ultra-preview:32.3.7.3"


def test_chat_parses_demo_json_content_tool_call(monkeypatch):
    monkeypatch.setenv("LLM_URL", "https://demo.example/v1/chat/completions")
    captured = {}

    class _Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "choices": [{
                    "message": {
                        "role": "assistant",
                        "content": (
                            "```json\n"
                            "{\n"
                            '  "name": "echo_word",\n'
                            '  "arguments": {"word": "data-science"}\n'
                            "}\n"
                            "```"
                        ),
                    }
                }],
                "model": "GigaChat-3-Ultra-preview:32.3.7.3",
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            }

    def fake_post(url, **kwargs):
        captured["url"] = url
        captured["kwargs"] = kwargs
        return _Response()

    monkeypatch.setattr("requests.post", fake_post)

    tools = [{
        "type": "function",
        "function": {
            "name": "echo_word",
            "description": "Echo one word",
            "parameters": {
                "type": "object",
                "properties": {"word": {"type": "string"}},
                "required": ["word"],
            },
        },
    }]
    msg, _usage = LLMClient().chat(
        messages=[{"role": "user", "content": "Use the echo tool."}],
        model="ignored",
        tools=tools,
    )

    payload = captured["kwargs"]["json"]
    assert payload["tools"] == tools
    assert payload["tool_choice"] == "auto"
    assert any(
        message["role"] == "system" and "Tool calling compatibility mode" in message["content"]
        for message in payload["messages"]
    )
    assert msg["content"] is None
    assert msg["tool_calls"][0]["function"]["name"] == "echo_word"
    assert json.loads(msg["tool_calls"][0]["function"]["arguments"]) == {"word": "data-science"}


def test_prepare_demo_messages_converts_tool_history_to_text():
    prepared = LLMClient._prepare_demo_messages(
        [
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [{
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "echo_word", "arguments": '{"word": "data-science"}'},
                }],
            },
            {"role": "tool", "tool_call_id": "call_1", "content": "data-science"},
        ],
        tools=[],
    )

    assert prepared[0]["role"] == "assistant"
    assert "Tool calls requested" in prepared[0]["content"]
    assert "echo_word" in prepared[0]["content"]
    assert "tool_calls" not in prepared[0]
    assert prepared[1] == {
        "role": "user",
        "content": "Tool result (call_1):\ndata-science",
    }


def test_model_switch_surface_is_fixed_to_demo_model():
    client = LLMClient()

    assert client.default_model() == DEMO_LLM_MODEL
    assert client.available_models() == [DEMO_LLM_MODEL]


def test_resolve_openai_target(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "openai-key")

    target = LLMClient()._resolve_remote_target("openai::gpt-4.1")

    assert target["provider"] == "openai"
    assert target["resolved_model"] == "gpt-4.1"
    assert target["usage_model"] == "openai/gpt-4.1"
    assert target["base_url"] == "https://api.openai.com/v1"


def test_build_remote_kwargs_uses_max_completion_tokens_for_openai_gpt5(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "openai-key")

    client = LLMClient()
    target = client._resolve_remote_target("openai::gpt-5.2")
    kwargs = client._build_remote_kwargs(
        target,
        [{"role": "user", "content": "hi"}],
        "high",
        512,
        "auto",
        None,
        None,
    )

    assert kwargs["max_completion_tokens"] == 512
    assert "max_tokens" not in kwargs


def test_build_remote_kwargs_keeps_max_tokens_for_openai_gpt41(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "openai-key")

    client = LLMClient()
    target = client._resolve_remote_target("openai::gpt-4.1")
    kwargs = client._build_remote_kwargs(
        target,
        [{"role": "user", "content": "hi"}],
        "high",
        512,
        "auto",
        None,
        None,
    )

    assert kwargs["max_tokens"] == 512
    assert "max_completion_tokens" not in kwargs


def test_build_remote_kwargs_normalizes_tool_descriptions_for_openrouter():
    client = LLMClient()
    target = client._resolve_remote_target("anthropic/claude-sonnet-4.6")

    kwargs = client._build_remote_kwargs(
        target,
        [{"role": "user", "content": "hi"}],
        "high",
        512,
        "auto",
        None,
        [{
            "type": "function",
            "function": {
                "name": "bad_tool",
                "description": ("first half ", "second half"),
                "parameters": {"type": "object", "properties": {}},
            },
        }],
    )

    assert kwargs["tools"][0]["function"]["description"] == "first half second half"


def test_build_remote_kwargs_deduplicates_tool_names_for_openrouter():
    client = LLMClient()
    target = client._resolve_remote_target("anthropic/claude-sonnet-4.6")

    kwargs = client._build_remote_kwargs(
        target,
        [{"role": "user", "content": "hi"}],
        "high",
        512,
        "auto",
        None,
        [
            {
                "type": "function",
                "function": {
                    "name": "dup_tool",
                    "description": "first",
                    "parameters": {"type": "object", "properties": {}},
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "dup_tool",
                    "description": "second",
                    "parameters": {"type": "object", "properties": {}},
                },
            },
        ],
    )

    assert [tool["function"]["name"] for tool in kwargs["tools"]] == ["dup_tool"]
    assert kwargs["tools"][0]["function"]["description"] == "first"


def test_build_anthropic_tools_deduplicates_tool_names():
    tools = [
        {
            "type": "function",
            "function": {
                "name": "dup_tool",
                "description": "first",
                "parameters": {"type": "object", "properties": {}},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "dup_tool",
                "description": "second",
                "parameters": {"type": "object", "properties": {}},
            },
        },
    ]

    anthropic_tools = LLMClient._build_anthropic_tools(tools)

    assert anthropic_tools == [
        {
            "name": "dup_tool",
            "description": "first",
            "input_schema": {"type": "object", "properties": {}},
        }
    ]


def test_resolve_anthropic_target_normalizes_direct_model(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "anthropic-key")

    target = LLMClient()._resolve_remote_target("anthropic::claude-sonnet-4.6")

    assert target["provider"] == "anthropic"
    assert target["resolved_model"] == "claude-sonnet-4-6"
    assert target["usage_model"] == "anthropic/claude-sonnet-4-6"
    assert target["base_url"] == "https://api.anthropic.com/v1"


def test_normalize_anthropic_response_maps_tool_use(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "anthropic-key")

    client = LLMClient()
    target = client._resolve_remote_target("anthropic::claude-sonnet-4-6")
    message, usage = client._normalize_anthropic_response(
        {
            "content": [
                {"type": "text", "text": "Working on it."},
                {"type": "tool_use", "id": "toolu_1", "name": "echo_tool", "input": {"text": "hello"}},
            ],
            "usage": {
                "input_tokens": 11,
                "output_tokens": 7,
                "cache_read_input_tokens": 3,
                "cache_creation_input_tokens": 2,
            },
        },
        target,
    )

    assert message["content"] == "Working on it."
    assert message["tool_calls"][0]["function"]["name"] == "echo_tool"
    assert message["tool_calls"][0]["function"]["arguments"] == '{"text": "hello"}'
    assert usage["provider"] == "anthropic"
    assert usage["resolved_model"] == "anthropic/claude-sonnet-4-6"
    assert usage["cached_tokens"] == 3
    assert usage["cache_write_tokens"] == 2


def test_build_anthropic_messages_preserves_system_blocks_and_cache_control(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "anthropic-key")

    client = LLMClient()
    system_blocks, anthropic_messages = client._build_anthropic_messages([
        {
            "role": "system",
            "content": [
                {"type": "text", "text": "stable", "cache_control": {"type": "ephemeral", "ttl": "1h"}},
                {"type": "text", "text": "dynamic"},
            ],
        },
        {"role": "user", "content": "hi"},
    ])

    assert system_blocks == [
        {"type": "text", "text": "stable", "cache_control": {"type": "ephemeral", "ttl": "1h"}},
        {"type": "text", "text": "dynamic"},
    ]
    assert anthropic_messages == [{"role": "user", "content": [{"type": "text", "text": "hi"}]}]


def test_resolve_openai_compatible_target_prefers_dedicated_credentials(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "legacy-key")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://legacy.example/v1")
    monkeypatch.setenv("OPENAI_COMPATIBLE_API_KEY", "compat-key")
    monkeypatch.setenv("OPENAI_COMPATIBLE_BASE_URL", "https://compat.example/v1")

    target = LLMClient()._resolve_remote_target("openai-compatible::meta-llama/compatible")

    assert target["provider"] == "openai-compatible"
    assert target["api_key"] == "compat-key"
    assert target["base_url"] == "https://compat.example/v1"
    assert target["usage_model"] == "openai-compatible/meta-llama/compatible"


def test_resolve_cloudru_target_uses_default_base_url(monkeypatch):
    monkeypatch.setenv("CLOUDRU_FOUNDATION_MODELS_API_KEY", "cloudru-key")
    monkeypatch.delenv("CLOUDRU_FOUNDATION_MODELS_BASE_URL", raising=False)

    target = LLMClient()._resolve_remote_target("cloudru::giga-model")

    assert target["provider"] == "cloudru"
    assert target["api_key"] == "cloudru-key"
    assert target["base_url"] == "https://foundation-models.api.cloud.ru/v1"
    assert target["usage_model"] == "cloudru/giga-model"


def test_normalize_remote_response_estimates_cost_for_direct_openai(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "openai-key")

    client = LLMClient()
    target = client._resolve_remote_target("openai::gpt-5.2")
    seen = {}

    def fake_estimate_cost(model, prompt_tokens, completion_tokens, cached_tokens=0, cache_write_tokens=0):
        seen["args"] = (model, prompt_tokens, completion_tokens, cached_tokens, cache_write_tokens)
        return 0.123456

    monkeypatch.setattr(pricing_module, "estimate_cost", fake_estimate_cost)

    message, usage = client._normalize_remote_response(
        {
            "choices": [{"message": {"role": "assistant", "content": "ok"}}],
            "usage": {
                "prompt_tokens": 100,
                "completion_tokens": 40,
                "prompt_tokens_details": {"cached_tokens": 10},
            },
        },
        target,
    )

    assert message["content"] == "ok"
    assert usage["provider"] == "openai"
    assert usage["resolved_model"] == "openai/gpt-5.2"
    assert usage["cached_tokens"] == 10
    assert usage["cost"] == 0.123456
    assert seen["args"] == ("openai/gpt-5.2", 100, 40, 10, 0)


def test_build_anthropic_messages_rejects_tool_result_without_tool_call_id(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "anthropic-key")

    client = LLMClient()

    with pytest.raises(ValueError, match="tool_call_id"):
        client._build_anthropic_messages([
            {"role": "user", "content": "hi"},
            {"role": "tool", "content": "done"},
        ])
