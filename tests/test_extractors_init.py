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

    assert calls == ["GoogleDocsExtractor", "GoogleSheetsExtractor"]
