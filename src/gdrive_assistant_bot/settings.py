from __future__ import annotations

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_MAX_TOP_K = 50
_MIN_CONTEXT_CHARS = 500
_MAX_CONTEXT_CHARS = 100_000
_MAX_WORKERS = 64
_MAX_RPS = 1000
_MAX_BURST = 10_000
_MAX_PROGRESS_EVERY = 10_000
_MAX_PROGRESS_SECONDS = 3600
_MAX_SHUTDOWN_GRACE_SECONDS = 600


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
        "Ты помощник по внутренней базе знаний. "
        "Отвечай по контексту. Если данных нет — скажи, что не нашел."
    )

    # Google Drive ingest
    GOOGLE_SERVICE_ACCOUNT_JSON: str = "/run/secrets/google_sa"
    GOOGLE_DRIVE_FOLDER_IDS: list[str] = []
    ALL_ACCESSIBLE: bool = False

    INGEST_MODE: str = "loop"  # once|loop
    INGEST_POLL_SECONDS: int = 600
    INGEST_WORKERS: int = 6

    GOOGLE_MAX_ROWS_PER_SHEET: int = 2000
    GOOGLE_BACKOFF_RETRIES: int = 8
    GOOGLE_BACKOFF_BASE_DELAY: float = 1.0
    GOOGLE_BACKOFF_MAX_DELAY: float = 30.0

    # Google API rate limit (token bucket)
    GOOGLE_API_RPS: float = 8.0
    GOOGLE_API_BURST: float = 16.0

    # progress logging
    INGEST_PROGRESS_EVERY: int = 25
    INGEST_PROGRESS_SECONDS: int = 30

    # graceful shutdown
    INGEST_SHUTDOWN_GRACE_SECONDS: int = 20

    # health
    HEALTH_HOST: str = "localhost"
    BOT_HEALTH_PORT: int = 8080
    INGEST_HEALTH_PORT: int = 8081

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

    @field_validator("INGEST_PROGRESS_EVERY")
    @classmethod
    def _validate_progress_every(cls, v: int) -> int:
        if v < 1 or v > _MAX_PROGRESS_EVERY:
            raise ValueError(f"INGEST_PROGRESS_EVERY must be in range [1..{_MAX_PROGRESS_EVERY}]")
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
            "QDRANT_URL": self.QDRANT_URL,
            "QDRANT_COLLECTION": self.QDRANT_COLLECTION,
            "EMBED_MODEL": self.EMBED_MODEL,
            "TOP_K": self.TOP_K,
            "MAX_CONTEXT_CHARS": self.MAX_CONTEXT_CHARS,
            "LLM_BASE_URL": self.LLM_BASE_URL,
            "LLM_MODEL": self.LLM_MODEL,
            "LLM_ENABLED": self.llm_enabled(),
            "GOOGLE_SERVICE_ACCOUNT_JSON": self.GOOGLE_SERVICE_ACCOUNT_JSON,
            "GOOGLE_DRIVE_FOLDER_IDS": self.GOOGLE_DRIVE_FOLDER_IDS,
            "ALL_ACCESSIBLE": self.ALL_ACCESSIBLE,
            "INGEST_MODE": self.INGEST_MODE,
            "INGEST_POLL_SECONDS": self.INGEST_POLL_SECONDS,
            "INGEST_WORKERS": self.INGEST_WORKERS,
            "GOOGLE_API_RPS": self.GOOGLE_API_RPS,
            "GOOGLE_API_BURST": self.GOOGLE_API_BURST,
            "INGEST_PROGRESS_EVERY": self.INGEST_PROGRESS_EVERY,
            "INGEST_PROGRESS_SECONDS": self.INGEST_PROGRESS_SECONDS,
            "INGEST_SHUTDOWN_GRACE_SECONDS": self.INGEST_SHUTDOWN_GRACE_SECONDS,
            "HEALTH_HOST": self.HEALTH_HOST,
            "BOT_HEALTH_PORT": self.BOT_HEALTH_PORT,
            "INGEST_HEALTH_PORT": self.INGEST_HEALTH_PORT,
        }


settings = Settings()
