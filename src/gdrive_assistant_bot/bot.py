import os

import structlog
from telegram.ext import Application

from .adapters.llm import make_llm_client
from .adapters.telegram import register_handlers
from .core.qa.service import QAService
from .health import start_health_server
from .logging import setup_logging
from .rag import RAGStore
from .settings import settings
from .smoke_test import is_smoke_test_mode

_CLOSE_LOOP = False

log = structlog.get_logger("gdrive-assistant-bot.bot")


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
            "llm_enabled": settings.is_llm_enabled(),
        },
    )
    log.info("config", component="bot", flow="config", meta=settings.model_dump(mode="json"))

    if is_smoke_test_mode("bot", log=log):
        return

    try:
        store = RAGStore()
    except Exception:
        log.exception(
            "store_init_failed",
            component="bot",
            flow="startup",
            meta={"qdrant_url": str(settings.QDRANT_URL)},
        )
        raise
    llm = make_llm_client()
    qa = QAService(store, llm)

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

    app.bot_data["qa"] = qa
    register_handlers(app)

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
