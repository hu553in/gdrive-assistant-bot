from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any, cast

import pytest

from gdrive_assistant_bot.extractors.base import ExtractionContext
from gdrive_assistant_bot.extractors.office.excel import XLSX_MIME_TYPE, XlsExtractor, XlsxExtractor


@dataclass(slots=True)
class _Context:
    settings: Any
    payload: bytes

    def download_binary(self, _file_id: str) -> bytes:
        return self.payload


def test_xlsx_extractor_can_extract_by_mime_or_extension() -> None:
    extractor = XlsxExtractor()
    assert extractor.can_extract({"mimeType": XLSX_MIME_TYPE}) is True
    assert extractor.can_extract({"fileExtension": "xlsx"}) is True
    assert extractor.can_extract({"fileExtension": "xls"}) is False


def test_xls_extractor_can_extract_by_mime_or_extension() -> None:
    extractor = XlsExtractor()
    assert extractor.can_extract({"mimeType": "application/vnd.ms-excel"}) is True
    assert extractor.can_extract({"fileExtension": "xls"}) is True
    assert extractor.can_extract({"fileExtension": "xlsx"}) is False


def test_xlsx_extractor_skips_on_size_limit() -> None:
    extractor = XlsxExtractor()
    settings = SimpleNamespace(
        OFFICE_MAX_FILE_SIZE_MB=1, EXCEL_MAX_SHEETS=10, STORAGE_GOOGLE_DRIVE_MAX_ROWS_PER_SHEET=100
    )
    ctx = _Context(settings=settings, payload=b"xlsx")

    result = extractor.extract(
        {"id": "xls1", "size": str(2 * 1024 * 1024)}, cast(ExtractionContext, ctx)
    )

    assert result.text == ""
    assert result.metadata["skipped"] == "size_limit"


def test_xlsx_extractor_extracts_text(monkeypatch: pytest.MonkeyPatch) -> None:
    extractor = XlsxExtractor()
    settings = SimpleNamespace(
        OFFICE_MAX_FILE_SIZE_MB=10, EXCEL_MAX_SHEETS=5, STORAGE_GOOGLE_DRIVE_MAX_ROWS_PER_SHEET=50
    )
    ctx = _Context(settings=settings, payload=b"xlsx")
    monkeypatch.setattr(extractor, "_extract_xlsx", lambda *_args, **_kwargs: "sheet text")

    result = extractor.extract(
        {"id": "xls1", "mimeType": XLSX_MIME_TYPE, "size": "20"}, cast(ExtractionContext, ctx)
    )

    assert result.text == "sheet text"
    assert result.file_type == "xlsx"


def test_xls_extractor_extracts_text(monkeypatch: pytest.MonkeyPatch) -> None:
    extractor = XlsExtractor()
    settings = SimpleNamespace(
        OFFICE_MAX_FILE_SIZE_MB=10, EXCEL_MAX_SHEETS=5, STORAGE_GOOGLE_DRIVE_MAX_ROWS_PER_SHEET=50
    )
    ctx = _Context(settings=settings, payload=b"xls")
    monkeypatch.setattr(extractor, "_extract_xls", lambda *_args, **_kwargs: "legacy sheet")

    result = extractor.extract(
        {"id": "xls1", "mimeType": "application/vnd.ms-excel", "size": "20"},
        cast(ExtractionContext, ctx),
    )

    assert result.text == "legacy sheet"
    assert result.file_type == "xls"
