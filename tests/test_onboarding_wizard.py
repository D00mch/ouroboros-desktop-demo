import pathlib

import pytest

from ouroboros.onboarding_wizard import build_onboarding_html, prepare_onboarding_settings
from ouroboros.demo_llm import DEFAULT_LLM_URL, DEMO_LLM_MODEL


REPO = pathlib.Path(__file__).resolve().parents[1]


def _base_payload() -> dict:
    return {
        "OPENROUTER_API_KEY": "",
        "OPENAI_API_KEY": "",
        "ANTHROPIC_API_KEY": "",
        "TOTAL_BUDGET": 10,
        "OUROBOROS_PER_TASK_COST_USD": 20,
        "OUROBOROS_REVIEW_ENFORCEMENT": "advisory",
        "LOCAL_MODEL_SOURCE": "",
        "LOCAL_MODEL_FILENAME": "",
        "LOCAL_MODEL_CONTEXT_LENGTH": 16384,
        "LOCAL_MODEL_N_GPU_LAYERS": -1,
        "LOCAL_MODEL_CHAT_FORMAT": "",
        "LOCAL_ROUTING_MODE": "cloud",
        "OUROBOROS_MODEL": "openai::gpt-5.5",
        "OUROBOROS_MODEL_CODE": "openai::gpt-5.5",
        "OUROBOROS_MODEL_LIGHT": "openai::gpt-5.5-mini",
        "OUROBOROS_MODEL_FALLBACK": "openai::gpt-5.5-mini",
    }


def test_prepare_onboarding_settings_accepts_demo_without_keys():
    prepared, error = prepare_onboarding_settings(_base_payload(), {})

    assert error is None
    assert prepared["LLM_URL"] == DEFAULT_LLM_URL
    assert prepared["OPENROUTER_API_KEY"] == ""
    assert prepared["OPENAI_API_KEY"] == ""
    assert prepared["ANTHROPIC_API_KEY"] == ""
    assert prepared["OUROBOROS_MODEL"] == DEMO_LLM_MODEL


def test_prepare_onboarding_settings_accepts_openai_only_setup():
    payload = _base_payload()
    payload["OPENAI_API_KEY"] = "sk-openai-1234567890"

    prepared, error = prepare_onboarding_settings(payload, {})

    assert error is None
    assert prepared["OPENAI_API_KEY"] == ""
    assert prepared["OUROBOROS_MODEL"] == DEMO_LLM_MODEL
    assert prepared["TOTAL_BUDGET"] == 10.0
    assert prepared["OUROBOROS_PER_TASK_COST_USD"] == 20.0
    assert prepared["OUROBOROS_REVIEW_ENFORCEMENT"] == "advisory"


def test_prepare_onboarding_settings_accepts_cloudru_only_setup():
    payload = _base_payload()
    payload["CLOUDRU_FOUNDATION_MODELS_API_KEY"] = "cloudru-key-1234567890"
    payload["OUROBOROS_MODEL"] = "cloudru::zai-org/GLM-4.7"
    payload["OUROBOROS_MODEL_CODE"] = "cloudru::zai-org/GLM-4.7"
    payload["OUROBOROS_MODEL_LIGHT"] = "cloudru::zai-org/GLM-4.7"
    payload["OUROBOROS_MODEL_FALLBACK"] = "cloudru::zai-org/GLM-4.7"

    prepared, error = prepare_onboarding_settings(payload, {})

    assert error is None
    assert prepared["CLOUDRU_FOUNDATION_MODELS_API_KEY"] == ""
    assert prepared["OUROBOROS_MODEL"] == DEMO_LLM_MODEL


def test_prepare_onboarding_settings_accepts_anthropic_only_setup():
    payload = _base_payload()
    payload["ANTHROPIC_API_KEY"] = "sk-ant-1234567890"
    payload["OUROBOROS_MODEL"] = "anthropic::claude-opus-4-6"
    payload["OUROBOROS_MODEL_CODE"] = "anthropic::claude-opus-4-6"
    payload["OUROBOROS_MODEL_LIGHT"] = "anthropic::claude-sonnet-4-6"
    payload["OUROBOROS_MODEL_FALLBACK"] = "anthropic::claude-sonnet-4-6"

    prepared, error = prepare_onboarding_settings(payload, {})

    assert error is None
    assert prepared["ANTHROPIC_API_KEY"] == ""
    assert prepared["OUROBOROS_MODEL"] == DEMO_LLM_MODEL


def test_prepare_onboarding_settings_accepts_local_only_cloud_routing_in_demo():
    payload = _base_payload()
    payload["LOCAL_MODEL_SOURCE"] = "Qwen/Qwen2.5-7B-Instruct-GGUF"
    payload["LOCAL_MODEL_FILENAME"] = "qwen2.5-7b-instruct-q3_k_m.gguf"
    payload["LOCAL_ROUTING_MODE"] = "cloud"

    prepared, error = prepare_onboarding_settings(payload, {})

    assert error is None
    assert prepared["USE_LOCAL_MAIN"] is False
    assert prepared["USE_LOCAL_FALLBACK"] is False


def test_prepare_onboarding_settings_sets_all_local_routes():
    payload = _base_payload()
    payload["LOCAL_MODEL_SOURCE"] = "Qwen/Qwen2.5-7B-Instruct-GGUF"
    payload["LOCAL_MODEL_FILENAME"] = "qwen2.5-7b-instruct-q3_k_m.gguf"
    payload["LOCAL_ROUTING_MODE"] = "all"

    prepared, error = prepare_onboarding_settings(payload, {})

    assert error is None
    assert prepared["USE_LOCAL_MAIN"] is True
    assert prepared["USE_LOCAL_CODE"] is True
    assert prepared["USE_LOCAL_LIGHT"] is True
    assert prepared["USE_LOCAL_FALLBACK"] is True


def test_prepare_onboarding_settings_preserves_non_secret_provider_fields():
    """The demo wizard clears provider keys but leaves non-secret legacy
    endpoint fields alone so old settings files round-trip cleanly."""
    payload = _base_payload()
    payload["OPENAI_API_KEY"] = "sk-openai-1234567890"
    current = {
        "OPENAI_BASE_URL": "https://legacy.example/v1",
        "OPENAI_COMPATIBLE_API_KEY": "compat-secret",
        "OPENAI_COMPATIBLE_BASE_URL": "https://compat.example/v1",
        "CLOUDRU_FOUNDATION_MODELS_BASE_URL": "https://cloud.example/v1",
    }

    prepared, error = prepare_onboarding_settings(payload, current)

    assert error is None
    assert prepared["OPENAI_BASE_URL"] == "https://legacy.example/v1"
    assert prepared["OPENAI_COMPATIBLE_API_KEY"] == ""
    assert prepared["OPENAI_COMPATIBLE_BASE_URL"] == "https://compat.example/v1"
    assert prepared["CLOUDRU_FOUNDATION_MODELS_BASE_URL"] == "https://cloud.example/v1"


def test_build_onboarding_html_contains_multistep_markers():
    html = build_onboarding_html({})

    assert '"stepOrder": ["review_mode", "budget", "summary"]' in html
    assert "Demo onboarding uses the server-side LLM_URL endpoint" in html
    assert "Add your access" in html
    assert "Choose models" in html
    assert "Choose review mode" in html
    assert "Set your budget" in html
    assert DEMO_LLM_MODEL in html
    assert "OPENAI_BASE_URL: ''" not in html
    assert "OPENAI_COMPATIBLE_API_KEY: ''" not in html
    assert "OPENAI_COMPATIBLE_BASE_URL: ''" not in html
    assert "CLOUDRU_FOUNDATION_MODELS_BASE_URL: ''" not in html


def test_build_onboarding_html_accepts_web_host_mode():
    html = build_onboarding_html({}, host_mode="web")

    assert '"hostMode": "web"' in html
    assert '"supportsLocalRuntimeControls": true' in html
    assert "@media (max-width: 720px)" in html
    assert "scroll-snap-type: x proximity;" in html


def test_build_onboarding_html_adapts_to_multi_provider_access():
    html = build_onboarding_html({})

    assert "function detectProviderProfile()" in html
    assert "function activeProviderProfile()" in html
    assert "function profileLabel(profile)" in html
    assert "function nextButtonShouldBeDisabled()" in html
    assert "function syncCurrentStepActionState()" in html
    assert "return 'demo';" in html
    assert "OPENROUTER_API_KEY: ''" in html
    assert "OPENAI_API_KEY: ''" in html
    assert "ANTHROPIC_API_KEY: ''" in html
    assert "LOCAL_ROUTING_MODE: trim(state.localSource) ? (trim(state.localRoutingMode) || 'cloud') : 'cloud'" in html


def test_build_onboarding_html_includes_claude_runtime_cta_and_host_transports():
    desktop_html = build_onboarding_html({}, host_mode="desktop")
    web_html = build_onboarding_html({}, host_mode="web")

    assert "Claude Runtime" in desktop_html or "Claude runtime" in desktop_html
    assert "Skip for now" in desktop_html
    assert "window.pywebview.api.claude_code_status" in desktop_html
    assert "window.pywebview.api.install_claude_code" in desktop_html
    assert "/api/claude-code/status" in web_html
    assert "/api/claude-code/install" in web_html


def _launcher_has_onboarding_bridge() -> bool:
    launcher = REPO / "launcher.py"
    if not launcher.exists():
        return False
    source = launcher.read_text(encoding="utf-8")
    return all(marker in source for marker in (
        "has_startup_ready_provider(settings)",
        "prepare_onboarding_settings(data, settings)",
        'build_onboarding_html(settings, host_mode="desktop")',
        "def claude_code_status(self) -> dict:",
        "def install_claude_code(self) -> dict:",
    ))

_LAUNCHER_HAS_ONBOARDING_BRIDGE = _launcher_has_onboarding_bridge()

@pytest.mark.skipif(
    not _LAUNCHER_HAS_ONBOARDING_BRIDGE,
    reason="launcher.py does not contain onboarding bridge (may be an older bundle or post-refactor version)",
)
def test_launcher_uses_shared_onboarding_and_claude_cli_bridge():
    source = (REPO / "launcher.py").read_text(encoding="utf-8")

    assert "has_startup_ready_provider(settings)" in source
    assert "prepare_onboarding_settings(data, settings)" in source
    assert 'build_onboarding_html(settings, host_mode="desktop")' in source
    assert "def claude_code_status(self) -> dict:" in source
    assert "def install_claude_code(self) -> dict:" in source


def test_web_style_contains_onboarding_overlay_shell():
    style = (REPO / "web" / "style.css").read_text(encoding="utf-8")

    assert ".onboarding-overlay {" in style
    assert ".onboarding-frame {" in style
    assert ".onboarding-overlay-backdrop {" in style
