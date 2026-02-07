from __future__ import annotations

import asyncio
from typing import cast

import pytest
from telegram import Update
from telegram.ext import ContextTypes

from gdrive_assistant_bot.adapters import telegram as tg
from gdrive_assistant_bot.core.qa.service import LLMError, QAAnswer, SearchError
from gdrive_assistant_bot.settings import settings
from tests.fakes import FakeApplication, FakeChat, FakeContext, FakeMessage, FakeUpdate, FakeUser


class _FakeQA:
    def __init__(
        self,
        *,
        answer: QAAnswer | None = None,
        raise_error: Exception | None = None,
        llm: object | None = None,
    ):
        self.answer = answer
        self.raise_error = raise_error
        self.llm = llm
        self.ingested: list[dict[str, object]] = []

    def ingest_text(
        self, *, text: str, payload: dict[str, object], doc_id: str, source: str
    ) -> int:
        if self.raise_error:
            raise self.raise_error
        self.ingested.append({"text": text, "payload": payload, "doc_id": doc_id, "source": source})
        return 2

    def ask(self, _question: str) -> QAAnswer:
        if self.raise_error:
            raise self.raise_error
        if not self.answer:
            raise AssertionError("answer required")
        return self.answer


def _run(coro):
    return asyncio.run(coro)


def _as_update(update: FakeUpdate) -> Update:
    return cast(Update, update)


def _as_context(context: FakeContext) -> ContextTypes.DEFAULT_TYPE:
    return cast(ContextTypes.DEFAULT_TYPE, context)


def test_is_allowed_public_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "TELEGRAM_ALLOWED_USER_IDS", [])
    monkeypatch.setattr(settings, "TELEGRAM_ALLOWED_GROUP_IDS", [])

    update = FakeUpdate()

    assert tg._is_allowed(_as_update(update)) is True


def test_is_allowed_private_user(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "TELEGRAM_ALLOWED_USER_IDS", [1])
    monkeypatch.setattr(settings, "TELEGRAM_ALLOWED_GROUP_IDS", [])

    msg = FakeMessage(chat=FakeChat(id=10, type="private"), message_id=1, from_user=FakeUser(1))
    update = FakeUpdate(message=msg)

    assert tg._is_allowed(_as_update(update)) is True

    msg_other = FakeMessage(
        chat=FakeChat(id=10, type="private"), message_id=2, from_user=FakeUser(2)
    )
    update_other = FakeUpdate(message=msg_other)
    assert tg._is_allowed(_as_update(update_other)) is False


def test_is_allowed_group(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "TELEGRAM_ALLOWED_USER_IDS", [])
    monkeypatch.setattr(settings, "TELEGRAM_ALLOWED_GROUP_IDS", [99])

    msg = FakeMessage(chat=FakeChat(id=99, type="group"), message_id=1)
    update = FakeUpdate(message=msg)

    assert tg._is_allowed(_as_update(update)) is True


def test_cmd_ingest_requires_text(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "TELEGRAM_ALLOWED_USER_IDS", [])
    monkeypatch.setattr(settings, "TELEGRAM_ALLOWED_GROUP_IDS", [])

    msg = FakeMessage(chat=FakeChat(id=1, type="private"), message_id=1, text="/ingest")
    update = FakeUpdate(message=msg)
    ctx = FakeContext(application=FakeApplication())

    _run(tg.cmd_ingest(_as_update(update), _as_context(ctx)))

    assert msg.replies[-1] == "Использование: /ingest <текст>"


def test_cmd_ingest_requires_service(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "TELEGRAM_ALLOWED_USER_IDS", [])
    monkeypatch.setattr(settings, "TELEGRAM_ALLOWED_GROUP_IDS", [])

    msg = FakeMessage(chat=FakeChat(id=1, type="private"), message_id=1, text="/ingest hi")
    update = FakeUpdate(message=msg)
    ctx = FakeContext(application=FakeApplication())

    _run(tg.cmd_ingest(_as_update(update), _as_context(ctx)))

    assert msg.replies[-1] == "Сервис недоступен. Попробуйте позже."


def test_cmd_ingest_handles_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "TELEGRAM_ALLOWED_USER_IDS", [])
    monkeypatch.setattr(settings, "TELEGRAM_ALLOWED_GROUP_IDS", [])

    msg = FakeMessage(chat=FakeChat(id=1, type="private"), message_id=1, text="/ingest hi")
    update = FakeUpdate(message=msg)
    ctx = FakeContext(
        application=FakeApplication(bot_data={"qa": _FakeQA(raise_error=RuntimeError("boom"))})
    )

    _run(tg.cmd_ingest(_as_update(update), _as_context(ctx)))

    expected = "Ошибка добавления в базу знаний. Попробуйте позже."
    assert msg.replies[-1] == expected


def test_cmd_ingest_success(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "TELEGRAM_ALLOWED_USER_IDS", [])
    monkeypatch.setattr(settings, "TELEGRAM_ALLOWED_GROUP_IDS", [])

    qa = _FakeQA()
    msg = FakeMessage(chat=FakeChat(id=1, type="private"), message_id=1, text="/ingest hi")
    update = FakeUpdate(message=msg)
    ctx = FakeContext(application=FakeApplication(bot_data={"qa": qa}))

    _run(tg.cmd_ingest(_as_update(update), _as_context(ctx)))

    assert "Информация добавлена" in msg.replies[-1]
    assert qa.ingested


def test_cmd_ask_requires_text(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "TELEGRAM_ALLOWED_USER_IDS", [])
    monkeypatch.setattr(settings, "TELEGRAM_ALLOWED_GROUP_IDS", [])

    msg = FakeMessage(chat=FakeChat(id=1, type="private"), message_id=1, text="/ask")
    update = FakeUpdate(message=msg)
    ctx = FakeContext(application=FakeApplication())

    _run(tg.cmd_ask(_as_update(update), _as_context(ctx)))

    assert msg.replies[-1] == "Использование: /ask <вопрос>"


def test_cmd_ask_requires_service(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "TELEGRAM_ALLOWED_USER_IDS", [])
    monkeypatch.setattr(settings, "TELEGRAM_ALLOWED_GROUP_IDS", [])

    msg = FakeMessage(chat=FakeChat(id=1, type="private"), message_id=1, text="/ask hi")
    update = FakeUpdate(message=msg)
    ctx = FakeContext(application=FakeApplication())

    _run(tg.cmd_ask(_as_update(update), _as_context(ctx)))

    assert msg.replies[-1] == "Сервис недоступен. Попробуйте позже."


def test_cmd_ask_handles_search_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "TELEGRAM_ALLOWED_USER_IDS", [])
    monkeypatch.setattr(settings, "TELEGRAM_ALLOWED_GROUP_IDS", [])

    msg = FakeMessage(chat=FakeChat(id=1, type="private"), message_id=1, text="/ask hi")
    update = FakeUpdate(message=msg)
    qa = _FakeQA(raise_error=SearchError())
    ctx = FakeContext(application=FakeApplication(bot_data={"qa": qa}))

    _run(tg.cmd_ask(_as_update(update), _as_context(ctx)))

    expected = "Ошибка поиска в базе знаний. Попробуйте позже."
    assert msg.replies[-1] == expected


def test_cmd_ask_handles_llm_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "TELEGRAM_ALLOWED_USER_IDS", [])
    monkeypatch.setattr(settings, "TELEGRAM_ALLOWED_GROUP_IDS", [])

    msg = FakeMessage(chat=FakeChat(id=1, type="private"), message_id=1, text="/ask hi")
    update = FakeUpdate(message=msg)
    qa = _FakeQA(raise_error=LLMError(preview="preview"))
    ctx = FakeContext(application=FakeApplication(bot_data={"qa": qa}))

    _run(tg.cmd_ask(_as_update(update), _as_context(ctx)))

    assert msg.replies[-1].startswith("Ошибка LLM.")


def test_cmd_ask_success(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "TELEGRAM_ALLOWED_USER_IDS", [])
    monkeypatch.setattr(settings, "TELEGRAM_ALLOWED_GROUP_IDS", [])

    answer = QAAnswer(kind="llm", text="answer", hits=1, context_chars=10)
    msg = FakeMessage(chat=FakeChat(id=1, type="private"), message_id=1, text="/ask hi")
    update = FakeUpdate(message=msg)
    qa = _FakeQA(answer=answer)
    ctx = FakeContext(application=FakeApplication(bot_data={"qa": qa}))

    _run(tg.cmd_ask(_as_update(update), _as_context(ctx)))

    assert msg.replies[-1] == "answer"
