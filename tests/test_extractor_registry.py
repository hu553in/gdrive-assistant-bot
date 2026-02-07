from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from gdrive_assistant_bot.extractors.base import FileExtractor
from gdrive_assistant_bot.extractors.registry import ExtractorRegistry


@dataclass(slots=True)
class _FakeExtractor(FileExtractor):
    supported_mimes: list[str]
    supported_extensions: list[str]
    prefixes: list[str]
    can_extract_result: bool = False

    @property
    def mime_types(self) -> list[str]:
        return list(self.supported_mimes)

    @property
    def file_extensions(self) -> list[str]:
        return list(self.supported_extensions)

    @property
    def mime_prefixes(self) -> list[str]:
        return list(self.prefixes)

    def can_extract(self, file_meta: dict[str, Any]) -> bool:
        _ = file_meta
        return self.can_extract_result

    def extract(self, file_meta: dict[str, Any], context: Any) -> Any:
        raise NotImplementedError


def test_registry_prefers_exact_mime_match() -> None:
    registry = ExtractorRegistry()
    exact = _FakeExtractor(supported_mimes=["text/plain"], supported_extensions=[], prefixes=[])
    fallback = _FakeExtractor(
        supported_mimes=[], supported_extensions=[], prefixes=[], can_extract_result=True
    )

    registry.register(exact)
    registry.register(fallback)

    extractor = registry.get_extractor({"mimeType": "text/plain"})
    assert extractor is exact


def test_registry_falls_back_to_can_extract() -> None:
    registry = ExtractorRegistry()
    fallback = _FakeExtractor(
        supported_mimes=[], supported_extensions=[], prefixes=[], can_extract_result=True
    )
    registry.register(fallback)

    extractor = registry.get_extractor({"mimeType": "application/unknown"})
    assert extractor is fallback


def test_registry_tracks_mimes_prefixes_and_extensions() -> None:
    registry = ExtractorRegistry()
    extractor = _FakeExtractor(
        supported_mimes=["application/test"], supported_extensions=["txt", "md"], prefixes=["text/"]
    )
    registry.register(extractor)

    assert registry.list_supported_mimes() == ["application/test"]
    assert set(registry.list_supported_extensions()) == {"txt", "md"}
    assert registry.list_mime_prefixes() == ["text/"]
