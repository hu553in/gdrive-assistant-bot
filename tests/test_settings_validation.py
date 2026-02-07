from typing import Any

import pytest

from gdrive_assistant_bot.settings import Settings


def _valid_settings(**kwargs: Any) -> Settings:
    if (
        "STORAGE_GOOGLE_DRIVE_ALL_ACCESSIBLE" not in kwargs
        and "STORAGE_GOOGLE_DRIVE_FOLDER_IDS" not in kwargs
    ):
        kwargs["STORAGE_GOOGLE_DRIVE_ALL_ACCESSIBLE"] = True
    return Settings(TELEGRAM_BOT_TOKEN="example", **kwargs)


def test_literal_types_validated() -> None:
    with pytest.raises(ValueError):
        _valid_settings(STORAGE_BACKEND="invalid")
    with pytest.raises(ValueError):
        _valid_settings(LOG_LEVEL="INVALID")
    with pytest.raises(ValueError):
        _valid_settings(INGEST_MODE="INVALID")
    with pytest.raises(ValueError):
        _valid_settings(PDF_EXTRACTION_ENGINE="INVALID")


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


def test_llm_enabled_requires_api_key() -> None:
    assert _valid_settings(LLM_API_KEY=None).is_llm_enabled() is False
    assert _valid_settings(LLM_API_KEY="key").is_llm_enabled() is True


def test_telegram_private_mode_flags() -> None:
    assert _valid_settings().is_telegram_private_mode() is False
    assert _valid_settings(TELEGRAM_ALLOWED_USER_IDS=[1]).is_telegram_private_mode() is True
    assert _valid_settings(TELEGRAM_ALLOWED_GROUP_IDS=[2]).is_telegram_private_mode() is True


def test_file_type_feature_toggles_enabled_by_default() -> None:
    settings = _valid_settings()
    assert settings.FILE_TYPE_GDOCS_ENABLED is True
    assert settings.FILE_TYPE_GSHEETS_ENABLED is True
    assert settings.FILE_TYPE_GSLIDES_ENABLED is True
    assert settings.FILE_TYPE_TEXT_BASED_ENABLED is True
    assert settings.FILE_TYPE_PDF_ENABLED is True
    assert settings.FILE_TYPE_DOCX_ENABLED is True
    assert settings.FILE_TYPE_DOC_ENABLED is True
    assert settings.FILE_TYPE_XLSX_ENABLED is True
    assert settings.FILE_TYPE_XLS_ENABLED is True
    assert settings.FILE_TYPE_PPTX_ENABLED is True
    assert settings.FILE_TYPE_PPT_ENABLED is True
