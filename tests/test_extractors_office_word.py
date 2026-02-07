from __future__ import annotations

import subprocess
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any, cast

import pytest

from gdrive_assistant_bot.extractors.base import ExtractionContext
from gdrive_assistant_bot.extractors.office.word import DOCX_MIME_TYPE, DocExtractor, DocxExtractor


@dataclass(slots=True)
class _Context:
    settings: Any
    payload: bytes

    def download_binary(self, _file_id: str) -> bytes:
        return self.payload


def test_docx_extractor_can_extract_by_mime_or_extension() -> None:
    extractor = DocxExtractor()
    assert extractor.can_extract({"mimeType": DOCX_MIME_TYPE}) is True
    assert extractor.can_extract({"fileExtension": "docx"}) is True
    assert extractor.can_extract({"fileExtension": "doc"}) is False


def test_doc_extractor_can_extract_by_mime_or_extension() -> None:
    extractor = DocExtractor()
    assert extractor.can_extract({"mimeType": "application/msword"}) is True
    assert extractor.can_extract({"fileExtension": "doc"}) is True
    assert extractor.can_extract({"fileExtension": "docx"}) is False


def test_docx_extractor_skips_on_size_limit() -> None:
    extractor = DocxExtractor()
    ctx = _Context(settings=SimpleNamespace(OFFICE_MAX_FILE_SIZE_MB=1), payload=b"docx")

    result = extractor.extract(
        {"id": "docx1", "size": str(2 * 1024 * 1024)}, cast(ExtractionContext, ctx)
    )

    assert result.text == ""
    assert result.metadata["skipped"] == "size_limit"


def test_docx_extractor_extracts_text(monkeypatch: pytest.MonkeyPatch) -> None:
    extractor = DocxExtractor()
    ctx = _Context(settings=SimpleNamespace(OFFICE_MAX_FILE_SIZE_MB=10), payload=b"docx")
    monkeypatch.setattr(extractor, "_extract_docx", lambda _bytes: "hello docx")

    result = extractor.extract(
        {"id": "docx1", "mimeType": DOCX_MIME_TYPE, "size": "16"}, cast(ExtractionContext, ctx)
    )

    assert result.text == "hello docx"
    assert result.file_type == "docx"


def test_doc_extractor_extracts_text(monkeypatch: pytest.MonkeyPatch) -> None:
    extractor = DocExtractor()
    ctx = _Context(settings=SimpleNamespace(OFFICE_MAX_FILE_SIZE_MB=10), payload=b"doc")
    monkeypatch.setattr(extractor, "_extract_doc", lambda _bytes: "hello doc")

    result = extractor.extract(
        {"id": "doc1", "mimeType": "application/msword", "size": "16"}, cast(ExtractionContext, ctx)
    )

    assert result.text == "hello doc"
    assert result.file_type == "doc"


def test_doc_extractor_uses_catdoc(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=0, stdout=b"legacy text", stderr=b""),
    )

    assert DocExtractor._extract_doc(b"binary") == "legacy text"


def test_doc_extractor_raises_when_catdoc_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise(*_args, **_kwargs):
        raise FileNotFoundError

    monkeypatch.setattr(subprocess, "run", _raise)

    with pytest.raises(RuntimeError, match="catdoc"):
        DocExtractor._extract_doc(b"binary")
