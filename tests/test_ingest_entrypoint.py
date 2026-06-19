from __future__ import annotations

import threading

import pytest

from gdrive_assistant_bot import ingest as ingest_app
from gdrive_assistant_bot.settings import settings


class _FakeService:
    def __init__(self) -> None:
        self.run_once_called = False
        self.run_loop_called = False

    def run_once(self, _limiter, stop_event: threading.Event) -> None:
        self.run_once_called = True
        stop_event.set()

    def run_loop(self, _limiter, stop_event: threading.Event) -> None:
        self.run_loop_called = True
        stop_event.set()


def test_ingest_main_raises_when_provider_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    def noop() -> None:
        return None

    def noop_health(*_args, **_kwargs) -> None:
        return None

    def get_provider(_name: str):
        return None

    def list_providers() -> list[str]:
        return ["other"]

    monkeypatch.setattr(ingest_app, "setup_logging", noop)
    monkeypatch.setattr(ingest_app, "start_health_server", noop_health)
    monkeypatch.setattr(ingest_app, "init_extractors", noop)
    monkeypatch.setattr(ingest_app, "init_providers", noop)
    monkeypatch.setattr(ingest_app, "get_provider", get_provider)
    monkeypatch.setattr(ingest_app, "list_providers", list_providers)

    with pytest.raises(ValueError):
        ingest_app.main()


def test_ingest_main_runs_once(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_service = _FakeService()

    def noop() -> None:
        return None

    def noop_health(*_args, **_kwargs) -> None:
        return None

    def install_handlers(_event: threading.Event) -> None:
        return None

    def get_provider(_name: str):
        return object()

    def make_store():
        return object()

    def make_limiter(**_kwargs):
        return object()

    def make_service(_store, _provider):
        return fake_service

    monkeypatch.setattr(settings, "INGEST_MODE", "once")
    monkeypatch.setattr(settings, "INGEST_POLL_SECONDS", 1)
    monkeypatch.setattr(ingest_app, "setup_logging", noop)
    monkeypatch.setattr(ingest_app, "start_health_server", noop_health)
    monkeypatch.setattr(ingest_app, "init_extractors", noop)
    monkeypatch.setattr(ingest_app, "init_providers", noop)
    monkeypatch.setattr(ingest_app, "_install_signal_handlers", install_handlers)
    monkeypatch.setattr(ingest_app, "get_provider", get_provider)
    monkeypatch.setattr(ingest_app, "RAGStore", make_store)
    monkeypatch.setattr(ingest_app, "RateLimiter", make_limiter)
    monkeypatch.setattr(ingest_app, "IngestService", make_service)

    ingest_app.main()

    assert fake_service.run_once_called is True
    assert fake_service.run_loop_called is False
