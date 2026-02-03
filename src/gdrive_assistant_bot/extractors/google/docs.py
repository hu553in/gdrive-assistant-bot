from typing import Any

from ..base import ExtractedContent, ExtractionContext, FileExtractor


class GoogleDocsExtractor(FileExtractor):
    """Extract text from Google Docs documents."""

    MIME_TYPE = "application/vnd.google-apps.document"

    @property
    def mime_types(self) -> list[str]:
        return [self.MIME_TYPE]

    @property
    def file_extensions(self) -> list[str]:
        return []

    def can_extract(self, file_meta: dict[str, Any]) -> bool:
        return file_meta.get("mimeType") == self.MIME_TYPE

    def extract(self, file_meta: dict[str, Any], context: ExtractionContext) -> ExtractedContent:
        doc_id = file_meta["id"]
        doc = context.execute_with_backoff(
            lambda: context.docs.documents().get(documentId=doc_id).execute()
        )
        body = (doc.get("body") or {}).get("content") or []

        out: list[str] = []
        for el in body:
            paragraph = el.get("paragraph")
            if not paragraph:
                continue
            for paragraph_el in paragraph.get("elements") or []:
                text_run = paragraph_el.get("textRun")
                if text_run and "content" in text_run:
                    out.append(text_run["content"])

        text = "".join(out).replace("\u000b", "\n").strip()
        return ExtractedContent(text=text, file_type="gdoc", metadata={})
