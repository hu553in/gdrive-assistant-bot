from __future__ import annotations

import threading
import time

from ...errors import ShutdownRequested


class RateLimiter:
    """
    Token bucket limiter:
      - rate: tokens/sec
      - burst: max bucket size
    acquire() blocks until token available or stop_event set.
    """

    def __init__(self, *, rate: float, burst: float, stop_event: threading.Event) -> None:
        self.rate = float(rate)
        self.capacity = float(burst)
        self.tokens = float(burst)
        self.updated = time.monotonic()
        self.lock = threading.Lock()
        self.stop_event = stop_event

    def acquire(self) -> None:
        while not self.stop_event.is_set():
            with self.lock:
                now = time.monotonic()
                elapsed = now - self.updated
                if elapsed > 0:
                    self.tokens = min(self.capacity, self.tokens + elapsed * self.rate)
                    self.updated = now

                if self.tokens >= 1.0:
                    self.tokens -= 1.0
                    return

                needed = 1.0 - self.tokens
                sleep_for = max(0.001, needed / self.rate)

            self.stop_event.wait(timeout=sleep_for)

        raise ShutdownRequested()
