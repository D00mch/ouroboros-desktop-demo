import asyncio
import inspect
import json

import ouroboros.model_catalog_api as model_catalog_api
from ouroboros.demo_llm import DEMO_LLM_MODEL


def test_model_catalog_returns_fixed_demo_model():
    response = asyncio.run(model_catalog_api.api_model_catalog(None))
    payload = json.loads(response.body.decode("utf-8"))

    assert payload["items"] == [{
        "provider_id": "gigachat",
        "provider": "GigaChat",
        "source": "LLM_URL",
        "id": DEMO_LLM_MODEL,
        "name": DEMO_LLM_MODEL,
        "value": DEMO_LLM_MODEL,
        "label": f"GigaChat · {DEMO_LLM_MODEL}",
    }]
    assert payload["errors"] == []


def test_model_catalog_does_not_call_provider_loaders(monkeypatch):
    calls = []

    async def _loader(_client):
        await asyncio.sleep(0)
        calls.append("provider")
        return [{"value": "provider::model", "label": "Provider Model"}]

    monkeypatch.setattr(model_catalog_api, "_provider_specs", lambda settings: [("provider", _loader)])

    response = asyncio.run(model_catalog_api.api_model_catalog(None))
    payload = json.loads(response.body.decode("utf-8"))

    assert payload["items"][0]["value"] == DEMO_LLM_MODEL
    assert payload["errors"] == []
    assert calls == []


def test_model_catalog_no_longer_uses_requests_or_to_thread():
    source = inspect.getsource(model_catalog_api)
    assert "import requests" not in source
    assert "asyncio.to_thread" not in source
