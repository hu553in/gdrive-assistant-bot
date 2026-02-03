from .google.docs import GoogleDocsExtractor
from .google.sheets import GoogleSheetsExtractor
from .registry import register_extractor


def init_extractors() -> None:
    if getattr(init_extractors, "_initialized", False):
        return

    register_extractor(GoogleDocsExtractor())
    register_extractor(GoogleSheetsExtractor())
    init_extractors._initialized = True
