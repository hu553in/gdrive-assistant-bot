from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

from gdrive_assistant_bot.extractors.google.docs import GoogleDocsExtractor
from gdrive_assistant_bot.extractors.google.sheets import GoogleSheetsExtractor


class _FakeDocs:
    def __init__(self, document: dict[str, Any]) -> None:
        self._document = document

    def documents(self) -> _FakeDocs:
        return self

    def get(self, documentId: str) -> _FakeDocs:
        assert documentId == "doc1"
        return self

    def execute(self) -> dict[str, Any]:
        return self._document


class _Exec:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def execute(self) -> dict[str, Any]:
        return self._payload


class _FakeValues:
    def __init__(self, values: dict[str, list[list[Any]]]) -> None:
        self._values = values

    def get(self, *, spreadsheetId: str, range: str) -> _Exec:
        assert spreadsheetId == "sheet1"
        sheet_title = range.split("'")[1]
        return _Exec({"values": self._values.get(sheet_title, [])})


class _FakeSpreadsheets:
    def __init__(self, spreadsheet: dict[str, Any], values: dict[str, list[list[Any]]]) -> None:
        self._spreadsheet = spreadsheet
        self._values = values

    def get(self, spreadsheetId: str) -> _Exec:
        assert spreadsheetId == "sheet1"
        return _Exec(self._spreadsheet)

    def values(self) -> _FakeValues:
        return _FakeValues(self._values)


class _FakeSheets:
    def __init__(self, spreadsheet: dict[str, Any], values: dict[str, list[list[Any]]]) -> None:
        self._spreadsheets = _FakeSpreadsheets(spreadsheet, values)

    def spreadsheets(self) -> _FakeSpreadsheets:
        return self._spreadsheets


@dataclass(slots=True)
class _Context:
    docs: Any
    sheets: Any
    settings: Any

    def execute_with_backoff(self, call):
        return call()


def test_google_docs_extractor_extracts_text() -> None:
    extractor = GoogleDocsExtractor()
    doc = {
        "body": {
            "content": [
                {
                    "paragraph": {
                        "elements": [
                            {"textRun": {"content": "Hello"}},
                            {"textRun": {"content": "World\u000b"}},
                        ]
                    }
                }
            ]
        }
    }
    ctx = _Context(docs=_FakeDocs(doc), sheets=None, settings=SimpleNamespace())

    result = extractor.extract({"id": "doc1", "mimeType": extractor.MIME_TYPE}, ctx)

    assert result.text == "HelloWorld"
    assert result.file_type == "gdoc"


def test_google_sheets_extractor_extracts_tables() -> None:
    extractor = GoogleSheetsExtractor()
    spreadsheet = {
        "sheets": [{"properties": {"title": "Sheet1"}}, {"properties": {"title": "Empty"}}]
    }
    values = {"Sheet1": [["A", "B"], ["1", "2"], ["", " "]], "Empty": []}
    settings = SimpleNamespace(STORAGE_GOOGLE_DRIVE_MAX_ROWS_PER_SHEET=2)
    ctx = _Context(docs=None, sheets=_FakeSheets(spreadsheet, values), settings=settings)

    result = extractor.extract({"id": "sheet1", "mimeType": extractor.MIME_TYPE}, ctx)

    assert "=== SHEET: Sheet1 ===" in result.text
    assert "A\tB" in result.text
    assert "1\t2" in result.text
    assert "Empty" not in result.text
    assert result.file_type == "gsheet"
