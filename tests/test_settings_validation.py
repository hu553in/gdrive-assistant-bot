from typing import Any

import pytest
from pydantic_settings import SettingsConfigDict

from gdrive_assistant_bot.settings import Settings


def _valid_settings(cls: type[Settings] = Settings, **kwargs: dict[str, Any]) -> Settings:
    if (
        "STORAGE_GOOGLE_DRIVE_ALL_ACCESSIBLE" not in kwargs
        and "STORAGE_GOOGLE_DRIVE_FOLDER_IDS" not in kwargs
    ):
        kwargs["STORAGE_GOOGLE_DRIVE_ALL_ACCESSIBLE"] = True
    return cls(TELEGRAM_BOT_TOKEN="example", **kwargs)


def test_literal_types_validated() -> None:
    with pytest.raises(ValueError):
        _valid_settings(STORAGE_BACKEND="invalid")
    with pytest.raises(ValueError):
        _valid_settings(LOG_LEVEL="INVALID")
    with pytest.raises(ValueError):
        _valid_settings(INGEST_MODE="INVALID")


def test_google_drive_scope_validated() -> None:
    with pytest.raises(ValueError):
        _valid_settings(
            STORAGE_BACKEND="google_drive",
            STORAGE_GOOGLE_DRIVE_FOLDER_IDS=[],
            STORAGE_GOOGLE_DRIVE_ALL_ACCESSIBLE=False,
        )


def test_google_drive_scope_valid_when_all_accessible() -> None:
    settings = _valid_settings(
        STORAGE_GOOGLE_DRIVE_ALL_ACCESSIBLE=True, STORAGE_GOOGLE_DRIVE_FOLDER_IDS=[]
    )
    assert settings.STORAGE_GOOGLE_DRIVE_ALL_ACCESSIBLE is True


def test_google_drive_scope_valid_when_folder_ids_set() -> None:
    settings = _valid_settings(
        STORAGE_GOOGLE_DRIVE_ALL_ACCESSIBLE=False, STORAGE_GOOGLE_DRIVE_FOLDER_IDS=["id1"]
    )
    assert settings.STORAGE_GOOGLE_DRIVE_FOLDER_IDS == ["id1"]


def test_llm_enabled_requires_all_fields() -> None:
    base_url = "http://llm.local"
    assert (
        _valid_settings(LLM_BASE_URL=base_url, LLM_API_KEY=None, LLM_MODEL="gpt").is_llm_enabled()
        is False
    )
    assert (
        _valid_settings(LLM_BASE_URL=None, LLM_API_KEY="key", LLM_MODEL="gpt").is_llm_enabled()
        is False
    )
    assert (
        _valid_settings(LLM_BASE_URL=base_url, LLM_API_KEY="key", LLM_MODEL=None).is_llm_enabled()
        is False
    )
    assert (
        _valid_settings(LLM_BASE_URL=base_url, LLM_API_KEY="key", LLM_MODEL="gpt").is_llm_enabled()
        is True
    )


def test_telegram_private_mode_flags() -> None:
    class SettingsIgnoringEnvFile(Settings):
        model_config = SettingsConfigDict(env_file=None, extra="ignore", env_ignore_empty=True)

    assert _valid_settings(SettingsIgnoringEnvFile).is_telegram_private_mode() is False
    assert (
        _valid_settings(
            SettingsIgnoringEnvFile, TELEGRAM_ALLOWED_USER_IDS=[1]
        ).is_telegram_private_mode()
        is True
    )
    assert (
        _valid_settings(
            SettingsIgnoringEnvFile, TELEGRAM_ALLOWED_GROUP_IDS=[2]
        ).is_telegram_private_mode()
        is True
    )
