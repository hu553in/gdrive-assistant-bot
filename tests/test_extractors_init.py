from __future__ import annotations

import pytest

from gdrive_assistant_bot import extractors


def test_init_extractors_registers_once(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def fake_register(extractor) -> None:
        calls.append(extractor.__class__.__name__)

    monkeypatch.setattr(extractors, "register_extractor", fake_register)

    if hasattr(extractors.init_extractors, "_initialized"):
        delattr(extractors.init_extractors, "_initialized")

    extractors.init_extractors()
    extractors.init_extractors()

    assert calls == [
        "GoogleDocsExtractor",
        "GoogleSheetsExtractor",
        "GoogleSlidesExtractor",
        "TextBasedFileExtractor",
        "PDFExtractor",
        "DocxExtractor",
        "DocExtractor",
        "XlsxExtractor",
        "XlsExtractor",
        "PptxExtractor",
        "PptExtractor",
    ]


@pytest.mark.parametrize(
    ("toggle_name", "missing_extractor"),
    [
        ("FILE_TYPE_GDOCS_ENABLED", "GoogleDocsExtractor"),
        ("FILE_TYPE_GSHEETS_ENABLED", "GoogleSheetsExtractor"),
        ("FILE_TYPE_GSLIDES_ENABLED", "GoogleSlidesExtractor"),
        ("FILE_TYPE_TEXT_BASED_ENABLED", "TextBasedFileExtractor"),
        ("FILE_TYPE_PDF_ENABLED", "PDFExtractor"),
        ("FILE_TYPE_DOCX_ENABLED", "DocxExtractor"),
        ("FILE_TYPE_DOC_ENABLED", "DocExtractor"),
        ("FILE_TYPE_XLSX_ENABLED", "XlsxExtractor"),
        ("FILE_TYPE_XLS_ENABLED", "XlsExtractor"),
        ("FILE_TYPE_PPTX_ENABLED", "PptxExtractor"),
        ("FILE_TYPE_PPT_ENABLED", "PptExtractor"),
    ],
)
def test_init_extractors_respects_feature_toggles(
    monkeypatch: pytest.MonkeyPatch, toggle_name: str, missing_extractor: str
) -> None:
    calls: list[str] = []

    def fake_register(extractor) -> None:
        calls.append(extractor.__class__.__name__)

    monkeypatch.setattr(extractors, "register_extractor", fake_register)

    toggles = [
        "FILE_TYPE_GDOCS_ENABLED",
        "FILE_TYPE_GSHEETS_ENABLED",
        "FILE_TYPE_GSLIDES_ENABLED",
        "FILE_TYPE_TEXT_BASED_ENABLED",
        "FILE_TYPE_PDF_ENABLED",
        "FILE_TYPE_DOCX_ENABLED",
        "FILE_TYPE_DOC_ENABLED",
        "FILE_TYPE_XLSX_ENABLED",
        "FILE_TYPE_XLS_ENABLED",
        "FILE_TYPE_PPTX_ENABLED",
        "FILE_TYPE_PPT_ENABLED",
    ]
    for name in toggles:
        monkeypatch.setattr(extractors.settings, name, True)
    monkeypatch.setattr(extractors.settings, toggle_name, False)

    if hasattr(extractors.init_extractors, "_initialized"):
        delattr(extractors.init_extractors, "_initialized")

    extractors.init_extractors()

    assert missing_extractor not in calls
