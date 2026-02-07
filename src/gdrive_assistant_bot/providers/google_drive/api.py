from __future__ import annotations

import io
import random
import time
from collections.abc import Callable
from typing import Any

import structlog
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseDownload

from ...errors import ShutdownRequested
from ...settings import settings
from ..base import Limiter, StopEvent

log = structlog.get_logger("gdrive-assistant-bot.providers.google_drive.api")


def execute_with_backoff[T](call: Callable[[], T], limiter: Limiter) -> T:
    """Execute a callable with Google API retry/backoff semantics."""

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
            if attempt > settings.STORAGE_GOOGLE_DRIVE_BACKOFF_RETRIES:
                raise

            delay = min(
                settings.STORAGE_GOOGLE_DRIVE_BACKOFF_MAX_DELAY_SECONDS,
                settings.STORAGE_GOOGLE_DRIVE_BACKOFF_BASE_DELAY_SECONDS * (2 ** (attempt - 1)),
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
                    "max_retries": settings.STORAGE_GOOGLE_DRIVE_BACKOFF_RETRIES,
                    "backoff_base_seconds": (
                        settings.STORAGE_GOOGLE_DRIVE_BACKOFF_BASE_DELAY_SECONDS
                    ),
                    "backoff_max_seconds": settings.STORAGE_GOOGLE_DRIVE_BACKOFF_MAX_DELAY_SECONDS,
                },
            )
            time.sleep(delay)


def download_request(request: Any, limiter: Limiter, stop_event: StopEvent) -> bytes:
    """Download a file/export request with retry and shutdown handling."""

    buffer = io.BytesIO()
    downloader = MediaIoBaseDownload(buffer, request)
    done = False
    while not done:
        if stop_event.is_set():
            raise ShutdownRequested()
        _, done = execute_with_backoff(downloader.next_chunk, limiter)
    return buffer.getvalue()


def download_export(
    drive: Any, file_id: str, mime_type: str, limiter: Limiter, stop_event: StopEvent
) -> bytes:
    """Export a Google Docs file to the requested MIME type."""

    request = drive.files().export(fileId=file_id, mimeType=mime_type)
    return download_request(request, limiter, stop_event)


def download_binary(drive: Any, file_id: str, limiter: Limiter, stop_event: StopEvent) -> bytes:
    """Download a binary file by Google Drive file ID."""

    request = drive.files().get_media(fileId=file_id)
    return download_request(request, limiter, stop_event)
