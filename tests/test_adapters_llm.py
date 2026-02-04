from __future__ import annotations

import pytest

from gdrive_assistant_bot.adapters import llm as llm_adapter
from gdrive_assistant_bot.settings import settings


class _FakeOpenAI:
    def __init__(self, *, base_url: str, api_key: str) -> None:
        self.base_url = base_url
        self.api_key = api_key


def test_make_llm_client_returns_none_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "LLM_BASE_URL", None)
    monkeypatch.setattr(settings, "LLM_API_KEY", None)
    monkeypatch.setattr(settings, "LLM_MODEL", None)

    client = llm_adapter.make_llm_client()

    assert client is None


def test_make_llm_client_returns_client_when_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "LLM_BASE_URL", "http://llm.local")
    monkeypatch.setattr(settings, "LLM_API_KEY", "key")
    monkeypatch.setattr(settings, "LLM_MODEL", "model")
    monkeypatch.setattr(llm_adapter, "OpenAI", _FakeOpenAI)

    client = llm_adapter.make_llm_client()

    assert isinstance(client, _FakeOpenAI)
    assert client.base_url == "http://llm.local"
    assert client.api_key == "key"
