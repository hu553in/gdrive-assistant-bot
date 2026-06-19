from __future__ import annotations

import logging

import pytest

from gdrive_assistant_bot import logging as bot_logging
from gdrive_assistant_bot.settings import settings


def test_setup_logging_plain_text(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "LOG_PLAIN_TEXT", True)
    monkeypatch.setattr(settings, "LOG_LEVEL", "DEBUG")

    bot_logging.setup_logging()

    root = logging.getLogger()
    assert root.level == logging.DEBUG
    assert root.handlers


def test_setup_logging_json(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "LOG_PLAIN_TEXT", False)
    monkeypatch.setattr(settings, "LOG_LEVEL", "INFO")

    bot_logging.setup_logging()

    root = logging.getLogger()
    assert root.level == logging.INFO
    assert root.handlers
