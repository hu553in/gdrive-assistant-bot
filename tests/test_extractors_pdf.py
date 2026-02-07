from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

import pytest

from gdrive_assistant_bot.extractors.pdf import PDFExtractor


@dataclass(slots=True)
class _Context:
    settings: Any
    payload: bytes

    def download_binary(self, _file_id: str) -> bytes:
        return self.payload


def test_pdf_extractor_can_extract_by_mime_or_extension() -> None:
    extractor = PDFExtractor()
    assert extractor.can_extract({"mimeType": "application/pdf"}) is True
    assert extractor.can_extract({"fileExtension": "pdf"}) is True
    assert (
        extractor.can_extract({"mimeType": "application/octet-stream", "name": "report.PDF"})
        is True
    )
    assert (
        extractor.can_extract({"mimeType": "application/octet-stream", "fileExtension": "bin"})
        is False
    )


def test_pdf_extractor_skips_on_size_limit() -> None:
    extractor = PDFExtractor()
    ctx = _Context(
        settings=SimpleNamespace(
            PDF_MAX_FILE_SIZE_MB=1, PDF_MAX_PAGES=100, PDF_EXTRACTION_ENGINE="pypdf"
        ),
        payload=b"%PDF",
    )

    result = extractor.extract({"id": "pdf1", "size": str(2 * 1024 * 1024)}, ctx)

    assert result.text == ""
    assert result.metadata["skipped"] == "size_limit"


def test_pdf_extractor_uses_selected_engine(monkeypatch: pytest.MonkeyPatch) -> None:
    extractor = PDFExtractor()
    ctx = _Context(
        settings=SimpleNamespace(
            PDF_MAX_FILE_SIZE_MB=10, PDF_MAX_PAGES=7, PDF_EXTRACTION_ENGINE="pdfplumber"
        ),
        payload=b"pdf-bytes",
    )

    monkeypatch.setattr(extractor, "_extract_text_pdfplumber", lambda *_args, **_kwargs: "pdf text")

    result = extractor.extract({"id": "pdf1", "size": "20"}, ctx)

    assert result.text == "pdf text"
    assert result.metadata["engine"] == "pdfplumber"
    assert result.file_type == "pdf"
