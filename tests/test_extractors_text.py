from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any, cast

from gdrive_assistant_bot.extractors.base import ExtractionContext
from gdrive_assistant_bot.extractors.text import TextBasedFileExtractor


@dataclass(slots=True)
class _Context:
    settings: Any
    payload: bytes

    def download_binary(self, _file_id: str) -> bytes:
        return self.payload


def test_text_extractor_can_extract_by_mime_or_extension() -> None:
    extractor = TextBasedFileExtractor()

    assert extractor.can_extract({"mimeType": "text/plain"}) is True
    assert extractor.can_extract({"mimeType": "application/json"}) is True
    assert (
        extractor.can_extract({"mimeType": "application/octet-stream", "fileExtension": "py"})
        is True
    )
    assert (
        extractor.can_extract({"mimeType": "application/octet-stream", "name": "notes.md"}) is True
    )
    assert (
        extractor.can_extract({"mimeType": "application/octet-stream", "fileExtension": "bin"})
        is False
    )
    assert extractor.can_extract({"mimeType": None, "fileExtension": "bin"}) is False
    assert extractor.can_extract({"mimeType": None, "fileExtension": "py"}) is True


def test_text_extractor_skips_on_size_limit() -> None:
    extractor = TextBasedFileExtractor()
    ctx = _Context(settings=SimpleNamespace(TEXT_MAX_FILE_SIZE_MB=1), payload=b"content")

    result = extractor.extract(
        {"id": "f1", "size": str(2 * 1024 * 1024)}, cast(ExtractionContext, ctx)
    )

    assert result.text == ""
    assert result.metadata["skipped"] == "size_limit"


def test_text_extractor_extracts_and_normalizes_file_type() -> None:
    extractor = TextBasedFileExtractor()
    ctx = _Context(settings=SimpleNamespace(TEXT_MAX_FILE_SIZE_MB=10), payload=b"print('ok')\n")

    result = extractor.extract(
        {"id": "f1", "mimeType": "application/octet-stream", "fileExtension": "py", "size": "12"},
        cast(ExtractionContext, ctx),
    )

    assert result.text == "print('ok')"
    assert result.file_type == "python"
    assert result.metadata["extension"] == "py"
