import io
import random
import time
from collections.abc import Callable
from typing import Protocol

import structlog
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseDownload

from ..errors import ShutdownRequested
from ..settings import settings

log = structlog.get_logger("gdrive-assistant-bot.extractors.utils")


class Limiter(Protocol):
    def acquire(self) -> None: ...


class StopEvent(Protocol):
    def is_set(self) -> bool: ...


def execute_with_backoff[T](call: Callable[[], T], limiter: Limiter) -> T:
    attempt = 0
    while True:
        limiter.acquire()
        try:
            return call()
        except HttpError as exc:
            status = getattr(exc, "status_code", None)
            if status is None and hasattr(exc, "resp"):
                status = getattr(exc.resp, "status", None)

            retryable = status in (429, 500, 502, 503, 504)

            if not retryable:
                raise

            attempt += 1
            if attempt > settings.GOOGLE_BACKOFF_RETRIES:
                raise

            delay = min(
                settings.GOOGLE_BACKOFF_MAX_DELAY_SECONDS,
                settings.GOOGLE_BACKOFF_BASE_DELAY_SECONDS * (2 ** (attempt - 1)),
            )
            delay *= 0.7 + random.random() * 0.6
            log.warning(
                "google_api_retry",
                component="ingest",
                flow="google_api",
                meta={
                    "status": status,
                    "attempt": attempt,
                    "delay_seconds": round(delay, 2),
                    "max_retries": settings.GOOGLE_BACKOFF_RETRIES,
                    "backoff_base_seconds": settings.GOOGLE_BACKOFF_BASE_DELAY_SECONDS,
                    "backoff_max_seconds": settings.GOOGLE_BACKOFF_MAX_DELAY_SECONDS,
                },
            )
            time.sleep(delay)


def download_request(request, limiter: Limiter, stop_event: StopEvent) -> bytes:
    buffer = io.BytesIO()
    downloader = MediaIoBaseDownload(buffer, request)
    done = False
    while not done:
        if stop_event.is_set():
            raise ShutdownRequested()
        _, done = execute_with_backoff(downloader.next_chunk, limiter)
    return buffer.getvalue()


def download_export(
    drive, file_id: str, mime_type: str, limiter: Limiter, stop_event: StopEvent
) -> bytes:
    request = drive.files().export(fileId=file_id, mimeType=mime_type)
    return download_request(request, limiter, stop_event)


def download_binary(drive, file_id: str, limiter: Limiter, stop_event: StopEvent) -> bytes:
    request = drive.files().get_media(fileId=file_id)
    return download_request(request, limiter, stop_event)
