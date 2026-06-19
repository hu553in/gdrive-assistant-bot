from __future__ import annotations

import threading

import pytest

from gdrive_assistant_bot.core.ingest.limiter import RateLimiter
from gdrive_assistant_bot.errors import ShutdownRequested


def test_rate_limiter_allows_immediate_acquire() -> None:
    stop_event = threading.Event()
    limiter = RateLimiter(rate=1000.0, burst=2.0, stop_event=stop_event)
    limiter.acquire()
    assert limiter.tokens <= 1.0


def test_rate_limiter_respects_stop_event() -> None:
    stop_event = threading.Event()
    stop_event.set()
    limiter = RateLimiter(rate=1.0, burst=1.0, stop_event=stop_event)
    with pytest.raises(ShutdownRequested):
        limiter.acquire()
