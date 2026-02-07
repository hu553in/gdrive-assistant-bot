from ..settings import settings
from .google.docs import GoogleDocsExtractor
from .google.sheets import GoogleSheetsExtractor
from .google.slides import GoogleSlidesExtractor
from .office.excel import XlsExtractor, XlsxExtractor
from .office.powerpoint import PptExtractor, PptxExtractor
from .office.word import DocExtractor, DocxExtractor
from .pdf import PDFExtractor
from .registry import register_extractor
from .text import TextBasedFileExtractor


def init_extractors() -> None:
    """Register built-in extractors once."""

    if getattr(init_extractors, "_initialized", False):
        return

    if settings.FILE_TYPE_GDOCS_ENABLED:
        register_extractor(GoogleDocsExtractor())
    if settings.FILE_TYPE_GSHEETS_ENABLED:
        register_extractor(GoogleSheetsExtractor())
    if settings.FILE_TYPE_GSLIDES_ENABLED:
        register_extractor(GoogleSlidesExtractor())
    if settings.FILE_TYPE_TEXT_BASED_ENABLED:
        register_extractor(TextBasedFileExtractor())
    if settings.FILE_TYPE_PDF_ENABLED:
        register_extractor(PDFExtractor())
    if settings.FILE_TYPE_DOCX_ENABLED:
        register_extractor(DocxExtractor())
    if settings.FILE_TYPE_DOC_ENABLED:
        register_extractor(DocExtractor())
    if settings.FILE_TYPE_XLSX_ENABLED:
        register_extractor(XlsxExtractor())
    if settings.FILE_TYPE_XLS_ENABLED:
        register_extractor(XlsExtractor())
    if settings.FILE_TYPE_PPTX_ENABLED:
        register_extractor(PptxExtractor())
    if settings.FILE_TYPE_PPT_ENABLED:
        register_extractor(PptExtractor())
    init_extractors._initialized = True


__all__ = []
