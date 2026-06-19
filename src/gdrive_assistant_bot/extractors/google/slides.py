from __future__ import annotations

from typing import Any

from ..base import ExtractedContent, ExtractionContext, FileExtractor


class GoogleSlidesExtractor(FileExtractor):
    """Extract text from Google Slides presentations."""

    MIME_TYPE = "application/vnd.google-apps.presentation"

    @property
    def mime_types(self) -> list[str]:
        return [self.MIME_TYPE]

    @property
    def file_extensions(self) -> list[str]:
        return []

    def can_extract(self, file_meta: dict[str, Any]) -> bool:
        return file_meta.get("mimeType") == self.MIME_TYPE

    def extract(self, file_meta: dict[str, Any], context: ExtractionContext) -> ExtractedContent:
        file_id = file_meta["id"]
        slides_client = context.slides
        if slides_client is None:
            raise RuntimeError("Google Slides API client is not initialized")

        presentation = context.execute_with_backoff(
            lambda: slides_client.presentations().get(presentationId=file_id).execute()
        )

        slides = presentation.get("slides") or []
        lines: list[str] = []
        for index, slide in enumerate(slides, start=1):
            lines.append(f"=== SLIDE {index} ===")
            lines.extend(self._extract_slide_lines(slide))
            lines.append("")

        return ExtractedContent(
            text="\n".join(lines).strip(),
            file_type="gslides",
            metadata={"slide_count": len(slides)},
        )

    def _extract_slide_lines(self, slide: dict[str, Any]) -> list[str]:
        lines: list[str] = []
        for element in slide.get("pageElements") or []:
            lines.extend(self._extract_element_lines(element))
        return lines

    def _extract_element_lines(self, element: dict[str, Any]) -> list[str]:
        lines: list[str] = []

        shape = element.get("shape") or {}
        text_elements = (shape.get("text") or {}).get("textElements") or []
        shape_text = self._extract_text_elements(text_elements)
        if shape_text:
            lines.append(shape_text)

        table = element.get("table") or {}
        for row in table.get("tableRows") or []:
            cells: list[str] = []
            for cell in row.get("tableCells") or []:
                cell_text = self._extract_text_elements(
                    (cell.get("text") or {}).get("textElements") or []
                )
                if cell_text:
                    cells.append(cell_text)
            if cells:
                lines.append(" | ".join(cells))

        for child in (element.get("group") or {}).get("children") or []:
            lines.extend(self._extract_element_lines(child))

        return lines

    @staticmethod
    def _extract_text_elements(text_elements: list[dict[str, Any]]) -> str:
        parts: list[str] = []
        for text_element in text_elements:
            content = ((text_element.get("textRun") or {}).get("content") or "").strip()
            if content:
                parts.append(content)
        return " ".join(parts).strip()
