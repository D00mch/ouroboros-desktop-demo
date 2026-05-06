"""Shared GigaChat demo-runtime helpers."""

from __future__ import annotations

import os


DEFAULT_LLM_URL = "https://gigachat-ift.sberdevices.delta.sbrf.ru/v1/chat/completions"
DEFAULT_MODEL_ID = "glm-5.1"
DEMO_MODEL_VALUE = f"gigachat::{DEFAULT_MODEL_ID}"

_MTLS_CERT_PATH = "~/crt/giga.pem"
_MTLS_KEY_PATH = "~/crt/giga.key"
_CA_CERT_PATH = "~/crt/cp.pem"


def _expand(path: str) -> str:
    return os.path.expanduser(path)


def llm_url() -> str:
    raw = str(os.environ.get("LLM_URL", "") or "").strip() or DEFAULT_LLM_URL
    trimmed = raw.rstrip("/")
    if trimmed.endswith("/chat/completions"):
        return trimmed
    if trimmed.endswith("/v1"):
        return f"{trimmed}/chat/completions"
    return f"{trimmed}/chat/completions"


def runtime_available() -> bool:
    return bool(llm_url())


def mtls_cert_path() -> str:
    return _expand(_MTLS_CERT_PATH)


def mtls_key_path() -> str:
    return _expand(_MTLS_KEY_PATH)


def ca_cert_path() -> str:
    return _expand(_CA_CERT_PATH)


def tls_verify_value() -> str | bool:
    ca_path = ca_cert_path()
    return ca_path if os.path.exists(ca_path) else False


def bearer_token() -> str:
    return str(os.environ.get("GIGA_TOKEN", "") or "").strip()


def demo_settings_defaults() -> dict[str, str]:
    return {
        "OUROBOROS_MODEL": DEMO_MODEL_VALUE,
        "OUROBOROS_MODEL_CODE": DEMO_MODEL_VALUE,
        "OUROBOROS_MODEL_LIGHT": DEMO_MODEL_VALUE,
        "OUROBOROS_MODEL_FALLBACK": DEMO_MODEL_VALUE,
        "OUROBOROS_REVIEW_MODELS": ",".join([DEMO_MODEL_VALUE] * 3),
        "OUROBOROS_SCOPE_REVIEW_MODEL": DEMO_MODEL_VALUE,
    }


def demo_review_models() -> list[str]:
    return [DEMO_MODEL_VALUE] * 3
