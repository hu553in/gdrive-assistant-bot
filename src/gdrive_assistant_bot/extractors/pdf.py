from __future__ import annotations

import io
from typing import Any, ClassVar

import pdfplumber
from pypdf import PdfReader

from .base import ExtractedContent, ExtractionContext, FileExtractor


class PDFExtractor(FileExtractor):
    """Extract text from PDF documents."""

    MIME_TYPES: ClassVar[list[str]] = ["application/pdf", "application/x-pdf"]

    @property
    def mime_types(self) -> list[str]:
        return list(self.MIME_TYPES)

    @property
    def file_extensions(self) -> list[str]:
        return ["pdf"]

    def can_extract(self, file_meta: dict[str, Any]) -> bool:
        mime = file_meta.get("mimeType")
        if mime in self.MIME_TYPES:
            return True

        return self._extension(file_meta) == "pdf"

    def extract(self, file_meta: dict[str, Any], context: ExtractionContext) -> ExtractedContent:
        file_id = file_meta["id"]
        size = self._to_int(file_meta.get("size"))
        max_bytes = int(context.settings.PDF_MAX_FILE_SIZE_MB * 1024 * 1024)
        if size and size > max_bytes:
            return ExtractedContent(
                text="", file_type="pdf", metadata={"skipped": "size_limit", "size_bytes": size}
            )

        pdf_bytes = context.download_binary(file_id)
        max_pages = context.settings.PDF_MAX_PAGES
        engine = context.settings.PDF_EXTRACTION_ENGINE.strip().lower()
        text = self._extract_text_from_pdf(pdf_bytes, max_pages=max_pages, engine=engine)
        return ExtractedContent(
            text=text.strip(),
            file_type="pdf",
            metadata={"file_size_bytes": len(pdf_bytes), "engine": engine},
        )

    def _extract_text_from_pdf(self, pdf_bytes: bytes, *, max_pages: int, engine: str) -> str:
        if engine == "pypdf":
            return self._extract_text_pypdf(pdf_bytes, max_pages=max_pages)
        if engine == "pdfplumber":
            return self._extract_text_pdfplumber(pdf_bytes, max_pages=max_pages)
        raise ValueError(f"Unsupported PDF extraction engine: {engine}")

    @staticmethod
    def _extract_text_pypdf(pdf_bytes: bytes, *, max_pages: int) -> str:
        reader = PdfReader(io.BytesIO(pdf_bytes))
        texts: list[str] = []
        for index, page in enumerate(reader.pages, start=1):
            if max_pages and index > max_pages:
                texts.append(f"... (limited to {max_pages} pages)")
                break
            text = (page.extract_text() or "").strip()
            if text:
                texts.append(text)
        return "\n\n".join(texts)

    @staticmethod
    def _extract_text_pdfplumber(pdf_bytes: bytes, *, max_pages: int) -> str:
        texts: list[str] = []
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            for index, page in enumerate(pdf.pages, start=1):
                if max_pages and index > max_pages:
                    texts.append(f"... (limited to {max_pages} pages)")
                    break
                text = (page.extract_text() or "").strip()
                if text:
                    texts.append(text)
        return "\n\n".join(texts)

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
