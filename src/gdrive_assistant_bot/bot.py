import logging

from openai import OpenAI
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from .health import start_health_server
from .logging import setup_logging
from .rag import RAGStore
from .settings import settings

_MIN_CMD_PARTS = 2

log = logging.getLogger("gdrive-assistant-bot.bot")


def _make_llm_client() -> OpenAI | None:
    if not settings.llm_enabled():
        return None
    return OpenAI(base_url=settings.LLM_BASE_URL, api_key=settings.LLM_API_KEY)


def _truncate_text(text: str, max_chars: int = 4000) -> str:
    return text[:max_chars] + "…\n\n…(информация обрезана)" if len(text) > max_chars else text


async def cmd_start(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "🤖 Я — бот-ассистент для Google Drive.\n\n"
        "Команды:\n\n"
        "– /ask <вопрос> — найти ответ в базе знаний\n"
        "– /ingest <текст> — добавить информацию в базу знаний\n"
    )


async def cmd_ingest(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.message
    if not msg or not msg.text:
        return

    parts = msg.text.split(maxsplit=1)
    if len(parts) < _MIN_CMD_PARTS or not parts[1].strip():
        await msg.reply_text("Использование: /ingest <текст>")
        return

    store: RAGStore = context.application.bot_data["store"]

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

    n = store.upsert_document(
        doc_id=doc_id, source=f"telegram:{msg.chat_id}", text=text, payload=payload
    )
    await msg.reply_text(f"Информация добавлена в базу знаний ({n} частей)")


async def cmd_ask(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.message
    if not msg or not msg.text:
        return

    parts = msg.text.split(maxsplit=1)
    if len(parts) < _MIN_CMD_PARTS or not parts[1].strip():
        await msg.reply_text("Использование: /ask <вопрос>")
        return

    store: RAGStore = context.application.bot_data["store"]
    llm: OpenAI | None = context.application.bot_data["llm"]

    question = parts[1].strip()

    hits = store.search(question)
    context_text = store.build_context(hits, max_chars=settings.MAX_CONTEXT_CHARS)

    if not context_text.strip():
        await msg.reply_text("Ничего не найдено")
        return

    if not llm:
        preview = _truncate_text(context_text)
        await msg.reply_text("Языковая модель не настроена. Найденные фрагменты:\n\n" + preview)
        return

    prompt = f"Контекст:\n\n{context_text}\n\nВопрос пользователя:\n\n{question}"

    try:
        resp = llm.chat.completions.create(
            model=settings.LLM_MODEL,
            messages=[
                {"role": "system", "content": settings.LLM_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
        )
        answer = _truncate_text((resp.choices[0].message.content or "").strip()) or "Пустой ответ"
        await msg.reply_text(answer)
    except Exception:
        log.exception("llm_call_failed", extra={"component": "bot", "event": "llm_failed"})
        await msg.reply_text("Ошибка языковой модели")


async def on_plain_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await cmd_start(update, context)


def main() -> None:
    setup_logging()
    start_health_server(settings.HEALTH_HOST, settings.BOT_HEALTH_PORT, component="bot")

    log.info("startup", extra={"component": "bot", "event": "startup"})
    log.info("config", extra={"component": "bot", "event": "config", "count": settings.safe_dump()})

    store = RAGStore()
    llm = _make_llm_client()

    app = Application.builder().token(settings.TELEGRAM_BOT_TOKEN).build()
    app.bot_data["store"] = store
    app.bot_data["llm"] = llm

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("ingest", cmd_ingest))
    app.add_handler(CommandHandler("ask", cmd_ask))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_plain_text))

    log.info("polling", extra={"component": "bot", "event": "polling"})
    app.run_polling(close_loop=False)


if __name__ == "__main__":
    main()
