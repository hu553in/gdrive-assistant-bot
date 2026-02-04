from typing import Any

import pytest

from gdrive_assistant_bot.settings import Settings


def _with_required_fields(**kwargs: dict[str, Any]) -> Settings:
    return Settings(TELEGRAM_BOT_TOKEN="example", **kwargs)


def test_literal_types_validated() -> None:
    with pytest.raises(ValueError):
        _with_required_fields(STORAGE_BACKEND="invalid")
    with pytest.raises(ValueError):
        _with_required_fields(LOG_LEVEL="INVALID")
    with pytest.raises(ValueError):
        _with_required_fields(INGEST_MODE="INVALID")


def test_google_drive_scope_validated() -> None:
    with pytest.raises(ValueError):
        _with_required_fields(
            STORAGE_BACKEND="google_drive",
            STORAGE_GOOGLE_DRIVE_FOLDER_IDS=[],
            STORAGE_GOOGLE_DRIVE_ALL_ACCESSIBLE=False,
        )
