from __future__ import annotations

from typing import Any, ClassVar

from .base import ExtractedContent, ExtractionContext, FileExtractor


class TextBasedFileExtractor(FileExtractor):
    """Extract text from plain text and code files."""

    TEXT_MIME_PREFIXES: ClassVar[tuple[str, ...]] = ("text/",)
    EXTRA_MIME_TYPES: ClassVar[tuple[str, ...]] = (
        "application/json",
        "application/xml",
        "application/javascript",
        "application/yaml",
        "application/x-yaml",
        "application/x-python-code",
    )
    FILE_EXTENSIONS: ClassVar[frozenset[str]] = frozenset(
        {
            "txt",
            "md",
            "markdown",
            "rst",
            "log",
            "csv",
            "tsv",
            "json",
            "yaml",
            "yml",
            "toml",
            "ini",
            "cfg",
            "conf",
            "py",
            "pyw",
            "pyi",
            "js",
            "jsx",
            "ts",
            "tsx",
            "html",
            "htm",
            "css",
            "xml",
            "sh",
            "bash",
            "zsh",
            "fish",
            "rb",
            "php",
            "go",
            "rs",
            "java",
            "c",
            "h",
            "cpp",
            "hpp",
            "cs",
            "swift",
            "kt",
            "sql",
        }
    )
    TYPE_MAP: ClassVar[dict[str, str]] = {
        "py": "python",
        "pyw": "python",
        "pyi": "python",
        "js": "javascript",
        "jsx": "javascript",
        "ts": "typescript",
        "tsx": "typescript",
        "yaml": "yaml",
        "yml": "yaml",
        "md": "markdown",
        "markdown": "markdown",
        "json": "json",
        "toml": "toml",
        "sh": "shell",
        "bash": "shell",
        "zsh": "shell",
        "fish": "shell",
        "csv": "csv",
    }

    @property
    def mime_types(self) -> list[str]:
        return list(self.EXTRA_MIME_TYPES)

    @property
    def file_extensions(self) -> list[str]:
        return sorted(self.FILE_EXTENSIONS)

    @property
    def mime_prefixes(self) -> list[str]:
        return list(self.TEXT_MIME_PREFIXES)

    def can_extract(self, file_meta: dict[str, Any]) -> bool:
        mime = file_meta.get("mimeType")
        if not isinstance(mime, str):
            mime = ""
        if mime.startswith("text/") or mime in self.EXTRA_MIME_TYPES:
            return True
        extension = self._extension(file_meta)
        return bool(extension and extension in self.FILE_EXTENSIONS)

    def extract(self, file_meta: dict[str, Any], context: ExtractionContext) -> ExtractedContent:
        file_id = file_meta["id"]
        size = self._to_int(file_meta.get("size"))
        max_bytes = int(context.settings.TEXT_MAX_FILE_SIZE_MB * 1024 * 1024)
        if size and size > max_bytes:
            return ExtractedContent(
                text="", file_type="text", metadata={"skipped": "size_limit", "size_bytes": size}
            )

        content_bytes = context.download_binary(file_id)
        content = content_bytes.decode("utf-8", errors="replace").strip()
        extension = self._extension(file_meta)
        return ExtractedContent(
            text=content,
            file_type=self._normalized_file_type(extension),
            metadata={
                "original_mime": file_meta.get("mimeType"),
                "extension": extension,
                "file_size_bytes": len(content_bytes),
            },
        )

    @staticmethod
    def _to_int(value: Any) -> int | None:
        if isinstance(value, int):
            return value
        if isinstance(value, str) and value.isdigit():
            return int(value)
        return None

    @staticmethod
    def _extension(file_meta: dict[str, Any]) -> str | None:
        ext = file_meta.get("fileExtension")
        if isinstance(ext, str) and ext.strip():
            return ext.lower().lstrip(".")

        name = file_meta.get("name")
        if not isinstance(name, str) or "." not in name:
            return None
        return name.rsplit(".", 1)[-1].strip().lower() or None

    @staticmethod
    def _normalized_file_type(extension: str | None) -> str:
        if not extension:
            return "text"
        return TextBasedFileExtractor.TYPE_MAP.get(extension, "text")
