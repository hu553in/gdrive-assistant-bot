from __future__ import annotations

import subprocess
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any, cast

import pytest

from gdrive_assistant_bot.extractors.base import ExtractionContext
from gdrive_assistant_bot.extractors.office.powerpoint import (
    PPTX_MIME_TYPE,
    PptExtractor,
    PptxExtractor,
)


@dataclass(slots=True)
class _Context:
    settings: Any
    payload: bytes

    def download_binary(self, _file_id: str) -> bytes:
        return self.payload


def test_pptx_extractor_can_extract_by_mime_or_extension() -> None:
    extractor = PptxExtractor()
    assert extractor.can_extract({"mimeType": PPTX_MIME_TYPE}) is True
    assert extractor.can_extract({"fileExtension": "pptx"}) is True
    assert extractor.can_extract({"fileExtension": "ppt"}) is False


def test_ppt_extractor_can_extract_by_mime_or_extension() -> None:
    extractor = PptExtractor()
    assert extractor.can_extract({"mimeType": "application/vnd.ms-powerpoint"}) is True
    assert extractor.can_extract({"fileExtension": "ppt"}) is True
    assert extractor.can_extract({"fileExtension": "pptx"}) is False


def test_pptx_extractor_extracts_text(monkeypatch: pytest.MonkeyPatch) -> None:
    extractor = PptxExtractor()
    ctx = _Context(settings=SimpleNamespace(OFFICE_MAX_FILE_SIZE_MB=10), payload=b"pptx")
    monkeypatch.setattr(extractor, "_extract_pptx", lambda _bytes: "slide text")

    result = extractor.extract(
        {"id": "pptx1", "mimeType": PPTX_MIME_TYPE, "size": "20"}, cast(ExtractionContext, ctx)
    )

    assert result.text == "slide text"
    assert result.file_type == "pptx"


def test_pptx_extractor_extracts_grouped_shapes(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Shape:
        def __init__(
            self,
            *,
            text: str = "",
            table_rows: list[list[str]] | None = None,
            children: list[_Shape] | None = None,
        ) -> None:
            self.has_text_frame = bool(text)
            self.text = text
            self.has_table = table_rows is not None
            if table_rows is not None:
                self.table = SimpleNamespace(
                    rows=[
                        SimpleNamespace(cells=[SimpleNamespace(text=value) for value in row])
                        for row in table_rows
                    ]
                )
            self.shapes = children or []

    class _Slide:
        def __init__(self, shapes: list[_Shape]) -> None:
            self.shapes = shapes

    class _Presentation:
        def __init__(self, _stream: Any) -> None:
            self.slides = [
                _Slide(
                    [
                        _Shape(
                            children=[
                                _Shape(text="Nested headline"),
                                _Shape(table_rows=[["A", "B"]]),
                            ]
                        )
                    ]
                )
            ]

    monkeypatch.setattr(
        "gdrive_assistant_bot.extractors.office.powerpoint.Presentation", _Presentation
    )

    text = PptxExtractor._extract_pptx(b"pptx")

    assert "Nested headline" in text
    assert "A | B" in text


def test_ppt_extractor_extracts_text(monkeypatch: pytest.MonkeyPatch) -> None:
    extractor = PptExtractor()
    ctx = _Context(settings=SimpleNamespace(OFFICE_MAX_FILE_SIZE_MB=10), payload=b"ppt")
    monkeypatch.setattr(extractor, "_extract_ppt", lambda _bytes: "legacy slide")

    result = extractor.extract(
        {"id": "ppt1", "mimeType": "application/vnd.ms-powerpoint", "size": "20"},
        cast(ExtractionContext, ctx),
    )

    assert result.text == "legacy slide"
    assert result.file_type == "ppt"


def test_ppt_extractor_uses_catppt(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=0, stdout=b"legacy ppt", stderr=b""),
    )

    assert PptExtractor._extract_ppt(b"binary") == "legacy ppt"


def test_ppt_extractor_raises_when_catppt_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise(*_args, **_kwargs):
        raise FileNotFoundError

    monkeypatch.setattr(subprocess, "run", _raise)

    with pytest.raises(RuntimeError, match="catppt"):
        PptExtractor._extract_ppt(b"binary")
