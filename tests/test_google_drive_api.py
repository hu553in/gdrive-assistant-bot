from __future__ import annotations

from types import SimpleNamespace

import pytest
from googleapiclient.errors import HttpError

from gdrive_assistant_bot.providers.google_drive import api as gapi
from gdrive_assistant_bot.providers.google_drive.api import execute_with_backoff


class _FakeLimiter:
    def __init__(self) -> None:
        self.calls = 0

    def acquire(self) -> None:
        self.calls += 1


def _http_error(status: int) -> HttpError:
    resp = SimpleNamespace(status=status, reason="reason")
    return HttpError(resp, b"error")


def test_execute_with_backoff_success() -> None:
    limiter = _FakeLimiter()

    def call() -> str:
        return "ok"

    assert execute_with_backoff(call, limiter) == "ok"
    assert limiter.calls == 1


def test_execute_with_backoff_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    limiter = _FakeLimiter()
    attempts = {"count": 0}
    expected_attempts = 2

    def call() -> str:
        attempts["count"] += 1
        if attempts["count"] < expected_attempts:
            raise _http_error(429)
        return "ok"

    monkeypatch.setattr(gapi.settings, "STORAGE_GOOGLE_DRIVE_BACKOFF_RETRIES", 2)
    monkeypatch.setattr(gapi.settings, "STORAGE_GOOGLE_DRIVE_BACKOFF_BASE_DELAY_SECONDS", 0.01)
    monkeypatch.setattr(gapi.settings, "STORAGE_GOOGLE_DRIVE_BACKOFF_MAX_DELAY_SECONDS", 0.02)
    monkeypatch.setattr(gapi.random, "random", lambda: 0.0)
    monkeypatch.setattr(gapi.time, "sleep", lambda _: None)

    assert execute_with_backoff(call, limiter) == "ok"
    assert attempts["count"] == expected_attempts


def test_execute_with_backoff_raises_on_non_retryable() -> None:
    limiter = _FakeLimiter()
    attempts = {"count": 0}
    expected_attempts = 1

    def call() -> str:
        attempts["count"] += 1
        raise _http_error(400)

    with pytest.raises(HttpError):
        execute_with_backoff(call, limiter)

    assert attempts["count"] == expected_attempts


def test_execute_with_backoff_exhausts_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    limiter = _FakeLimiter()
    attempts = {"count": 0}
    expected_attempts = 2

    def call() -> str:
        attempts["count"] += 1
        raise _http_error(503)

    monkeypatch.setattr(gapi.settings, "STORAGE_GOOGLE_DRIVE_BACKOFF_RETRIES", 1)
    monkeypatch.setattr(gapi.settings, "STORAGE_GOOGLE_DRIVE_BACKOFF_BASE_DELAY_SECONDS", 0.01)
    monkeypatch.setattr(gapi.settings, "STORAGE_GOOGLE_DRIVE_BACKOFF_MAX_DELAY_SECONDS", 0.02)
    monkeypatch.setattr(gapi.random, "random", lambda: 0.0)
    monkeypatch.setattr(gapi.time, "sleep", lambda _: None)

    with pytest.raises(HttpError):
        execute_with_backoff(call, limiter)

    assert attempts["count"] == expected_attempts
