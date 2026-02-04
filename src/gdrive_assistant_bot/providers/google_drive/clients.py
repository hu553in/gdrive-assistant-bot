from __future__ import annotations

import threading
from typing import Any

from google.oauth2 import service_account
from googleapiclient.discovery import build

SCOPES: list[str] = ["https://www.googleapis.com/auth/drive.readonly"]

_thread_local = threading.local()


def get_thread_clients(service_account_json: str) -> tuple[Any, Any, Any]:
    """Build or reuse thread-local Drive, Docs, and Sheets clients."""

    if getattr(_thread_local, "creds", None) is None:
        _thread_local.creds = service_account.Credentials.from_service_account_file(
            service_account_json, scopes=SCOPES
        )
        _thread_local.drive = build(
            "drive", "v3", credentials=_thread_local.creds, cache_discovery=False
        )
        _thread_local.docs = build(
            "docs", "v1", credentials=_thread_local.creds, cache_discovery=False
        )
        _thread_local.sheets = build(
            "sheets", "v4", credentials=_thread_local.creds, cache_discovery=False
        )

    return _thread_local.drive, _thread_local.docs, _thread_local.sheets
