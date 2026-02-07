from __future__ import annotations

import threading

from gdrive_assistant_bot.providers.base import FileTypeFilter
from gdrive_assistant_bot.providers.google_drive import provider as gprovider
from gdrive_assistant_bot.providers.google_drive.provider import GoogleDriveProvider


def test_matches_filter_by_mime_and_prefix_and_extension() -> None:
    provider = GoogleDriveProvider()
    file_filter = FileTypeFilter(
        mime_types=["application/test"], mime_prefixes=["text/"], extensions=["md"]
    )

    assert provider._matches_filter({"mimeType": "application/test"}, file_filter) is True
    assert provider._matches_filter({"mimeType": "text/plain"}, file_filter) is True
    assert (
        provider._matches_filter(
            {"mimeType": "application/other", "fileExtension": "MD"}, file_filter
        )
        is True
    )
    assert (
        provider._matches_filter({"mimeType": "application/other", "name": "notes.MD"}, file_filter)
        is True
    )
    assert provider._matches_filter({"mimeType": "application/other"}, file_filter) is False


def test_build_drive_query_terms_orders_prefixes_and_extensions() -> None:
    provider = GoogleDriveProvider()
    file_filter = FileTypeFilter(
        mime_types=["application/test"],
        mime_prefixes=["text/", "application/"],
        extensions=["b", "a"],
    )

    terms = provider._build_drive_query_terms(file_filter)
    assert terms == [
        "mimeType='application/test'",
        "mimeType contains 'application/'",
        "mimeType contains 'text/'",
        "fileExtension='a'",
        "name contains '.a'",
        "fileExtension='b'",
        "name contains '.b'",
    ]


def test_to_storage_meta_normalizes_size_and_extension() -> None:
    provider = GoogleDriveProvider()
    expected_size = 42
    meta = provider._to_storage_meta(
        {
            "id": "1",
            "name": "file",
            "mimeType": "text/plain",
            "modifiedTime": "2024-01-01",
            "size": str(expected_size),
            "fileExtension": "TXT",
        }
    )

    assert meta.size == expected_size
    assert meta.extension == "TXT"
    as_meta = meta.as_extractor_meta()
    assert as_meta["id"] == "1"
    assert as_meta["fileExtension"] == "TXT"


def test_build_extraction_context_initializes_optional_clients_lazily(monkeypatch) -> None:
    provider = GoogleDriveProvider()
    calls: list[str] = []

    class _Client:
        def __init__(self, api: str) -> None:
            self.api = api

        def marker(self) -> str:
            return self.api

    def fake_get_thread_client(service_account_json: str, api: str):
        assert service_account_json == gprovider.settings.STORAGE_GOOGLE_DRIVE_SERVICE_ACCOUNT_JSON
        calls.append(api)
        return _Client(api)

    monkeypatch.setattr(gprovider, "get_thread_client", fake_get_thread_client)
    monkeypatch.setattr(gprovider.settings, "FILE_TYPE_GDOCS_ENABLED", True)
    monkeypatch.setattr(gprovider.settings, "FILE_TYPE_GSHEETS_ENABLED", True)
    monkeypatch.setattr(gprovider.settings, "FILE_TYPE_GSLIDES_ENABLED", True)

    ctx = provider.build_extraction_context(limiter=object(), stop_event=threading.Event())

    assert calls == ["drive"]
    assert ctx.docs.marker() == "docs"
    assert ctx.sheets.marker() == "sheets"
    assert ctx.slides.marker() == "slides"
    assert calls == ["drive", "docs", "sheets", "slides"]


def test_build_extraction_context_skips_disabled_optional_clients(monkeypatch) -> None:
    provider = GoogleDriveProvider()
    calls: list[str] = []

    def fake_get_thread_client(_service_account_json: str, api: str):
        calls.append(api)
        return object()

    monkeypatch.setattr(gprovider, "get_thread_client", fake_get_thread_client)
    monkeypatch.setattr(gprovider.settings, "FILE_TYPE_GDOCS_ENABLED", False)
    monkeypatch.setattr(gprovider.settings, "FILE_TYPE_GSHEETS_ENABLED", False)
    monkeypatch.setattr(gprovider.settings, "FILE_TYPE_GSLIDES_ENABLED", False)

    ctx = provider.build_extraction_context(limiter=object(), stop_event=threading.Event())

    assert ctx.docs is None
    assert ctx.sheets is None
    assert ctx.slides is None
    assert calls == ["drive"]
