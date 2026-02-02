import os

import structlog
from openai import OpenAI, OpenAIError
from telegram import Message, Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from .health import start_health_server
from .logging import setup_logging
from .rag import RAGStore
from .settings import settings

_MIN_CMD_PARTS = 2
_CLOSE_LOOP = False

log = structlog.get_logger("gdrive-assistant-bot.bot")


def _is_allowed(update: Update) -> bool:
    if not settings.private_mode():
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
        and msg.from_user.id
        and msg.from_user.id in settings.TELEGRAM_ALLOWED_USER_IDS
    )


def _make_llm_client() -> OpenAI | None:
    if not settings.llm_enabled():
        return None
    return OpenAI(base_url=settings.LLM_BASE_URL, api_key=settings.LLM_API_KEY)


def _truncate_text(text: str, max_chars: int = 4000) -> str:
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "…\n\n…(информация обрезана)"


def _message_meta(msg: Message, *, include_user: bool = False) -> dict[str, object]:
    meta: dict[str, object] = {"chat_id": msg.chat_id, "message_id": msg.message_id}
    if include_user:
        meta["has_user"] = bool(msg.from_user)
    return meta


async def _reply_service_unavailable(msg: Message, *, flow: str) -> None:
    log.error("store_missing", component="bot", flow=flow, meta=_message_meta(msg))
    await msg.reply_text("Сервис недоступен. Попробуйте позже.")


async def cmd_start(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_allowed(update):
        return

    await update.message.reply_text(
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

    store: RAGStore | None = context.application.bot_data.get("store")
    if not store:
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
        n = store.upsert_document(
            doc_id=doc_id, source=f"telegram:{msg.chat_id}", text=text, payload=payload
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


async def cmd_ask(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:  # noqa: PLR0911
    if not _is_allowed(update):
        return

    msg = update.message
    if not msg or not msg.text:
        return

    parts = msg.text.split(maxsplit=1)
    if len(parts) < _MIN_CMD_PARTS or not parts[1].strip():
        await msg.reply_text("Использование: /ask <вопрос>")
        return

    store: RAGStore | None = context.application.bot_data.get("store")
    if not store:
        await _reply_service_unavailable(msg, flow="telegram_ask")
        return

    llm: OpenAI | None = context.application.bot_data.get("llm")

    question = parts[1].strip()

    try:
        hits = store.search(question)
        context_text = store.build_context(hits, max_chars=settings.MAX_CONTEXT_CHARS)
    except Exception:
        log.exception(
            "search_failed",
            component="bot",
            flow="telegram_ask",
            meta={**_message_meta(msg), "question_chars": len(question)},
        )
        await msg.reply_text("Ошибка поиска в базе знаний. Попробуйте позже.")
        return

    if not context_text.strip():
        await msg.reply_text("Ничего не найдено.")
        return

    if not llm:
        preview = _truncate_text(context_text)
        await msg.reply_text("LLM не настроена. Найденные фрагменты:\n\n" + preview)
        return

    prompt = f"Контекст:\n\n{context_text}\n\nВопрос пользователя:\n\n{question}"

    log_meta = {
        **_message_meta(msg, include_user=True),
        "question_chars": len(question),
        "hits": len(hits),
        "context_chars": len(context_text),
        "model": settings.LLM_MODEL,
    }

    try:
        resp = llm.chat.completions.create(
            model=settings.LLM_MODEL,
            messages=[
                {"role": "system", "content": settings.LLM_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
        )
        if not resp.choices:
            log.warning("llm_call_response_empty", component="bot", flow="llm_call", meta=log_meta)
            preview = _truncate_text(context_text)
            await msg.reply_text("Пустой ответ от LLM. Найденные фрагменты:\n\n" + preview)
            return
        answer = _truncate_text((resp.choices[0].message.content or "").strip()) or "Пустой ответ"
        await msg.reply_text(answer)
    except OpenAIError as e:
        status = getattr(e, "status_code", None)
        log.exception(
            "llm_call_failed", component="bot", flow="llm_call", meta={**log_meta, "status": status}
        )
        preview = _truncate_text(context_text)
        await msg.reply_text("Ошибка LLM. Найденные фрагменты:\n\n" + preview)
    except Exception as e:
        log.exception(
            "llm_call_failed",
            component="bot",
            flow="llm_call",
            meta={**log_meta, "error_type": type(e).__name__},
        )
        preview = _truncate_text(context_text)
        await msg.reply_text("Ошибка LLM. Найденные фрагменты:\n\n" + preview)


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


def main() -> None:
    setup_logging()
    start_health_server(settings.HEALTH_HOST, settings.BOT_HEALTH_PORT, component="bot")

    log.info(
        "startup",
        component="bot",
        flow="startup",
        meta={
            "pid": os.getpid(),
            "health_port": settings.BOT_HEALTH_PORT,
            "llm_enabled": settings.llm_enabled(),
        },
    )
    log.info("config", component="bot", flow="config", meta=settings.safe_dump())

    try:
        store = RAGStore()
    except Exception:
        log.exception(
            "store_init_failed",
            component="bot",
            flow="startup",
            meta={"qdrant_url": settings.QDRANT_URL},
        )
        raise
    llm = _make_llm_client()

    try:
        app = Application.builder().token(settings.TELEGRAM_BOT_TOKEN).build()
    except Exception:
        log.exception(
            "telegram_app_init_failed",
            component="bot",
            flow="startup",
            meta={"token_set": bool(settings.TELEGRAM_BOT_TOKEN)},
        )
        raise
    app.bot_data["store"] = store
    app.bot_data["llm"] = llm

    app.add_error_handler(on_error)
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("ingest", cmd_ingest))
    app.add_handler(CommandHandler("ask", cmd_ask))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_plain_text))

    log.info("polling", component="bot", flow="polling", meta={"close_loop": _CLOSE_LOOP})
    try:
        app.run_polling(close_loop=_CLOSE_LOOP)
    except Exception:
        log.exception(
            "polling_failed", component="bot", flow="polling", meta={"close_loop": _CLOSE_LOOP}
        )
        raise


if __name__ == "__main__":
    main()
