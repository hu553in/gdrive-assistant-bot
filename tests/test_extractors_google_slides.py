from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

from gdrive_assistant_bot.extractors.google.slides import GoogleSlidesExtractor


class _Exec:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def execute(self) -> dict[str, Any]:
        return self._payload


class _FakePresentations:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def get(self, *, presentationId: str) -> _Exec:
        assert presentationId == "slides1"
        return _Exec(self._payload)


class _FakeSlides:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._presentations = _FakePresentations(payload)

    def presentations(self) -> _FakePresentations:
        return self._presentations


@dataclass(slots=True)
class _Context:
    slides: Any
    settings: Any

    def execute_with_backoff(self, call):
        return call()


def test_google_slides_extractor_extracts_text_from_shapes_tables_and_groups() -> None:
    payload = {
        "slides": [
            {
                "pageElements": [
                    {
                        "shape": {
                            "text": {
                                "textElements": [
                                    {"textRun": {"content": "Title"}},
                                    {"textRun": {"content": " line"}},
                                ]
                            }
                        }
                    },
                    {
                        "table": {
                            "tableRows": [
                                {
                                    "tableCells": [
                                        {"text": {"textElements": [{"textRun": {"content": "A"}}]}},
                                        {"text": {"textElements": [{"textRun": {"content": "B"}}]}},
                                    ]
                                }
                            ]
                        }
                    },
                    {
                        "group": {
                            "children": [
                                {
                                    "shape": {
                                        "text": {
                                            "textElements": [{"textRun": {"content": "Nested"}}]
                                        }
                                    }
                                }
                            ]
                        }
                    },
                ]
            }
        ]
    }
    extractor = GoogleSlidesExtractor()
    ctx = _Context(slides=_FakeSlides(payload), settings=SimpleNamespace())

    result = extractor.extract({"id": "slides1", "mimeType": extractor.MIME_TYPE}, ctx)

    assert "=== SLIDE 1 ===" in result.text
    assert "Title line" in result.text
    assert "A | B" in result.text
    assert "Nested" in result.text
    assert result.file_type == "gslides"
    assert result.metadata["slide_count"] == 1
