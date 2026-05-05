from ouroboros.demo_llm import DEMO_LLM_MODEL
from ouroboros.server_runtime import (
    apply_runtime_provider_defaults,
    classify_runtime_provider_change,
    has_startup_ready_provider,
    has_supervisor_provider,
)


def test_demo_llm_makes_runtime_ready_without_keys():
    assert has_startup_ready_provider({})
    assert has_supervisor_provider({})


def test_demo_llm_keeps_runtime_ready_with_legacy_provider_settings():
    assert has_startup_ready_provider({"OPENAI_API_KEY": "sk-openai"})
    assert has_supervisor_provider({"ANTHROPIC_API_KEY": "sk-ant"})
    assert has_startup_ready_provider({"LOCAL_MODEL_SOURCE": "Qwen/Qwen2.5-7B-Instruct-GGUF"})


def test_apply_runtime_provider_defaults_forces_fixed_demo_models():
    normalized, changed, changed_keys = apply_runtime_provider_defaults({
        "OPENAI_API_KEY": "sk-openai",
        "OUROBOROS_MODEL": "openai::gpt-5.5",
        "OUROBOROS_MODEL_CODE": "anthropic::claude-opus-4-7",
        "OUROBOROS_MODEL_LIGHT": "custom-light",
        "OUROBOROS_MODEL_FALLBACK": "custom-fallback",
        "OUROBOROS_WEBSEARCH_MODEL": "gpt-5.2",
        "OUROBOROS_REVIEW_MODELS": "a,b,c",
        "OUROBOROS_SCOPE_REVIEW_MODEL": "scope-model",
    })

    assert changed
    assert set(changed_keys) == {
        "OUROBOROS_MODEL",
        "OUROBOROS_MODEL_CODE",
        "OUROBOROS_MODEL_LIGHT",
        "OUROBOROS_MODEL_FALLBACK",
        "OUROBOROS_WEBSEARCH_MODEL",
        "OUROBOROS_REVIEW_MODELS",
        "OUROBOROS_SCOPE_REVIEW_MODEL",
    }
    for key in changed_keys:
        assert normalized[key] == DEMO_LLM_MODEL


def test_apply_runtime_provider_defaults_is_noop_when_already_demo():
    normalized, changed, changed_keys = apply_runtime_provider_defaults({
        "OUROBOROS_MODEL": DEMO_LLM_MODEL,
        "OUROBOROS_MODEL_CODE": DEMO_LLM_MODEL,
        "OUROBOROS_MODEL_LIGHT": DEMO_LLM_MODEL,
        "OUROBOROS_MODEL_FALLBACK": DEMO_LLM_MODEL,
        "OUROBOROS_WEBSEARCH_MODEL": DEMO_LLM_MODEL,
        "OUROBOROS_REVIEW_MODELS": DEMO_LLM_MODEL,
        "OUROBOROS_SCOPE_REVIEW_MODEL": DEMO_LLM_MODEL,
    })

    assert not changed
    assert changed_keys == []
    assert normalized["OUROBOROS_MODEL"] == DEMO_LLM_MODEL


def test_demo_provider_normalization_never_warns():
    assert classify_runtime_provider_change({}, {"OPENAI_API_KEY": "sk-openai"}) == "none"
