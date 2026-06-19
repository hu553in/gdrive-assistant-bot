from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True, slots=True)
class ExtractedContent:
    """Result of file content extraction."""

    text: str
    file_type: str
    metadata: dict[str, Any]


class FileExtractor(ABC):
    """Abstract base class for file content extractors."""

    @property
    @abstractmethod
    def mime_types(self) -> list[str]:
        """List of supported MIME types."""

    @property
    @abstractmethod
    def file_extensions(self) -> list[str]:
        """List of supported file extensions (for non-Google files)."""

    @property
    def mime_prefixes(self) -> list[str]:
        """List of supported MIME type prefixes (for Google Drive queries)."""

        return []

    @abstractmethod
    def can_extract(self, file_meta: dict[str, Any]) -> bool:
        """Check if this extractor can handle the given file."""

    @abstractmethod
    def extract(self, file_meta: dict[str, Any], context: "ExtractionContext") -> ExtractedContent:
        """Extract text content from the file."""


class ExtractionContext(Protocol):
    """Protocol for extraction context (rate limiter, clients, helpers)."""

    limiter: Any
    stop_event: Any
    settings: Any

    drive: Any | None
    docs: Any | None
    sheets: Any | None
    slides: Any | None

    execute_with_backoff: Any
    download_binary: Any
    download_export: Any
