from __future__ import annotations

import structlog
from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_MAX_TOP_K = 50
_MIN_CONTEXT_CHARS = 500
_MAX_CONTEXT_CHARS = 100_000
_MAX_WORKERS = 64
_MAX_RPS = 1000
_MAX_BURST = 10_000
_MAX_PROGRESS_FILES = 10_000
_MAX_PROGRESS_SECONDS = 3600
_MAX_SHUTDOWN_GRACE_SECONDS = 600
_MAX_POLL_SECONDS = 86_400
_LOG_LEVELS = {"CRITICAL", "FATAL", "ERROR", "WARN", "WARNING", "INFO", "DEBUG", "NOTSET"}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Telegram
    TELEGRAM_BOT_TOKEN: str

    # Qdrant
    QDRANT_URL: str = "http://qdrant:6333"
    QDRANT_COLLECTION: str = "docs"

    # Embeddings
    EMBED_MODEL: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"

    # RAG
    TOP_K: int = 6
    MAX_CONTEXT_CHARS: int = 6000

    # Optional LLM (OpenAI-compatible)
    LLM_BASE_URL: str | None = None
    LLM_API_KEY: str | None = None
    LLM_MODEL: str | None = None
    LLM_SYSTEM_PROMPT: str = (
        "You are an assistant for a private internal knowledge base. "
        "You must answer questions strictly and exclusively based on the provided context. "
        "If the context does not explicitly contain the required information, "
        "state that the information is not available. "
        "Never speculate, infer, or guess beyond the given text. "
        "Prefer accuracy over completeness."
    )

    # Google Drive ingest
    GOOGLE_SERVICE_ACCOUNT_JSON: str = "/run/secrets/google_sa"
    GOOGLE_DRIVE_FOLDER_IDS: list[str] = []
    ALL_ACCESSIBLE: bool = False

    # Ingest
    INGEST_MODE: str = "loop"  # "once" or "loop"
    INGEST_POLL_SECONDS: int = 600
    INGEST_WORKERS: int = 6

    # Ingest backoff
    GOOGLE_MAX_ROWS_PER_SHEET: int = 2000
    GOOGLE_BACKOFF_RETRIES: int = 8
    GOOGLE_BACKOFF_BASE_DELAY_SECONDS: float = 1.0
    GOOGLE_BACKOFF_MAX_DELAY_SECONDS: float = 30.0

    # Google API rate limit
    GOOGLE_API_RPS: float = 8.0  # tokens/second
    GOOGLE_API_BURST: float = 16.0  # tokens

    # Ingest progress logging
    INGEST_PROGRESS_FILES: int = 25
    INGEST_PROGRESS_SECONDS: int = 30

    # Ingest graceful shutdown delay
    INGEST_SHUTDOWN_GRACE_SECONDS: int = 20

    # Health server
    HEALTH_HOST: str = "localhost"
    BOT_HEALTH_PORT: int = 8080
    INGEST_HEALTH_PORT: int = 8081

    # Logging
    LOG_LEVEL: str = "INFO"
    LOG_PLAIN_TEXT: bool = False

    @field_validator("INGEST_MODE")
    @classmethod
    def _validate_mode(cls, v: str) -> str:
        v = v.lower().strip()
        if v not in {"once", "loop"}:
            raise ValueError("INGEST_MODE must be 'once' or 'loop'")
        return v

    @field_validator("TOP_K")
    @classmethod
    def _validate_top_k(cls, v: int) -> int:
        if v < 1 or v > _MAX_TOP_K:
            raise ValueError(f"TOP_K must be in range [1..{_MAX_TOP_K}]")
        return v

    @field_validator("MAX_CONTEXT_CHARS")
    @classmethod
    def _validate_context_chars(cls, v: int) -> int:
        if v < _MIN_CONTEXT_CHARS or v > _MAX_CONTEXT_CHARS:
            raise ValueError(
                f"MAX_CONTEXT_CHARS must be in range [{_MIN_CONTEXT_CHARS}..{_MAX_CONTEXT_CHARS}]"
            )
        return v

    @field_validator("INGEST_WORKERS")
    @classmethod
    def _validate_workers(cls, v: int) -> int:
        if v < 1 or v > _MAX_WORKERS:
            raise ValueError(f"INGEST_WORKERS must be in range [1..{_MAX_WORKERS}]")
        return v

    @field_validator("GOOGLE_API_RPS")
    @classmethod
    def _validate_rps(cls, v: float) -> float:
        if v <= 0 or v > _MAX_RPS:
            raise ValueError(f"GOOGLE_API_RPS must be in range (0..{_MAX_RPS}]")
        return v

    @field_validator("GOOGLE_API_BURST")
    @classmethod
    def _validate_burst(cls, v: float) -> float:
        if v < 1 or v > _MAX_BURST:
            raise ValueError(f"GOOGLE_API_BURST must be in range [1..{_MAX_BURST}]")
        return v

    @field_validator("INGEST_PROGRESS_FILES")
    @classmethod
    def _validate_progress_files(cls, v: int) -> int:
        if v < 1 or v > _MAX_PROGRESS_FILES:
            raise ValueError(f"INGEST_PROGRESS_FILES must be in range [1..{_MAX_PROGRESS_FILES}]")
        return v

    @field_validator("INGEST_PROGRESS_SECONDS")
    @classmethod
    def _validate_progress_seconds(cls, v: int) -> int:
        if v < 1 or v > _MAX_PROGRESS_SECONDS:
            raise ValueError(
                f"INGEST_PROGRESS_SECONDS must be in range [1..{_MAX_PROGRESS_SECONDS}]"
            )
        return v

    @field_validator("INGEST_SHUTDOWN_GRACE_SECONDS")
    @classmethod
    def _validate_grace(cls, v: int) -> int:
        if v < 0 or v > _MAX_SHUTDOWN_GRACE_SECONDS:
            raise ValueError(
                f"INGEST_SHUTDOWN_GRACE_SECONDS must be in range [0..{_MAX_SHUTDOWN_GRACE_SECONDS}]"
            )
        return v

    @field_validator("INGEST_POLL_SECONDS")
    @classmethod
    def _validate_poll_seconds(cls, v: int) -> int:
        if v < 1 or v > _MAX_POLL_SECONDS:
            raise ValueError(f"INGEST_POLL_SECONDS must be in range [1..{_MAX_POLL_SECONDS}]")
        return v

    @field_validator("LOG_LEVEL")
    @classmethod
    def _validate_log_level(cls, v: str) -> str:
        level = v.strip().upper()
        if level not in _LOG_LEVELS:
            raise ValueError(f"LOG_LEVEL must be one of: {', '.join(sorted(_LOG_LEVELS))}")
        return level

    @field_validator("GOOGLE_DRIVE_FOLDER_IDS", mode="before")
    @classmethod
    def _parse_folder_ids(cls, v):
        if v is None:
            return []
        if isinstance(v, list):
            return [str(x).strip() for x in v if str(x).strip()]
        s = str(v).strip()
        if not s:
            return []
        return [x.strip() for x in s.split(",") if x.strip()]

    @model_validator(mode="after")
    def _validate_drive_scope(self) -> Settings:
        if not self.ALL_ACCESSIBLE and not self.GOOGLE_DRIVE_FOLDER_IDS:
            raise ValueError(
                "Set GOOGLE_DRIVE_FOLDER_IDS (comma-separated) or set ALL_ACCESSIBLE=true"
            )
        return self

    def llm_enabled(self) -> bool:
        return bool(self.LLM_BASE_URL and self.LLM_API_KEY and self.LLM_MODEL)

    def safe_dump(self) -> dict:
        # intentionally excludes secrets (telegram token, llm api key)
        return {
            "qdrant_url": self.QDRANT_URL,
            "qdrant_collection": self.QDRANT_COLLECTION,
            "embed_model": self.EMBED_MODEL,
            "top_k": self.TOP_K,
            "max_context_chars": self.MAX_CONTEXT_CHARS,
            "llm_base_url": self.LLM_BASE_URL,
            "llm_model": self.LLM_MODEL,
            "llm_enabled": self.llm_enabled(),
            "google_service_account_json": self.GOOGLE_SERVICE_ACCOUNT_JSON,
            "google_drive_folder_ids": self.GOOGLE_DRIVE_FOLDER_IDS,
            "all_accessible": self.ALL_ACCESSIBLE,
            "ingest_mode": self.INGEST_MODE,
            "ingest_poll_seconds": self.INGEST_POLL_SECONDS,
            "ingest_workers": self.INGEST_WORKERS,
            "google_max_rows_per_sheet": self.GOOGLE_MAX_ROWS_PER_SHEET,
            "google_backoff_retries": self.GOOGLE_BACKOFF_RETRIES,
            "google_backoff_base_delay_seconds": self.GOOGLE_BACKOFF_BASE_DELAY_SECONDS,
            "google_backoff_max_delay_seconds": self.GOOGLE_BACKOFF_MAX_DELAY_SECONDS,
            "google_api_rps": self.GOOGLE_API_RPS,
            "google_api_burst": self.GOOGLE_API_BURST,
            "ingest_progress_files": self.INGEST_PROGRESS_FILES,
            "ingest_progress_seconds": self.INGEST_PROGRESS_SECONDS,
            "ingest_shutdown_grace_seconds": self.INGEST_SHUTDOWN_GRACE_SECONDS,
            "log_level": self.LOG_LEVEL,
            "log_plain_text": self.LOG_PLAIN_TEXT,
            "health_host": self.HEALTH_HOST,
            "bot_health_port": self.BOT_HEALTH_PORT,
            "ingest_health_port": self.INGEST_HEALTH_PORT,
        }


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
