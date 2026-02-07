from __future__ import annotations

import threading
from typing import Any, Literal

from google.oauth2 import service_account
from googleapiclient.discovery import build

_GoogleAPIName = Literal["drive", "docs", "sheets", "slides"]

SCOPES: list[str] = [
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/documents.readonly",
    "https://www.googleapis.com/auth/spreadsheets.readonly",
    "https://www.googleapis.com/auth/presentations.readonly",
]
_API_VERSIONS: dict[_GoogleAPIName, str] = {
    "drive": "v3",
    "docs": "v1",
    "sheets": "v4",
    "slides": "v1",
}
_CLIENT_ATTRS: tuple[str, ...] = ("creds", *_API_VERSIONS.keys())

_thread_local = threading.local()


def _clear_thread_clients() -> None:
    for attr in _CLIENT_ATTRS:
        if hasattr(_thread_local, attr):
            delattr(_thread_local, attr)


def _get_thread_creds(service_account_json: str) -> Any:
    creds = getattr(_thread_local, "creds", None)
    if creds is not None:
        return creds

    try:
        creds = service_account.Credentials.from_service_account_file(
            service_account_json, scopes=SCOPES
        )
    except Exception:
        _clear_thread_clients()
        raise

    _thread_local.creds = creds
    return creds


def get_thread_client(service_account_json: str, api: _GoogleAPIName) -> Any:
    """Build or reuse a thread-local Google API client for the requested API."""

    client = getattr(_thread_local, api, None)
    if client is not None:
        return client

    creds = _get_thread_creds(service_account_json)
    try:
        client = build(api, _API_VERSIONS[api], credentials=creds, cache_discovery=False)
    except Exception:
        if hasattr(_thread_local, api):
            delattr(_thread_local, api)
        raise

    setattr(_thread_local, api, client)
    return client


def get_thread_clients(
    service_account_json: str,
    apis: tuple[_GoogleAPIName, ...] = ("drive", "docs", "sheets", "slides"),
) -> tuple[Any, ...]:
    """Build or reuse thread-local Google clients for the requested APIs."""

    try:
        return tuple(get_thread_client(service_account_json, api) for api in apis)
    except Exception:
        _clear_thread_clients()
        raise
