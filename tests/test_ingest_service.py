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


def _install_fake_log(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, dict[str, Any]]]:
    events: list[tuple[str, dict[str, Any]]] = []

    class _FakeLog:
        def debug(self, event: str, **kwargs: Any) -> None:
            events.append((event, kwargs))

        def info(self, event: str, **kwargs: Any) -> None:
            events.append((event, kwargs))

        def exception(self, event: str, **kwargs: Any) -> None:
            events.append((event, kwargs))

    monkeypatch.setattr("gdrive_assistant_bot.core.ingest.service.log", _FakeLog())
    return events


def test_ingest_one_file_skips_when_stop_event_set() -> None:
    store = FakeRAGStore()
    provider = _FakeProvider()
    service = IngestService(store, provider)
    limiter = _FakeLimiter()
    stop_event = threading.Event()
    stop_event.set()

    status = service._ingest_one_file(_file_meta("1"), limiter, stop_event)

    assert status == "skipped_stopped"
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

    assert status == "skipped_unsupported"
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

    assert status == "failed"
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


def test_run_once_counts_extractor_errors_as_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    files = [_file_meta("1")]
    provider = _FakeProvider(files=files)
    store = FakeRAGStore()
    service = IngestService(store, provider)

    events = _install_fake_log(monkeypatch)
    monkeypatch.setattr("gdrive_assistant_bot.core.ingest.service.settings.INGEST_WORKERS", 1)
    monkeypatch.setattr(
        "gdrive_assistant_bot.core.ingest.service.get_extractor",
        lambda _meta: _FakeExtractor(raise_error=RuntimeError("boom")),
    )

    limiter = _FakeLimiter()
    stop_event = threading.Event()
    service.run_once(limiter, stop_event)

    assert store.upserts == []
    assert any(event == "extraction_failed" for event, _ in events)

    ingest_done = next(kwargs for event, kwargs in events if event == "ingest_done")
    assert ingest_done["meta"]["completed"] == 1
    assert ingest_done["meta"]["ok"] == 0
    assert ingest_done["meta"]["fail"] == 1
    assert ingest_done["meta"]["skipped_empty"] == 0
    assert ingest_done["meta"]["skipped_unsupported"] == 0
    assert ingest_done["meta"]["skipped_stopped"] == 0


def test_run_once_counts_unsupported_files_separately(monkeypatch: pytest.MonkeyPatch) -> None:
    files = [_file_meta("1")]
    provider = _FakeProvider(files=files)
    store = FakeRAGStore()
    service = IngestService(store, provider)

    events = _install_fake_log(monkeypatch)
    monkeypatch.setattr("gdrive_assistant_bot.core.ingest.service.settings.INGEST_WORKERS", 1)
    monkeypatch.setattr(
        "gdrive_assistant_bot.core.ingest.service.get_extractor", lambda _meta: None
    )

    limiter = _FakeLimiter()
    stop_event = threading.Event()
    service.run_once(limiter, stop_event)

    ingest_done = next(kwargs for event, kwargs in events if event == "ingest_done")
    assert ingest_done["meta"]["completed"] == 1
    assert ingest_done["meta"]["ok"] == 0
    assert ingest_done["meta"]["fail"] == 0
    assert ingest_done["meta"]["skipped_empty"] == 0
    assert ingest_done["meta"]["skipped_unsupported"] == 1
    assert ingest_done["meta"]["skipped_stopped"] == 0


def test_run_once_drains_in_flight_results_after_stop_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    files = [_file_meta("1")]
    provider = _FakeProvider(files=files)
    store = FakeRAGStore()
    service = IngestService(store, provider)

    class _StopAfterExtract:
        def extract(self, _file_meta: dict[str, Any], context: Any) -> ExtractedContent:
            context.stop_event.set()
            return ExtractedContent(text="hello", file_type="fake", metadata={})

    events = _install_fake_log(monkeypatch)
    monkeypatch.setattr("gdrive_assistant_bot.core.ingest.service.settings.INGEST_WORKERS", 1)
    monkeypatch.setattr(
        "gdrive_assistant_bot.core.ingest.service.get_extractor", lambda _meta: _StopAfterExtract()
    )

    limiter = _FakeLimiter()
    stop_event = threading.Event()
    service.run_once(limiter, stop_event)

    assert store.upserts == []
    ingest_done = next(kwargs for event, kwargs in events if event == "ingest_done")
    assert ingest_done["meta"]["completed"] == 1
    assert ingest_done["meta"]["ok"] == 0
    assert ingest_done["meta"]["fail"] == 0
    assert ingest_done["meta"]["skipped_stopped"] == 1
