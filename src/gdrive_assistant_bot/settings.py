from __future__ import annotations

from typing import Literal

import structlog
from pydantic import Field, HttpUrl, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_StorageBackend = Literal["google_drive"]
_LogLevel = Literal["CRITICAL", "FATAL", "ERROR", "WARN", "WARNING", "INFO", "DEBUG", "NOTSET"]
_IngestMode = Literal["once", "loop"]
_PdfExtractionEngine = Literal["pypdf", "pdfplumber"]


class Settings(BaseSettings):
    """
    Typed application settings loaded from environment variables.
    List-type fields expect JSON arrays (for example: '["id1","id2"]').
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore", env_ignore_empty=True)

    # Telegram
    TELEGRAM_BOT_TOKEN: str = Field(exclude=True)
    TELEGRAM_ALLOWED_USER_IDS: list[int] = []
    TELEGRAM_ALLOWED_GROUP_IDS: list[int] = []

    # Storage backend
    STORAGE_BACKEND: _StorageBackend = "google_drive"

    # Google Drive storage
    STORAGE_GOOGLE_DRIVE_SERVICE_ACCOUNT_JSON: str = "/run/secrets/google_sa"
    STORAGE_GOOGLE_DRIVE_FOLDER_IDS: list[str] = []
    STORAGE_GOOGLE_DRIVE_ALL_ACCESSIBLE: bool = False

    # Google Drive API/backoff/limits
    STORAGE_GOOGLE_DRIVE_MAX_ROWS_PER_SHEET: int = Field(default=10000, ge=1)
    STORAGE_GOOGLE_DRIVE_BACKOFF_RETRIES: int = Field(default=8, ge=0)
    STORAGE_GOOGLE_DRIVE_BACKOFF_BASE_DELAY_SECONDS: float = Field(default=1.0, gt=0.0)
    STORAGE_GOOGLE_DRIVE_BACKOFF_MAX_DELAY_SECONDS: float = Field(default=30.0, gt=0.0)
    STORAGE_GOOGLE_DRIVE_API_RPS: float = Field(default=8.0, gt=0.0, le=1000.0)
    STORAGE_GOOGLE_DRIVE_API_BURST: float = Field(default=16.0, ge=1, le=10000.0)

    # File type feature toggles
    FILE_TYPE_GDOCS_ENABLED: bool = True
    FILE_TYPE_GSHEETS_ENABLED: bool = True
    FILE_TYPE_GSLIDES_ENABLED: bool = True
    FILE_TYPE_TEXT_BASED_ENABLED: bool = True
    FILE_TYPE_PDF_ENABLED: bool = True
    FILE_TYPE_DOCX_ENABLED: bool = True
    FILE_TYPE_DOC_ENABLED: bool = True
    FILE_TYPE_XLSX_ENABLED: bool = True
    FILE_TYPE_XLS_ENABLED: bool = True
    FILE_TYPE_PPTX_ENABLED: bool = True
    FILE_TYPE_PPT_ENABLED: bool = True

    # Extractor limits
    TEXT_MAX_FILE_SIZE_MB: int = Field(default=10, ge=1, le=1024)
    PDF_MAX_PAGES: int = Field(default=100, ge=1, le=10000)
    PDF_MAX_FILE_SIZE_MB: int = Field(default=50, ge=1, le=1024)
    PDF_EXTRACTION_ENGINE: _PdfExtractionEngine = "pypdf"
    OFFICE_MAX_FILE_SIZE_MB: int = Field(default=50, ge=1, le=1024)
    EXCEL_MAX_SHEETS: int = Field(default=50, ge=1, le=1000)

    # Qdrant
    QDRANT_URL: HttpUrl = HttpUrl("http://qdrant:6333")
    QDRANT_COLLECTION: str = "docs"

    # Embeddings
    EMBED_MODEL: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"

    # Optional HuggingFace token (fastembed reads it from env).
    HF_TOKEN: str | None = Field(default=None, exclude=True)

    # RAG
    TOP_K: int = Field(default=6, ge=1, le=50)
    MAX_CONTEXT_CHARS: int = Field(default=6000, ge=500, le=100_000)

    # Optional LLM (OpenAI-compatible)
    LLM_BASE_URL: HttpUrl = HttpUrl("https://api.openai.com/v1")
    LLM_API_KEY: str | None = Field(default=None, exclude=True)
    LLM_MODEL: str = "gpt-4o-mini"
    LLM_SYSTEM_PROMPT: str = (
        "You are an assistant for a private internal knowledge base. "
        "You must answer questions strictly and exclusively based on the provided context. "
        "If the context does not explicitly contain the required information, "
        "state that the information is not available. "
        "Never speculate, infer, or guess beyond the given text. "
        "Prefer accuracy over completeness."
    )

    # Ingest
    INGEST_MODE: _IngestMode = "loop"
    INGEST_POLL_SECONDS: int = Field(default=600, ge=1, le=86_400)
    INGEST_WORKERS: int = Field(default=6, ge=1, le=64)

    # Ingest progress logging
    INGEST_PROGRESS_FILES: int = Field(default=25, ge=1, le=10_000)
    INGEST_PROGRESS_SECONDS: int = Field(default=30, ge=1, le=3600)

    # Ingest graceful shutdown delay
    INGEST_SHUTDOWN_GRACE_SECONDS: int = Field(default=20, ge=0, le=600)

    # Health server
    HEALTH_HOST: str = "localhost"
    BOT_HEALTH_PORT: int = Field(default=8080, ge=1, le=65535)
    INGEST_HEALTH_PORT: int = Field(default=8081, ge=1, le=65535)

    # Logging
    LOG_LEVEL: _LogLevel = "INFO"
    LOG_PLAIN_TEXT: bool = False

    @model_validator(mode="after")
    def _validate_google_drive_scope(self) -> Settings:
        if (
            self.STORAGE_BACKEND == "google_drive"
            and not self.STORAGE_GOOGLE_DRIVE_ALL_ACCESSIBLE
            and not self.STORAGE_GOOGLE_DRIVE_FOLDER_IDS
        ):
            raise ValueError(
                "Set STORAGE_GOOGLE_DRIVE_FOLDER_IDS (JSON array) or set "
                "STORAGE_GOOGLE_DRIVE_ALL_ACCESSIBLE=true"
            )
        return self

    def is_llm_enabled(self) -> bool:
        return bool(self.LLM_API_KEY)

    def is_telegram_private_mode(self) -> bool:
        return bool(self.TELEGRAM_ALLOWED_USER_IDS or self.TELEGRAM_ALLOWED_GROUP_IDS)


try:
    settings = Settings()
except Exception as exc:
    structlog.get_logger("gdrive-assistant-bot.settings").error(
        "settings_load_failed",
        component="settings",
        flow="startup",
        meta={"error_type": type(exc).__name__, "error": str(exc)},
    )
    raise
