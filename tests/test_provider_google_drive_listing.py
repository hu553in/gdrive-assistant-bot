from __future__ import annotations

import threading
from typing import Any

import pytest

from gdrive_assistant_bot.providers.base import FileTypeFilter
from gdrive_assistant_bot.providers.google_drive import provider as gprovider
from gdrive_assistant_bot.providers.google_drive.provider import (
    FOLDER_MIME,
    SHORTCUT_MIME,
    GoogleDriveProvider,
)


class _FakeLimiter:
    def acquire(self) -> None:
        return


class _FakeGoogleDrive:
    def __init__(self, pages: dict[str | None, dict[str, Any]]) -> None:
        self.pages = pages
        self.calls: list[str | None] = []
        self.qs: list[str] = []
        self._current: str | None = None

    def files(self) -> _FakeGoogleDrive:
        return self

    def list(
        self, *, q: str, fields: str, pageToken: str | None, pageSize: int
    ) -> _FakeGoogleDrive:
        _ = fields, pageSize
        self.qs.append(q)
        self.calls.append(pageToken)
        self._current = pageToken
        return self

    def execute(self) -> dict[str, Any]:
        return self.pages.get(self._current, {})


def test_list_children_paginates(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = GoogleDriveProvider()
    pages = {
        None: {"files": [{"id": "1"}], "nextPageToken": "t1"},
        "t1": {"files": [{"id": "2"}], "nextPageToken": None},
    }
    drive = _FakeGoogleDrive(pages)

    def no_backoff(call, _limiter):
        return call()

    monkeypatch.setattr(gprovider, "execute_with_backoff", no_backoff)

    files = provider._list_children(
        drive, "root", limiter=_FakeLimiter(), stop_event=threading.Event()
    )

    assert files == [{"id": "1"}, {"id": "2"}]
    assert drive.calls == [None, "t1"]


def test_walk_recursive_skips_shortcuts_and_cycles(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = GoogleDriveProvider()
    file_filter = FileTypeFilter(mime_types=["text/plain"], mime_prefixes=[], extensions=[])

    tree = {
        "root": [
            {"id": "folder", "mimeType": FOLDER_MIME},
            {"id": "shortcut", "mimeType": SHORTCUT_MIME, "name": "s"},
            {"id": "file1", "mimeType": "text/plain"},
        ],
        "folder": [
            {"id": "root", "mimeType": FOLDER_MIME},
            {"id": "file2", "mimeType": "text/plain"},
        ],
    }

    def fake_list_children(_drive, parent_id: str, _limiter, _stop_event):
        return tree.get(parent_id, [])

    monkeypatch.setattr(provider, "_list_children", fake_list_children)

    files = list(
        provider._walk_recursive(
            drive=None,
            root_ids=["root"],
            limiter=_FakeLimiter(),
            stop_event=threading.Event(),
            file_filter=file_filter,
        )
    )

    assert [f["id"] for f in files] == ["file1", "file2"]


def test_list_all_accessible_files_filters_shortcuts(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = GoogleDriveProvider()
    file_filter = FileTypeFilter(mime_types=["text/plain"], mime_prefixes=[], extensions=[])
    pages = {
        None: {
            "files": [
                {"id": "shortcut", "mimeType": SHORTCUT_MIME},
                {"id": "file1", "mimeType": "text/plain"},
                {"id": "file2", "mimeType": "image/png"},
            ],
            "nextPageToken": None,
        }
    }
    drive = _FakeGoogleDrive(pages)

    def no_backoff(call, _limiter):
        return call()

    monkeypatch.setattr(gprovider, "execute_with_backoff", no_backoff)

    files = provider._list_all_accessible_files(
        drive, limiter=_FakeLimiter(), file_filter=file_filter, stop_event=threading.Event()
    )

    assert [f["id"] for f in files] == ["file1"]
    assert drive.qs
    assert "trashed=false" in drive.qs[0]
    assert "mimeType='text/plain'" in drive.qs[0]


def test_list_all_accessible_files_includes_name_extension_query(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = GoogleDriveProvider()
    file_filter = FileTypeFilter(mime_types=[], mime_prefixes=[], extensions=["md"])
    pages = {
        None: {
            "files": [
                {"id": "file1", "mimeType": "application/octet-stream", "name": "notes.MD"},
                {"id": "file2", "mimeType": "application/octet-stream", "name": "archive.bin"},
            ],
            "nextPageToken": None,
        }
    }
    drive = _FakeGoogleDrive(pages)

    def no_backoff(call, _limiter):
        return call()

    monkeypatch.setattr(gprovider, "execute_with_backoff", no_backoff)

    files = provider._list_all_accessible_files(
        drive, limiter=_FakeLimiter(), file_filter=file_filter, stop_event=threading.Event()
    )

    assert [f["id"] for f in files] == ["file1"]
    assert drive.qs
    assert "fileExtension='md'" in drive.qs[0]
    assert "name contains '.md'" in drive.qs[0]


def test_list_files_initializes_drive_client_only(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = GoogleDriveProvider()
    file_filter = FileTypeFilter(mime_types=[], mime_prefixes=[], extensions=[])
    calls: list[str] = []

    def fake_get_thread_client(service_account_json: str, api: str):
        assert service_account_json == gprovider.settings.STORAGE_GOOGLE_DRIVE_SERVICE_ACCOUNT_JSON
        calls.append(api)
        return object()

    monkeypatch.setattr(gprovider, "get_thread_client", fake_get_thread_client)
    monkeypatch.setattr(gprovider.settings, "STORAGE_GOOGLE_DRIVE_ALL_ACCESSIBLE", True)
    monkeypatch.setattr(
        provider,
        "_list_all_accessible_files",
        lambda _drive, _limiter, _file_filter, _stop_event: [],
    )

    files = list(
        provider.list_files(file_filter, limiter=_FakeLimiter(), stop_event=threading.Event())
    )

    assert files == []
    assert calls == ["drive"]


def test_list_children_respects_stop_event(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = GoogleDriveProvider()
    drive = _FakeGoogleDrive({None: {"files": [{"id": "1"}], "nextPageToken": None}})
    stop_event = threading.Event()
    stop_event.set()

    calls = {"execute_with_backoff": 0}

    def no_backoff(call, _limiter):
        calls["execute_with_backoff"] += 1
        return call()

    monkeypatch.setattr(gprovider, "execute_with_backoff", no_backoff)

    files = provider._list_children(drive, "root", limiter=_FakeLimiter(), stop_event=stop_event)

    assert files == []
    assert calls["execute_with_backoff"] == 0
    assert drive.calls == []


def test_list_all_accessible_files_respects_stop_event(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = GoogleDriveProvider()
    file_filter = FileTypeFilter(mime_types=["text/plain"], mime_prefixes=[], extensions=[])
    drive = _FakeGoogleDrive(
        {None: {"files": [{"id": "1", "mimeType": "text/plain"}], "nextPageToken": None}}
    )
    stop_event = threading.Event()
    stop_event.set()

    calls = {"execute_with_backoff": 0}

    def no_backoff(call, _limiter):
        calls["execute_with_backoff"] += 1
        return call()

    monkeypatch.setattr(gprovider, "execute_with_backoff", no_backoff)

    files = provider._list_all_accessible_files(
        drive, limiter=_FakeLimiter(), file_filter=file_filter, stop_event=stop_event
    )

    assert files == []
    assert calls["execute_with_backoff"] == 0
    assert drive.calls == []
