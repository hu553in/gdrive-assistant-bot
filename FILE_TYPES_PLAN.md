# File Type Support Expansion & Modular Architecture Plan

## Current State Analysis

**Project:** Google Drive assistant bot with RAG capabilities
**Current file support:** Google Docs, Google Sheets
**Planned file types (from README):**
1. Google Slides
2. Text-based files (configuration files, source code, plain text)
3. PDF documents
4. Microsoft Office formats (DOC, DOCX, XLS, XLSX, PPT, PPTX)

**Current Architecture Issues:**
- File extraction logic is hardcoded in `ingest.py` with specific functions
  `_extract_doc_text()` and `_extract_sheet_text()`
- MIME type constants are defined as module-level constants
- Adding new file types requires modifying multiple places in `ingest.py`
- No abstraction layer for file type handlers

---

## Proposed Modular Architecture

### 1. Directory Structure Restructure

```
src/gdrive_assistant_bot/
|-- __init__.py
|-- bot.py                      # Thin Telegram entrypoint
|-- ingest.py                   # Thin ingest entrypoint
|-- settings.py                 # Configuration (updated)
|-- logging.py                  # Logging setup
|-- health.py                   # Health server
|-- rag.py                      # RAG store
|-- adapters/                   # NEW: External adapters
|   |-- __init__.py
|   |-- llm.py                  # LLM client factory
|   `-- telegram.py             # Telegram handlers
|-- core/                       # NEW: Domain services
|   |-- __init__.py
|   |-- ingest/
|   |   |-- __init__.py
|   |   |-- limiter.py          # Rate limiter
|   |   |-- models.py           # Ingest types
|   |   `-- service.py          # Ingest service
|   `-- qa/
|       |-- __init__.py
|       `-- service.py          # Q&A service
|-- providers/                  # NEW: Storage providers
|   |-- __init__.py
|   |-- base.py                 # Provider interface
|   |-- registry.py             # Provider registry
|   `-- google_drive/
|       |-- __init__.py
|       |-- api.py              # Google API helpers
|       |-- clients.py          # Thread-local clients
|       `-- provider.py         # Google Drive provider
`-- extractors/                 # File extraction modules
    |-- __init__.py             # init_extractors() registers all extractors
    |-- base.py                 # Abstract base class
    |-- registry.py             # Extractor registry + Drive query terms
    |-- google/                 # Google Workspace files
    |   |-- __init__.py
    |   |-- docs.py             # Google Docs extractor
    |   |-- sheets.py           # Google Sheets extractor
    |   `-- slides.py           # Google Slides extractor
    |-- office/                 # Microsoft Office files
    |   |-- __init__.py
    |   |-- word.py             # DOC, DOCX
    |   |-- excel.py            # XLS, XLSX
    |   `-- powerpoint.py       # PPT, PPTX
    |-- pdf.py                  # PDF documents
    `-- text.py                 # Plain text, code files
```

---

## 2. Core Abstractions

### 2.1 Base Extractor Interface (`extractors/base.py`)

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True, slots=True)
class ExtractedContent:
    """Result of file content extraction."""
    text: str
    file_type: str  # normalized type identifier
    metadata: dict[str, Any]  # additional metadata


class FileExtractor(ABC):
    """Abstract base class for file content extractors."""

    @property
    @abstractmethod
    def mime_types(self) -> list[str]:
        """List of supported MIME types."""
        pass

    @property
    @abstractmethod
    def file_extensions(self) -> list[str]:
        """List of supported file extensions (for non-Google files)."""
        pass

    @property
    def mime_prefixes(self) -> list[str]:
        """List of supported MIME type prefixes (for Drive queries)."""
        return []

    @abstractmethod
    def can_extract(self, file_meta: dict[str, Any]) -> bool:
        """Check if this extractor can handle the given file."""
        pass

    @abstractmethod
    def extract(self, file_meta: dict[str, Any], context: ExtractionContext) -> ExtractedContent:
        """Extract text content from the file."""
        pass


class ExtractionContext(Protocol):
    """Protocol for extraction context (rate limiter, clients, helpers)."""
    limiter: Any  # RateLimiter
    stop_event: Any
    settings: Any

    # Google API clients (for Google Workspace files)
    drive: Any | None
    docs: Any | None
    sheets: Any | None
    slides: Any | None

    # Shared helpers
    execute_with_backoff: Any
    download_binary: Any
    download_export: Any
```

### 2.2 Extractor Registry (`extractors/registry.py`)

```python
from typing import Any
from .base import FileExtractor


class ExtractorRegistry:
    """Registry for file extractors."""

    def __init__(self) -> None:
        self._extractors: list[FileExtractor] = []
        self._mime_map: dict[str, FileExtractor] = {}
        self._mime_prefixes: set[str] = set()

    def register(self, extractor: FileExtractor) -> None:
        """Register an extractor."""
        self._extractors.append(extractor)
        for mime in extractor.mime_types:
            self._mime_map[mime] = extractor
        for prefix in extractor.mime_prefixes:
            self._mime_prefixes.add(prefix)

    def get_extractor(self, file_meta: dict[str, Any]) -> FileExtractor | None:
        """Find appropriate extractor for a file."""
        mime = file_meta.get("mimeType", "")

        # Direct MIME type match
        if mime in self._mime_map:
            return self._mime_map[mime]

        # Check via extractor's can_extract method
        for extractor in self._extractors:
            if extractor.can_extract(file_meta):
                return extractor

        return None

    def list_supported_mimes(self) -> list[str]:
        """Get all supported MIME types."""
        return list(self._mime_map.keys())

    def list_drive_query_terms(self) -> list[str]:
        """Build Drive query terms from supported types/prefixes."""
        terms: list[str] = []
        for mime in self._mime_map:
            terms.append(f"mimeType='{mime}'")
        for prefix in sorted(self._mime_prefixes):
            terms.append(f"mimeType contains '{prefix}'")
        return terms


# Global registry instance
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


def get_drive_query_terms() -> list[str]:
    """Get Drive query terms for supported MIME types."""
    return _registry.list_drive_query_terms()
```

---

### 2.3 Shared Google API Helpers (`providers/google_drive/api.py`)

Move the retry/backoff and download logic out of `ingest.py` so every extractor
uses the same limiter and error handling. This avoids copy/pasting
`MediaIoBaseDownload` loops that currently bypass the rate limiter.

Key helpers:
- `execute_with_backoff(call)` -> reuse the existing logic from `ingest.py`
  in a shared module to avoid circular imports and use `context.limiter`
  internally.
- `download_request(request, limiter, stop_event)` -> wraps
  `MediaIoBaseDownload.next_chunk()` with limiter acquisition and backoff,
  and checks `stop_event` between chunks.
- `download_export(drive, file_id, mime_type, limiter, stop_event)` -> calls
  `drive.files().export(...)` and downloads via `download_request(...)`.
- `download_binary(drive, file_id, limiter, stop_event)` -> calls
  `drive.files().get_media(...)` and downloads via `download_request(...)`.

`ExtractionContext` can bind these helpers into `ctx.download_export()` and
`ctx.download_binary()` for simpler extractor code.

This keeps extractors focused on parsing, not transport concerns.

---

### 2.4 Extractor Initialization (`extractors/__init__.py`)

Provide a single entry point that registers extractors based on settings, so
`ingest.py` can call `init_extractors()` once on startup.

```python
from .google.docs import GoogleDocsExtractor
from .google.sheets import GoogleSheetsExtractor
from .google.slides import GoogleSlidesExtractor
from .office.word import WordExtractor
from .office.excel import ExcelExtractor
from .office.powerpoint import PowerPointExtractor
from .pdf import PDFExtractor
from .text import TextFileExtractor
from .registry import register_extractor
from ..settings import settings


def init_extractors() -> None:
    register_extractor(GoogleDocsExtractor())
    register_extractor(GoogleSheetsExtractor())
    if settings.GOOGLE_SLIDES_ENABLED:
        register_extractor(GoogleSlidesExtractor())
    if settings.TEXT_FILES_ENABLED:
        register_extractor(TextFileExtractor())
    if settings.PDF_ENABLED:
        register_extractor(PDFExtractor())
    if settings.OFFICE_ENABLED:
        register_extractor(WordExtractor())
        register_extractor(ExcelExtractor())
        register_extractor(PowerPointExtractor())
```

---

## 3. Implementation Plan by File Type

### 3.1 Google Slides (`extractors/google/slides.py`)

**MIME Type:** `application/vnd.google-apps.presentation`

**Implementation:**
```python
from typing import Any
from ..base import ExtractedContent, FileExtractor
from ..registry import register_extractor


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

    def extract(self, file_meta: dict[str, Any], context: Any) -> ExtractedContent:
        """Extract text from all slides.

        Uses Google Slides API to iterate through slides and extract:
        - Slide titles (if present)
        - Text from all shapes/elements on each slide
        """
        file_id = file_meta["id"]
        presentation = context.execute_with_backoff(
            lambda: context.slides.presentations().get(presentationId=file_id).execute()
        )

        slides = presentation.get("slides", [])
        lines: list[str] = []

        for i, slide in enumerate(slides, 1):
            lines.append(f"=== SLIDE {i} ===")

            # Extract from page elements
            for element in slide.get("pageElements", []):
                text = self._extract_text_from_element(element)
                if text:
                    lines.append(text)

            lines.append("")

        return ExtractedContent(
            text="\n".join(lines).strip(),
            file_type="gslides",
            metadata={"slide_count": len(slides)}
        )

    def _extract_text_from_element(self, element: dict) -> str:
        """Recursively extract text from a page element."""
        texts: list[str] = []

        # Check for text in shape
        shape = element.get("shape", {})
        text_content = shape.get("text", {})

        for text_element in text_content.get("textElements", []):
            text_run = text_element.get("textRun", {})
            content = text_run.get("content", "").strip()
            if content:
                texts.append(content)

        # Handle groups recursively
        if "group" in element:
            for child in element["group"].get("children", []):
                child_text = self._extract_text_from_element(child)
                if child_text:
                    texts.append(child_text)

        return " ".join(texts)

# Register on module load
register_extractor(GoogleSlidesExtractor())
```

**Dependencies:**
- Add Google Slides API client initialization in `_get_thread_clients()`
- Verify scopes; if `drive.readonly` is insufficient, add
  `https://www.googleapis.com/auth/presentations.readonly`
- Enable the Google Slides API in the Google Cloud project used by the
  service account (same as Docs/Sheets)

**Configuration:**
- No new settings needed

---

### 3.2 Text-Based Files (`extractors/text.py`)

**MIME Types:**
- `text/plain`
- `text/markdown`
- `text/x-python`
- `application/json`
- `text/yaml`, `text/x-yaml`, `application/yaml`
- `text/xml`
- `text/css`
- `text/javascript`, `application/javascript`
- Many more code/config file types

**Implementation:**
```python
from typing import Any
from ..base import ExtractedContent, FileExtractor
from ..registry import register_extractor


class TextFileExtractor(FileExtractor):
    """Extract text from plain text and code files."""

    # MIME prefixes allowed by Drive query ("mimeType contains 'text/'")
    TEXT_MIME_PREFIXES = ["text/"]

    # Explicit extra MIME types that are text but not under "text/"
    EXTRA_MIME_TYPES = [
        "application/json",
        "application/xml",
        "application/javascript",
        "application/yaml",
        "application/x-yaml",
        "application/x-python-code",
    ]

    # Common code extensions
    CODE_EXTENSIONS = {
        # Python
        ".py", ".pyw", ".pyi", ".pyx", ".pxd", ".pxi",
        # Web
        ".html", ".htm", ".css", ".js", ".jsx", ".ts", ".tsx", ".json",
        # Config
        ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf", ".config",
        # Shell/Scripts
        ".sh", ".bash", ".zsh", ".fish", ".ps1", ".bat", ".cmd",
        # Data
        ".csv", ".tsv", ".md", ".markdown", ".rst", ".txt", ".log",
        # Other languages
        ".rb", ".php", ".go", ".rs", ".java", ".cpp", ".c", ".h",
        ".cs", ".swift", ".kt", ".scala", ".pl", ".lua", ".r",
    }

    @property
    def mime_types(self) -> list[str]:
        return list(self.EXTRA_MIME_TYPES)

    @property
    def file_extensions(self) -> list[str]:
        return list(self.CODE_EXTENSIONS)

    @property
    def mime_prefixes(self) -> list[str]:
        return list(self.TEXT_MIME_PREFIXES)

    def can_extract(self, file_meta: dict[str, Any]) -> bool:
        mime = file_meta.get("mimeType", "")
        name = file_meta.get("name", "")
        ext = file_meta.get("fileExtension")

        # Check MIME type patterns
        if mime.startswith("text/") or mime in self.EXTRA_MIME_TYPES:
            return True

        # Check extension
        if not ext:
            ext = "." + name.split(".")[-1].lower() if "." in name else ""
        else:
            ext = f".{ext.lower()}"
        return ext in self.CODE_EXTENSIONS

    def extract(self, file_meta: dict[str, Any], context: Any) -> ExtractedContent:
        """Download and read text file content.

        Uses Google Drive API get_media (export is only for Google-native docs).
        """
        file_id = file_meta["id"]
        name = file_meta.get("name", "")
        mime = file_meta.get("mimeType", "")
        size = int(file_meta.get("size") or 0)

        max_bytes = int(context.settings.TEXT_MAX_FILE_SIZE_MB * 1024 * 1024)
        if size and size > max_bytes:
            return ExtractedContent(
                text="",
                file_type="text",
                metadata={"skipped": "size_limit", "size_bytes": size},
            )
        content_bytes = context.download_binary(file_id)
        content = content_bytes.decode("utf-8", errors="replace")

        # Determine file type for metadata
        ext = "." + name.split(".")[-1].lower() if "." in name else ".txt"
        file_type = self._get_file_type(ext)

        return ExtractedContent(
            text=content.strip(),
            file_type=file_type,
            metadata={
                "original_mime": mime,
                "extension": ext,
            }
        )

    def _get_file_type(self, ext: str) -> str:
        """Map extension to normalized file type."""
        type_map = {
            ".py": "python",
            ".pyw": "python",
            ".pyi": "python",
            ".js": "javascript",
            ".jsx": "javascript",
            ".ts": "typescript",
            ".tsx": "typescript",
            ".json": "json",
            ".yaml": "yaml",
            ".yml": "yaml",
            ".toml": "toml",
            ".md": "markdown",
            ".markdown": "markdown",
            ".txt": "text",
            ".csv": "csv",
            ".sh": "shell",
            ".bash": "shell",
        }
        return type_map.get(ext, "text")


register_extractor(TextFileExtractor())
```

**Dependencies:**
- No new external dependencies
- Uses existing Google Drive API

**Configuration:**
- Optional: `TEXT_MAX_FILE_SIZE_MB` (default: 10) - skip files larger than this

---

### 3.3 PDF Documents (`extractors/pdf.py`)

**MIME Types:**
- `application/pdf`
- `application/x-pdf`

**Implementation:**
```python
from typing import Any
from ..base import ExtractedContent, FileExtractor
from ..registry import register_extractor


class PDFExtractor(FileExtractor):
    """Extract text from PDF documents."""

    MIME_TYPES = ["application/pdf", "application/x-pdf"]

    @property
    def mime_types(self) -> list[str]:
        return self.MIME_TYPES

    @property
    def file_extensions(self) -> list[str]:
        return [".pdf"]

    def can_extract(self, file_meta: dict[str, Any]) -> bool:
        return file_meta.get("mimeType") in self.MIME_TYPES

    def extract(self, file_meta: dict[str, Any], context: Any) -> ExtractedContent:
        """Extract text from PDF using pypdf or pdfplumber.

        For Google Drive, download the PDF binary then extract text.
        """
        file_id = file_meta["id"]
        size = int(file_meta.get("size") or 0)

        max_bytes = int(context.settings.PDF_MAX_FILE_SIZE_MB * 1024 * 1024)
        if size and size > max_bytes:
            return ExtractedContent(
                text="",
                file_type="pdf",
                metadata={"skipped": "size_limit", "size_bytes": size},
            )

        # Download PDF binary
        pdf_bytes = context.download_binary(file_id)

        # Extract text
        text = self._extract_text_from_pdf(pdf_bytes, context.settings.PDF_MAX_PAGES)

        return ExtractedContent(
            text=text.strip(),
            file_type="pdf",
            metadata={"file_size_bytes": len(pdf_bytes)}
        )

    def _extract_text_from_pdf(self, pdf_bytes: bytes, max_pages: int) -> str:
        """Extract text using pypdf (lightweight) or pdfplumber (better for complex layouts)."""
        try:
            from pypdf import PdfReader
            import io

            reader = PdfReader(io.BytesIO(pdf_bytes))
            texts: list[str] = []

            for i, page in enumerate(reader.pages, 1):
                if max_pages and i > max_pages:
                    texts.append(f"... (limited to {max_pages} pages)")
                    break
                text = page.extract_text()
                if text:
                    texts.append(text)

            return "\n\n".join(texts)
        except ImportError:
            raise RuntimeError("PDF extraction requires 'pypdf'. Install with: pip install pypdf")


register_extractor(PDFExtractor())
```

**Dependencies:**
- Add to `pyproject.toml`:
  ```toml
dependencies = [
    ...
    "pypdf",  # or "pdfplumber" for complex PDFs
]
```

**Alternative:** Use `pdfplumber` for better table extraction:
```python
import pdfplumber
import io

def _extract_text_from_pdf(self, pdf_bytes: bytes, max_pages: int) -> str:
    texts: list[str] = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for i, page in enumerate(pdf.pages, 1):
            if max_pages and i > max_pages:
                texts.append(f"... (limited to {max_pages} pages)")
                break
            text = page.extract_text()
            if text:
                texts.append(f"=== PAGE {i} ===\n{text}")
    return "\n\n".join(texts)
```

**Configuration:**
- Optional: `PDF_MAX_PAGES` (default: 100) - skip PDFs with more pages
- Optional: `PDF_MAX_FILE_SIZE_MB` (default: 50)
- Optional: `PDF_EXTRACTION_ENGINE` - choose between `pypdf` and `pdfplumber`

---

### 3.4 Microsoft Office - Word (`extractors/office/word.py`)

**MIME Types:**
- `application/msword` (.doc)
- `application/vnd.openxmlformats-officedocument.wordprocessingml.document` (.docx)

**Implementation:**
```python
from typing import Any
from ..base import ExtractedContent, FileExtractor
from ..registry import register_extractor


class WordExtractor(FileExtractor):
    """Extract text from Microsoft Word documents (.doc and .docx)."""

    MIME_TYPES = [
        "application/msword",  # .doc
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",  # .docx
    ]

    @property
    def mime_types(self) -> list[str]:
        return self.MIME_TYPES

    @property
    def file_extensions(self) -> list[str]:
        return [".doc", ".docx"]

    def can_extract(self, file_meta: dict[str, Any]) -> bool:
        return file_meta.get("mimeType") in self.MIME_TYPES

    def extract(self, file_meta: dict[str, Any], context: Any) -> ExtractedContent:
        """Extract text from Word document.

        Strategy:
        1. Download binary via Drive get_media
        2. Use python-docx for .docx
        3. Use textract (or antiword) for legacy .doc (optional)
        """
        file_id = file_meta["id"]
        mime = file_meta.get("mimeType", "")
        size = int(file_meta.get("size") or 0)

        max_bytes = int(context.settings.OFFICE_MAX_FILE_SIZE_MB * 1024 * 1024)
        if size and size > max_bytes:
            return ExtractedContent(
                text="",
                file_type="docx" if "openxml" in mime else "doc",
                metadata={"skipped": "size_limit", "size_bytes": size},
            )

        text = self._extract_from_binary(file_id, mime, context)

        return ExtractedContent(
            text=text.strip(),
            file_type="docx" if "openxml" in mime else "doc",
            metadata={"mime_type": mime}
        )

    def _extract_from_binary(self, file_id: str, mime: str, context: Any) -> str:
        """Download and extract from binary file."""
        doc_bytes = context.download_binary(file_id)

        if "openxml" in mime:  # .docx
            return self._extract_docx(doc_bytes)
        else:  # .doc
            return self._extract_doc(doc_bytes)

    def _extract_docx(self, docx_bytes: bytes) -> str:
        """Extract text from .docx using python-docx."""
        try:
            from docx import Document
            import io

            doc = Document(io.BytesIO(docx_bytes))
            paragraphs: list[str] = []

            for para in doc.paragraphs:
                text = para.text.strip()
                if text:
                    paragraphs.append(text)

            # Extract from tables
            for table in doc.tables:
                for row in table.rows:
                    row_text = " | ".join(
                        cell.text.strip() for cell in row.cells if cell.text.strip()
                    )
                    if row_text:
                        paragraphs.append(row_text)

            return "\n".join(paragraphs)
        except ImportError:
            raise RuntimeError("DOCX extraction requires 'python-docx'. Install with: pip install python-docx")

    def _extract_doc(self, doc_bytes: bytes) -> str:
        """Extract text from .doc binary format.

        Options:
        1. Use textract library (supports many formats)
        2. Use antiword via subprocess (requires binary installation)
        3. Use olefile to read WordDocument stream (complex)

        Recommended: textract for simplicity
        """
        try:
            import textract
            import tempfile
            import os

            # Write to temp file (textract needs file path)
            with tempfile.NamedTemporaryFile(delete=False, suffix=".doc") as tmp:
                tmp.write(doc_bytes)
                tmp_path = tmp.name

            try:
                text = textract.process(tmp_path).decode("utf-8", errors="replace")
                return text
            finally:
                os.unlink(tmp_path)

        except ImportError:
            raise RuntimeError("DOC extraction requires 'textract'. Install with: pip install textract")


register_extractor(WordExtractor())
```

**Dependencies:**
```toml
dependencies = [
    ...
    "python-docx",  # For .docx files
    "textract",     # For .doc files (optional, heavier)
]
```

**Configuration:**
- Optional: `OFFICE_MAX_FILE_SIZE_MB` (default: 50)

Note: `.doc` support via `textract` often needs OS packages (antiword, catdoc).
If you do not need legacy formats, skip `textract` entirely.

---

### 3.5 Microsoft Office - Excel (`extractors/office/excel.py`)

**MIME Types:**
- `application/vnd.ms-excel` (.xls)
- `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet` (.xlsx)

**Implementation:**
```python
from typing import Any
from ..base import ExtractedContent, FileExtractor
from ..registry import register_extractor


class ExcelExtractor(FileExtractor):
    """Extract text from Microsoft Excel spreadsheets (.xls and .xlsx)."""

    MIME_TYPES = [
        "application/vnd.ms-excel",  # .xls
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",  # .xlsx
    ]

    MAX_SHEETS = 50  # Configurable via settings
    MAX_ROWS_PER_SHEET = 2000  # Already configured in settings.py

    @property
    def mime_types(self) -> list[str]:
        return self.MIME_TYPES

    @property
    def file_extensions(self) -> list[str]:
        return [".xls", ".xlsx"]

    def can_extract(self, file_meta: dict[str, Any]) -> bool:
        return file_meta.get("mimeType") in self.MIME_TYPES

    def extract(self, file_meta: dict[str, Any], context: Any) -> ExtractedContent:
        """Extract text from Excel file.

        Similar to Google Sheets extractor but for Excel files.
        Uses openpyxl for .xlsx and xlrd for .xls.
        """
        file_id = file_meta["id"]
        mime = file_meta.get("mimeType", "")
        size = int(file_meta.get("size") or 0)

        max_bytes = int(context.settings.OFFICE_MAX_FILE_SIZE_MB * 1024 * 1024)
        if size and size > max_bytes:
            return ExtractedContent(
                text="",
                file_type="xlsx" if "openxml" in mime else "xls",
                metadata={"skipped": "size_limit", "size_bytes": size},
            )

        # Download binary
        excel_bytes = context.download_binary(file_id)

        # Extract based on format
        if "openxml" in mime:
            text = self._extract_xlsx(excel_bytes)
        else:
            text = self._extract_xls(excel_bytes)

        return ExtractedContent(
            text=text.strip(),
            file_type="xlsx" if "openxml" in mime else "xls",
            metadata={"mime_type": mime}
        )

    def _extract_xlsx(self, xlsx_bytes: bytes) -> str:
        """Extract from .xlsx using openpyxl."""
        try:
            from openpyxl import load_workbook
            import io

            wb = load_workbook(io.BytesIO(xlsx_bytes), read_only=True, data_only=True)
            lines: list[str] = []

            sheet_count = 0
            for sheet_name in wb.sheetnames:
                if sheet_count >= self.MAX_SHEETS:
                    lines.append(f"... (limited to {self.MAX_SHEETS} sheets)")
                    break

                sheet_count += 1
                lines.append(f"=== SHEET: {sheet_name} ===")

                sheet = wb[sheet_name]
                row_count = 0

                for row in sheet.iter_rows():
                    if row_count >= self.MAX_ROWS_PER_SHEET:
                        lines.append(f"... (limited to {self.MAX_ROWS_PER_SHEET} rows)")
                        break

                    row_count += 1
                    row_values = [str(cell.value) if cell.value is not None else "" for cell in row]
                    row_text = "\t".join(v.strip() for v in row_values if v.strip())

                    if row_text:
                        lines.append(row_text)

                lines.append("")

            return "\n".join(lines)

        except ImportError:
            raise RuntimeError("XLSX extraction requires 'openpyxl'. Install with: pip install openpyxl")

    def _extract_xls(self, xls_bytes: bytes) -> str:
        """Extract from .xls using xlrd."""
        try:
            import xlrd
            import io

            wb = xlrd.open_workbook(file_contents=xls_bytes)
            lines: list[str] = []

            sheet_count = 0
            for sheet_idx in range(wb.nsheets):
                if sheet_count >= self.MAX_SHEETS:
                    lines.append(f"... (limited to {self.MAX_SHEETS} sheets)")
                    break

                sheet_count += 1
                sheet = wb.sheet_by_index(sheet_idx)
                lines.append(f"=== SHEET: {sheet.name} ===")

                row_count = min(sheet.nrows, self.MAX_ROWS_PER_SHEET)
                if sheet.nrows > self.MAX_ROWS_PER_SHEET:
                    row_count = self.MAX_ROWS_PER_SHEET

                for row_idx in range(row_count):
                    row_values = []
                    for col_idx in range(sheet.ncols):
                        cell = sheet.cell(row_idx, col_idx)
                        if cell.value is not None:
                            row_values.append(str(cell.value))

                    row_text = "\t".join(v.strip() for v in row_values if v.strip())
                    if row_text:
                        lines.append(row_text)

                if sheet.nrows > self.MAX_ROWS_PER_SHEET:
                    lines.append(f"... (limited to {self.MAX_ROWS_PER_SHEET} rows, {sheet.nrows} total)")

                lines.append("")

            return "\n".join(lines)

        except ImportError:
            raise RuntimeError("XLS extraction requires 'xlrd'. Install with: pip install xlrd")


register_extractor(ExcelExtractor())
```

**Dependencies:**
```toml
dependencies = [
    ...
    "openpyxl",  # For .xlsx files
    "xlrd",      # For .xls files
]
```

**Configuration:**
- Reuse existing `STORAGE_GOOGLE_DRIVE_MAX_ROWS_PER_SHEET` setting
- Add: `EXCEL_MAX_SHEETS` (default: 50)

---

### 3.6 Microsoft Office - PowerPoint (`extractors/office/powerpoint.py`)

**MIME Types:**
- `application/vnd.ms-powerpoint` (.ppt)
- `application/vnd.openxmlformats-officedocument.presentationml.presentation` (.pptx)

**Implementation:**
```python
from typing import Any
from ..base import ExtractedContent, FileExtractor
from ..registry import register_extractor


class PowerPointExtractor(FileExtractor):
    """Extract text from Microsoft PowerPoint presentations (.ppt and .pptx)."""

    MIME_TYPES = [
        "application/vnd.ms-powerpoint",  # .ppt
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",  # .pptx
    ]

    @property
    def mime_types(self) -> list[str]:
        return self.MIME_TYPES

    @property
    def file_extensions(self) -> list[str]:
        return [".ppt", ".pptx"]

    def can_extract(self, file_meta: dict[str, Any]) -> bool:
        return file_meta.get("mimeType") in self.MIME_TYPES

    def extract(self, file_meta: dict[str, Any], context: Any) -> ExtractedContent:
        """Extract text from PowerPoint file."""
        file_id = file_meta["id"]
        mime = file_meta.get("mimeType", "")
        size = int(file_meta.get("size") or 0)

        max_bytes = int(context.settings.OFFICE_MAX_FILE_SIZE_MB * 1024 * 1024)
        if size and size > max_bytes:
            return ExtractedContent(
                text="",
                file_type="pptx" if "openxml" in mime else "ppt",
                metadata={"skipped": "size_limit", "size_bytes": size},
            )

        # Download binary
        ppt_bytes = context.download_binary(file_id)

        # Extract based on format
        if "openxml" in mime:
            text = self._extract_pptx(ppt_bytes)
        else:
            text = self._extract_ppt(ppt_bytes)

        return ExtractedContent(
            text=text.strip(),
            file_type="pptx" if "openxml" in mime else "ppt",
            metadata={"mime_type": mime}
        )

    def _extract_pptx(self, pptx_bytes: bytes) -> str:
        """Extract from .pptx using python-pptx."""
        try:
            from pptx import Presentation
            import io

            prs = Presentation(io.BytesIO(pptx_bytes))
            lines: list[str] = []

            for i, slide in enumerate(prs.slides, 1):
                lines.append(f"=== SLIDE {i} ===")

                # Extract from all shapes
                for shape in slide.shapes:
                    if hasattr(shape, "text") and shape.text.strip():
                        lines.append(shape.text.strip())
                lines.append("")

            return "\n".join(lines)

        except ImportError:
            raise RuntimeError("PPTX extraction requires 'python-pptx'. Install with: pip install python-pptx")

    def _extract_ppt(self, ppt_bytes: bytes) -> str:
        """Extract from .ppt binary format.

        Options:
        1. Use textract (recommended)
        2. Use antiword/catppt via subprocess
        3. Use olefile directly (complex)
        """
        try:
            import textract
            import tempfile
            import os

            with tempfile.NamedTemporaryFile(delete=False, suffix=".ppt") as tmp:
                tmp.write(ppt_bytes)
                tmp_path = tmp.name

            try:
                text = textract.process(tmp_path).decode("utf-8", errors="replace")
                return text
            finally:
                os.unlink(tmp_path)

        except ImportError:
            raise RuntimeError("PPT extraction requires 'textract'. Install with: pip install textract")


register_extractor(PowerPointExtractor())
```

**Dependencies:**
```toml
dependencies = [
    ...
    "python-pptx",  # For .pptx files
    "textract",     # For .ppt files (already needed for .doc)
]
```

Note: `.ppt` extraction via `textract` typically requires OS packages
(catppt). Consider skipping legacy formats if you want a lighter image.

---

## 4. Refactored Ingest Module (`ingest.py`)

After implementing all extractors, refactor `ingest.py` to use the registry:

```python
# ... existing imports ...
from .extractors import init_extractors
from .extractors.registry import get_drive_query_terms, get_extractor
from .extractors.utils import download_binary, download_export, execute_with_backoff

# Initialize extractor registry once on startup
init_extractors()

# Remove these hardcoded MIME constants
# DOC_MIME = "application/vnd.google-apps.document"
# SHEET_MIME = "application/vnd.google-apps.spreadsheet"

# Remove these hardcoded extraction functions
# def _extract_doc_text(...): ...
# def _extract_sheet_text(...): ...


def _ingest_one_file(
    store: RAGStore, file_meta: dict[str, Any], limiter: RateLimiter, stop_event: threading.Event
) -> str:
    """
    Returns status: ok | skipped_unchanged | skipped_empty | unsupported
    """
    if stop_event.is_set():
        return "skipped_empty"

    fid = file_meta["id"]
    name = file_meta.get("name", fid)
    mime = file_meta.get("mimeType")
    mtime = file_meta.get("modifiedTime") or ""

    if mtime and store.exists_file_mtime(fid, mtime):
        return "skipped_unchanged"

    # Get appropriate extractor from registry
    extractor = get_extractor(file_meta)
    if extractor is None:
        log.debug(
            "unsupported_file_type",
            component="ingest",
            flow="ingest_file",
            meta={"file_id": fid, "file_name": name, "mime_type": mime},
        )
        return "skipped_empty"  # Or add new "unsupported" status

    # Build extraction context
    context = _get_extraction_context(limiter, stop_event)

    try:
        result = extractor.extract(file_meta, context)
    except Exception:
        log.exception(
            "extraction_failed",
            component="ingest",
            flow="ingest_file",
            meta={"file_id": fid, "file_name": name, "mime_type": mime},
        )
        return "skipped_empty"

    if stop_event.is_set():
        return "skipped_empty"

    if not result.text.strip():
        return "skipped_empty"

    store.delete_by_file_id(fid)
    n = store.upsert_document(
        doc_id=fid,
        source="gdrive",
        text=result.text,
        payload={
            "file_id": fid,
            "file_name": name,
            "file_type": result.file_type,
            "modified_time": mtime,
            **result.metadata,
        },
    )

    log.info(
        "indexed",
        component="ingest",
        flow="ingest_file",
        meta=_file_log_meta(
            fid, name, chunks=n, file_type=result.file_type, modified_time=mtime
        ),
    )
    return "ok"


def _get_extraction_context(limiter: RateLimiter, stop_event: threading.Event):
    """Build context object with clients, limiter, and helpers."""
    drive, docs, sheets = _get_thread_clients()
    # Add slides client
    slides = getattr(_thread_local, "slides", None)
    if slides is None:
        _thread_local.slides = build(
            "slides", "v1", credentials=_thread_local.creds, cache_discovery=False
        )
        slides = _thread_local.slides

    class Context:
        pass

    ctx = Context()
    ctx.limiter = limiter
    ctx.stop_event = stop_event
    ctx.settings = settings
    ctx.drive = drive
    ctx.docs = docs
    ctx.sheets = sheets
    ctx.slides = slides
    ctx.execute_with_backoff = lambda call: execute_with_backoff(call, limiter)
    ctx.download_binary = lambda file_id: download_binary(drive, file_id, limiter, stop_event)
    ctx.download_export = lambda file_id, mime: download_export(
        drive, file_id, mime, limiter, stop_event
    )
    return ctx


def _walk_recursive(
    drive, root_ids: Iterable[str], limiter: RateLimiter, stop_event: threading.Event
) -> Iterable[dict[str, Any]]:
    """Modified to support all file types via registry."""
    stack = list(root_ids)
    seen: set[str] = set()

    while stack and not stop_event.is_set():
        folder_id = stack.pop()
        if folder_id in seen:
            continue
        seen.add(folder_id)

        for f in _list_children(drive, folder_id, limiter):
            if stop_event.is_set():
                break
            mime = f.get("mimeType")
            if mime == FOLDER_MIME:
                stack.append(f["id"])
            else:
                if get_extractor(f) is not None:
                    yield f


def _list_all_accessible_files(drive, limiter: RateLimiter) -> list[dict[str, Any]]:
    """Modified to support all file types."""
    terms = get_drive_query_terms()

    # Build query for all supported MIME types
    if terms:
        mime_conditions = " or ".join(terms)
        q = f"trashed=false and ({mime_conditions})"
    else:
        # Fallback: list everything and filter via registry
        q = "trashed=false"

    files: list[dict[str, Any]] = []
    page_token = None

    while True:
        pt = page_token
        resp = execute_with_backoff(
            lambda pt=pt: drive.files()
            .list(
                q=q,
                fields=(
                    "nextPageToken, files(id, name, mimeType, modifiedTime, "
                    "size, fileExtension, shortcutDetails)"
                ),
                pageToken=pt,
                pageSize=1000,
            )
            .execute(),
            limiter,
        )
        files.extend(resp.get("files") or [])
        page_token = resp.get("nextPageToken")
        if not page_token:
            break

    return [f for f in files if get_extractor(f) is not None]
```

Also update `_list_children()` to request `size`, `fileExtension`, and
`shortcutDetails` so extractors can enforce size limits and handle shortcuts.
If `mimeType` is `application/vnd.google-apps.shortcut`, either resolve the
target via `shortcutDetails.targetId` or skip it explicitly.

If Drive rejects `mimeType contains` queries or the OR list becomes too long,
fallback to `trashed=false` and filter via `get_extractor()` in-memory.

---

## 5. Settings Updates

Add new configuration options to `settings.py`:

```python
class Settings(BaseSettings):
    # ... existing settings ...

    # Google Slides
    GOOGLE_SLIDES_ENABLED: bool = True

    # Text files
    TEXT_FILES_ENABLED: bool = True
    TEXT_MAX_FILE_SIZE_MB: int = 10

    # PDF
    PDF_ENABLED: bool = True
    PDF_MAX_PAGES: int = 100
    PDF_MAX_FILE_SIZE_MB: int = 50
    PDF_EXTRACTION_ENGINE: str = "pypdf"  # or "pdfplumber"

    # Microsoft Office
    OFFICE_ENABLED: bool = True
    OFFICE_MAX_FILE_SIZE_MB: int = 50
    EXCEL_MAX_SHEETS: int = 50

    @field_validator("PDF_EXTRACTION_ENGINE")
    @classmethod
    def _validate_pdf_engine(cls, v: str) -> str:
        v = v.lower().strip()
        if v not in ("pypdf", "pdfplumber"):
            raise ValueError("PDF_EXTRACTION_ENGINE must be 'pypdf' or 'pdfplumber'")
        return v
```

In `init_extractors()`, only register extractors whose feature flags are
enabled. This avoids querying unsupported file types and keeps the Drive query
terms minimal.

---

## 6. Dependencies Update (`pyproject.toml`)

Add only new dependencies (existing ones stay as-is). Verify the latest
compatible versions and Python 3.13 support before pinning, then update
`uv.lock` accordingly.

```toml
dependencies = [
  # PDF support
  "pypdf",
  # "pdfplumber",  # Alternative PDF extractor (optional)
  # Microsoft Office support
  "python-docx",   # Word .docx
  "openpyxl",      # Excel .xlsx
  "xlrd",          # Excel .xls
  "python-pptx",   # PowerPoint .pptx
  "textract",      # Legacy Office formats (.doc, .ppt) - optional
]
```

**Alternative (lighter dependencies):**
If you want to minimize dependencies, you can:
1. Make heavy dependencies optional (textract)
2. Skip legacy format support (.doc, .ppt, .xls)
3. Use only modern formats (.docx, .pptx, .xlsx, .pdf)

Note: legacy extractors (textract, antiword, catppt) typically require OS
packages and may lag on Python 3.13 support. If you keep them, update the
Docker image and CI to install the required system libraries.

---

## 7. Migration Path

### Phase 1: Create Infrastructure (1-2 hours)

1. Create `extractors/` directory structure
2. Implement `extractors/base.py` (base classes)
3. Implement `extractors/registry.py` (registration system)
4. Add `providers/google_drive/api.py` and move backoff + download helpers
5. Refactor existing extractors into `extractors/google/docs.py` and
   `extractors/google/sheets.py`
6. Add `extractors/__init__.py` with `init_extractors()` (respect enable flags)
7. Update `ingest.py` to use registry and new helpers
8. Test that existing functionality works

### Phase 2: Add New Extractors (3-4 hours)

1. Implement Google Slides extractor
2. Implement Text files extractor
3. Implement PDF extractor
4. Implement Word extractor (DOC, DOCX)
5. Implement Excel extractor (XLS, XLSX)
6. Implement PowerPoint extractor (PPT, PPTX)
7. Update `pyproject.toml` with new dependencies and refresh `uv.lock`
8. Add new settings + validators
9. Update `.env.example` with new variables

### Phase 3: Testing & Documentation (1-2 hours)

1. Test each file type in a Google Drive folder
2. Update README with new supported file types
3. Update environment variable documentation
4. Update Dockerfile/CI if OS packages are required (textract, antiword, catppt)
5. Test error handling for unsupported files and size limits

---

## 8. Key Design Decisions

### 8.1 Why Separate Extractor Modules?

**Benefits:**
- Each file type is isolated and testable
- Easy to add new file types without touching existing code
- Dependencies can be optional per extractor
- Clear separation of concerns

### 8.2 Registry Pattern vs. Factory Pattern

Chosen **Registry Pattern** because:
- Registration is centralized in `init_extractors()` without large switch statements
- No central switch/if-elif chain needed inside `ingest.py`
- Plugins can add extractors without core code changes
- Runtime discovery of supported types

### 8.3 Binary Download Strategy

For non-Google files (PDF, Office, text files), we:
1. Download via Google Drive API `get_media`
2. Extract using Python libraries

For Google-native files (Docs, Sheets, Slides), use their dedicated APIs
or `export` when a suitable export format exists. This is more reliable than
Google Drive's text export for complex files.

### 8.4 Error Handling Strategy

Each extractor:
- Catches and logs extraction errors (unexpected exceptions)
- Returns empty content on failure (graceful degradation)
- Treats size-limit or disabled-format skips as non-errors
- Doesn't block ingestion of other files

---

## 9. Testing Strategy

### Unit Tests per Extractor

```python
# tests/extractors/test_pdf.py
import pytest
from gdrive_assistant_bot.extractors.pdf import PDFExtractor


def test_pdf_extractor_mime_types():
    extractor = PDFExtractor()
    assert "application/pdf" in extractor.mime_types


def test_pdf_extract_text_from_sample():
    extractor = PDFExtractor()
    # Use sample PDF bytes
    pdf_bytes = load_test_pdf()
    text = extractor._extract_text_from_pdf(pdf_bytes, max_pages=10)
    assert "expected content" in text
```

### Integration Tests

- Test with actual Google Drive files
- Test folder walking with mixed file types
- Test error handling (corrupted files, missing permissions)
- Test size limits and skip metadata (text, PDF, Office)

---

## 10. Summary

This plan transforms the hardcoded file extraction system into a modular, extensible architecture:

| Aspect               | Before                   | After                               |
| -------------------- | ------------------------ | ----------------------------------- |
| **File Support**     | 2 types (GDocs, GSheets) | 10+ types (Office, PDF, Text, etc.) |
| **Architecture**     | Hardcoded if-elif chain  | Registry-based plugin system        |
| **Adding New Types** | Edit `ingest.py`         | Create new extractor module         |
| **Testing**          | Difficult to isolate     | Per-extractor unit tests            |
| **Dependencies**     | Minimal                  | Modular (optional per extractor)    |

The new structure enables:
- Rapid addition of new file types
- Isolated testing and debugging
- Optional dependencies (don't install textract if you don't need legacy Office)
- Cleaner, more maintainable code
