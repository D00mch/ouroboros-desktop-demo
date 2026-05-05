"""Fixed demo LLM runtime settings.

The demo build does not collect provider API keys or expose model routing.
Remote calls go to a single OpenAI-compatible chat-completions URL protected
by the server-side mTLS certificate files.
"""

from __future__ import annotations

import os
from typing import Mapping


DEFAULT_LLM_URL = "https://gigachat-ift.sberdevices.delta.sbrf.ru/v1/chat/completions"
DEMO_LLM_MODEL = "GigaChat-3-Ultra-preview"
DEMO_LLM_CERT_PATH = "~/crt/giga.pem"
DEMO_LLM_KEY_PATH = "~/crt/giga.key"
DEMO_LLM_CA_PATH = "~/crt/cp.pem"


def resolve_llm_url(env: Mapping[str, str] | None = None) -> str:
    source = os.environ if env is None else env
    return str(source.get("LLM_URL", "") or "").strip() or DEFAULT_LLM_URL


def resolve_client_cert_paths() -> tuple[str, str]:
    return (
        os.path.expanduser(DEMO_LLM_CERT_PATH),
        os.path.expanduser(DEMO_LLM_KEY_PATH),
    )


def resolve_ca_cert_path() -> str:
    return os.path.expanduser(DEMO_LLM_CA_PATH)
