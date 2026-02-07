from __future__ import annotations

import structlog
from telegram import Message, Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from ..core.qa.service import LLMError, QAAnswer, QAService, SearchError
from ..settings import settings

_MIN_CMD_PARTS = 2

log = structlog.get_logger("gdrive-assistant-bot.bot")


def _is_allowed(update: Update) -> bool:
    if not settings.is_telegram_private_mode():
        return True

    msg = update.effective_message
    if not msg:
        return False

    chat = msg.chat
    if not chat:
        return False

    if chat.type in ("group", "supergroup") and chat.id in settings.TELEGRAM_ALLOWED_GROUP_IDS:
        return True

    return bool(
        chat.type == "private"
        and msg.from_user
        and msg.from_user.id in settings.TELEGRAM_ALLOWED_USER_IDS
    )


def _message_meta(msg: Message, *, include_user: bool = False) -> dict[str, object]:
    meta: dict[str, object] = {"chat_id": msg.chat_id, "message_id": msg.message_id}
    if include_user:
        meta["has_user"] = bool(msg.from_user)
    return meta


async def _reply_service_unavailable(msg: Message, *, flow: str) -> None:
    log.error("service_missing", component="bot", flow=flow, meta=_message_meta(msg))
    await msg.reply_text("Сервис недоступен. Попробуйте позже.")


async def cmd_start(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_allowed(update):
        return

    msg = update.message
    if not msg:
        return

    await msg.reply_text(
        "🤖 Я — бот-ассистент для Google Drive.\n\n"
        "Команды:\n\n"
        "– /ask <вопрос> — найти ответ в базе знаний\n"
        "– /ingest <текст> — добавить информацию в базу знаний\n"
    )


async def cmd_ingest(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_allowed(update):
        return

    msg = update.message
    if not msg or not msg.text:
        return

    parts = msg.text.split(maxsplit=1)
    if len(parts) < _MIN_CMD_PARTS or not parts[1].strip():
        await msg.reply_text("Использование: /ingest <текст>")
        return

    qa: QAService | None = context.application.bot_data.get("qa")
    if not qa:
        await _reply_service_unavailable(msg, flow="telegram_ingest")
        return

    text = parts[1].strip()
    doc_id = f"telegram:{msg.chat_id}:{msg.message_id}"

    payload = {
        "file_id": doc_id,
        "file_name": "telegram_message",
        "file_type": "telegram",
        "modified_time": str(msg.date),
        "from_user": (msg.from_user.username if msg.from_user else None),
        "chat_id": str(msg.chat_id),
        "message_id": msg.message_id,
    }

    try:
        n = qa.ingest_text(
            text=text, payload=payload, doc_id=doc_id, source=f"telegram:{msg.chat_id}"
        )
    except Exception:
        log.exception(
            "telegram_ingest_failed",
            component="bot",
            flow="telegram_ingest",
            meta={**_message_meta(msg), "text_chars": len(text), "doc_id": doc_id},
        )
        await msg.reply_text("Ошибка добавления в базу знаний. Попробуйте позже.")
        return

    await msg.reply_text(f"Информация добавлена в базу знаний ({n} частей).")


async def _reply_answer(msg: Message, qa: QAService, answer: QAAnswer) -> None:
    if qa.llm is not None and answer.kind == "fragments":
        log.warning(
            "llm_call_response_empty",
            component="bot",
            flow="llm_call",
            meta={
                **_message_meta(msg, include_user=True),
                "hits": answer.hits,
                "context_chars": answer.context_chars,
                "model": settings.LLM_MODEL,
            },
        )
    await msg.reply_text(answer.text)


async def cmd_ask(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_allowed(update):
        return

    msg = update.message
    if not msg or not msg.text:
        return

    parts = msg.text.split(maxsplit=1)
    if len(parts) < _MIN_CMD_PARTS or not parts[1].strip():
        await msg.reply_text("Использование: /ask <вопрос>")
        return

    qa: QAService | None = context.application.bot_data.get("qa")
    if not qa:
        await _reply_service_unavailable(msg, flow="telegram_ask")
        return

    question = parts[1].strip()

    try:
        answer = qa.ask(question)
    except SearchError:
        log.exception(
            "search_failed",
            component="bot",
            flow="telegram_ask",
            meta={**_message_meta(msg), "question_chars": len(question)},
        )
        await msg.reply_text("Ошибка поиска в базе знаний. Попробуйте позже.")
        return
    except LLMError as exc:
        log.exception(
            "llm_call_failed",
            component="bot",
            flow="llm_call",
            meta={
                **_message_meta(msg, include_user=True),
                "question_chars": len(question),
                "hits": exc.hits,
                "context_chars": exc.context_chars,
                "model": settings.LLM_MODEL,
                "status": exc.status,
                "error_type": exc.error_type,
            },
        )
        await msg.reply_text("Ошибка LLM. Найденные фрагменты:\n\n" + exc.preview)
        return

    await _reply_answer(msg, qa, answer)


async def on_plain_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await cmd_start(update, context)


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    meta: dict[str, object] = {
        "has_update": update is not None,
        "update_type": type(update).__name__,
    }
    if isinstance(update, Update) and update.effective_message:
        msg = update.effective_message
        meta.update(_message_meta(msg, include_user=True))

    exc_info = None
    err = context.error
    if isinstance(err, BaseException):
        exc_info = (type(err), err, err.__traceback__)

    log.error(
        "telegram_update_failed",
        exc_info=exc_info,
        component="bot",
        flow="telegram_update",
        meta=meta,
    )

    if isinstance(update, Update) and update.effective_message:
        try:
            await update.effective_message.reply_text("Произошла ошибка. Попробуйте позже.")
        except Exception:
            log.exception(
                "telegram_update_reply_failed", component="bot", flow="telegram_update", meta=meta
            )


def register_handlers(app: Application) -> None:
    app.add_error_handler(on_error)
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("ingest", cmd_ingest))
    app.add_handler(CommandHandler("ask", cmd_ask))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_plain_text))
