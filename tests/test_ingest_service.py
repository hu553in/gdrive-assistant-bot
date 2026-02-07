from __future__ import annotations

import threading
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any, cast

import pytest

from gdrive_assistant_bot.core.ingest.service import IngestService
from gdrive_assistant_bot.extractors.base import ExtractedContent, ExtractionContext
from gdrive_assistant_bot.providers.base import FileTypeFilter, StorageFileMeta
from tests.fakes import FakeRAGStore


@dataclass(slots=True)
class _FakeExtractor:
    text: str = "content"
    file_type: str = "fake"
    metadata: dict[str, Any] | None = None
    raise_error: Exception | None = None

    def extract(self, _file_meta: dict[str, Any], _context: Any) -> ExtractedContent:
        if self.raise_error:
            raise self.raise_error
        return ExtractedContent(
            text=self.text, file_type=self.file_type, metadata=self.metadata or {}
        )


class _FakeProvider:
    name = "fake"

    def __init__(self, files: list[StorageFileMeta] | None = None) -> None:
        self.files = files or []
        self.list_filters: list[FileTypeFilter] = []

    def list_files(
        self, file_filter: FileTypeFilter, limiter: Any, stop_event: Any
    ) -> list[StorageFileMeta]:
        _ = limiter, stop_event
        self.list_filters.append(file_filter)
        return list(self.files)

    def build_extraction_context(self, limiter: Any, stop_event: Any) -> ExtractionContext:
        return cast(ExtractionContext, SimpleNamespace(limiter=limiter, stop_event=stop_event))


class _FakeLimiter:
    def acquire(self) -> None:
        return


def _file_meta(file_id: str, *, name: str = "file", mime: str = "text/plain") -> StorageFileMeta:
    return StorageFileMeta(
        id=file_id,
        name=name,
        mime_type=mime,
        modified_time="mtime",
        size=10,
        extension="txt",
        raw={},
    )


def test_ingest_one_file_skips_when_stop_event_set() -> None:
    store = FakeRAGStore()
    provider = _FakeProvider()
    service = IngestService(store, provider)
    limiter = _FakeLimiter()
    stop_event = threading.Event()
    stop_event.set()

    status = service._ingest_one_file(_file_meta("1"), limiter, stop_event)

    assert status == "skipped_empty"
    assert store.upserts == []


def test_ingest_one_file_skips_unchanged() -> None:
    store = FakeRAGStore(existing_mtimes={("1", "mtime")})
    provider = _FakeProvider()
    service = IngestService(store, provider)
    limiter = _FakeLimiter()
    stop_event = threading.Event()

    status = service._ingest_one_file(_file_meta("1"), limiter, stop_event)

    assert status == "skipped_unchanged"
    assert store.upserts == []


def test_ingest_one_file_skips_unsupported(monkeypatch: pytest.MonkeyPatch) -> None:
    store = FakeRAGStore()
    provider = _FakeProvider()
    service = IngestService(store, provider)
    limiter = _FakeLimiter()
    stop_event = threading.Event()

    monkeypatch.setattr(
        "gdrive_assistant_bot.core.ingest.service.get_extractor", lambda _meta: None
    )

    status = service._ingest_one_file(_file_meta("1"), limiter, stop_event)

    assert status == "skipped_empty"
    assert store.upserts == []


def test_ingest_one_file_handles_extractor_error(monkeypatch: pytest.MonkeyPatch) -> None:
    store = FakeRAGStore()
    provider = _FakeProvider()
    service = IngestService(store, provider)
    limiter = _FakeLimiter()
    stop_event = threading.Event()

    extractor = _FakeExtractor(raise_error=RuntimeError("boom"))
    monkeypatch.setattr(
        "gdrive_assistant_bot.core.ingest.service.get_extractor", lambda _meta: extractor
    )

    status = service._ingest_one_file(_file_meta("1"), limiter, stop_event)

    assert status == "skipped_empty"
    assert store.upserts == []


def test_ingest_one_file_skips_empty_text(monkeypatch: pytest.MonkeyPatch) -> None:
    store = FakeRAGStore()
    provider = _FakeProvider()
    service = IngestService(store, provider)
    limiter = _FakeLimiter()
    stop_event = threading.Event()

    extractor = _FakeExtractor(text="   ")
    monkeypatch.setattr(
        "gdrive_assistant_bot.core.ingest.service.get_extractor", lambda _meta: extractor
    )

    status = service._ingest_one_file(_file_meta("1"), limiter, stop_event)

    assert status == "skipped_empty"
    assert store.upserts == []


def test_ingest_one_file_upserts_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    store = FakeRAGStore()
    provider = _FakeProvider()
    service = IngestService(store, provider)
    limiter = _FakeLimiter()
    stop_event = threading.Event()

    extractor = _FakeExtractor(text="hello", metadata={"extra": "meta"})
    monkeypatch.setattr(
        "gdrive_assistant_bot.core.ingest.service.get_extractor", lambda _meta: extractor
    )

    status = service._ingest_one_file(_file_meta("1", name="name"), limiter, stop_event)

    assert status == "ok"
    assert store.deletes == ["1"]
    assert store.upserts
    payload = store.upserts[0]["payload"]
    assert payload["file_id"] == "1"
    assert payload["file_name"] == "name"
    assert payload["file_type"] == "fake"
    assert payload["modified_time"] == "mtime"
    assert payload["extra"] == "meta"


def test_run_once_builds_filter_and_processes_files(monkeypatch: pytest.MonkeyPatch) -> None:
    files = [_file_meta("1"), _file_meta("2")]
    provider = _FakeProvider(files=files)
    store = FakeRAGStore()
    service = IngestService(store, provider)

    monkeypatch.setattr(
        "gdrive_assistant_bot.core.ingest.service.get_supported_mimes", lambda: ["text/plain"]
    )
    monkeypatch.setattr(
        "gdrive_assistant_bot.core.ingest.service.get_supported_mime_prefixes", lambda: ["text/"]
    )
    monkeypatch.setattr(
        "gdrive_assistant_bot.core.ingest.service.get_supported_extensions", lambda: ["txt"]
    )
    monkeypatch.setattr("gdrive_assistant_bot.core.ingest.service.settings.INGEST_WORKERS", 1)

    extractor = _FakeExtractor(text="hello")
    monkeypatch.setattr(
        "gdrive_assistant_bot.core.ingest.service.get_extractor", lambda _meta: extractor
    )

    limiter = _FakeLimiter()
    stop_event = threading.Event()

    service.run_once(limiter, stop_event)

    assert provider.list_filters
    file_filter = provider.list_filters[0]
    assert file_filter.mime_types == ["text/plain"]
    assert file_filter.mime_prefixes == ["text/"]
    assert file_filter.extensions == ["txt"]
    expected_upserts = 2
    assert len(store.upserts) == expected_upserts
