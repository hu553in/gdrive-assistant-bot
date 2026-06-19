from typing import Any

from .base import FileExtractor


class ExtractorRegistry:
    """Registry for file extractors."""

    def __init__(self) -> None:
        self._extractors: list[FileExtractor] = []
        self._mime_map: dict[str, FileExtractor] = {}
        self._mime_prefixes: set[str] = set()
        self._extensions: set[str] = set()

    def register(self, extractor: FileExtractor) -> None:
        """Register an extractor."""

        self._extractors.append(extractor)
        for mime in extractor.mime_types:
            self._mime_map[mime] = extractor
        for prefix in extractor.mime_prefixes:
            self._mime_prefixes.add(prefix)
        for ext in extractor.file_extensions:
            if ext:
                self._extensions.add(ext)

    def get_extractor(self, file_meta: dict[str, Any]) -> FileExtractor | None:
        """Find appropriate extractor for a file."""

        mime = file_meta.get("mimeType", "")

        if mime in self._mime_map:
            return self._mime_map[mime]

        for extractor in self._extractors:
            if extractor.can_extract(file_meta):
                return extractor

        return None

    def list_supported_mimes(self) -> list[str]:
        """Get all supported MIME types."""

        return list(self._mime_map.keys())

    def list_supported_extensions(self) -> list[str]:
        """Get all supported file extensions."""

        return list(self._extensions)

    def list_mime_prefixes(self) -> list[str]:
        """Get all supported MIME prefixes."""

        return list(self._mime_prefixes)


_registry = ExtractorRegistry()


def register_extractor(extractor: FileExtractor) -> None:
    """Register an extractor globally."""

    _registry.register(extractor)


def get_extractor(file_meta: dict[str, Any]) -> FileExtractor | None:
    """Get extractor for a file."""

    return _registry.get_extractor(file_meta)


def get_supported_mimes() -> list[str]:
    """Get supported MIME types."""

    return _registry.list_supported_mimes()


def get_supported_extensions() -> list[str]:
    """Get supported file extensions."""

    return _registry.list_supported_extensions()


def get_supported_mime_prefixes() -> list[str]:
    """Get supported MIME prefixes."""

    return _registry.list_mime_prefixes()
