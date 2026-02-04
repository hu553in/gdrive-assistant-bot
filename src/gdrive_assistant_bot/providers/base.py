from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, Protocol

from ..extractors.base import ExtractionContext


class Limiter(Protocol):
    """Rate limiter interface used by providers."""

    def acquire(self) -> None: ...


class StopEvent(Protocol):
    """Stop signal interface shared across services."""

    def is_set(self) -> bool: ...


@dataclass(frozen=True, slots=True)
class FileTypeFilter:
    """File type filters used by providers when listing files."""

    mime_types: list[str]
    mime_prefixes: list[str]
    extensions: list[str]


@dataclass(frozen=True, slots=True)
class StorageFileMeta:
    """Normalized file metadata used across providers."""

    id: str
    name: str | None
    mime_type: str | None
    modified_time: str | None
    size: int | None
    extension: str | None
    raw: dict[str, Any]

    def as_extractor_meta(self) -> dict[str, Any]:
        """Return a dict matching extractor expectations (Drive-style keys)."""

        data = dict(self.raw or {})
        data.update(
            {
                "id": self.id,
                "name": self.name,
                "mimeType": self.mime_type,
                "modifiedTime": self.modified_time,
                "size": self.size,
                "fileExtension": self.extension,
            }
        )
        return data


class StorageProvider(Protocol):
    """Storage provider interface used by ingest."""

    name: str

    def list_files(
        self, file_filter: FileTypeFilter, limiter: Limiter, stop_event: StopEvent
    ) -> Iterable[StorageFileMeta]: ...

    def build_extraction_context(
        self, limiter: Limiter, stop_event: StopEvent
    ) -> ExtractionContext: ...
