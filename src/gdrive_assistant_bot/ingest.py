import os
import signal
import threading
import time

import structlog

from .core.ingest.limiter import RateLimiter
from .core.ingest.service import IngestService
from .extractors import init_extractors
from .health import start_health_server
from .logging import setup_logging
from .providers import init_providers
from .providers.registry import get_provider, list_providers
from .rag import RAGStore
from .settings import settings
from .smoke import is_smoke_test_mode

log = structlog.get_logger("gdrive-assistant-bot.ingest")


def _install_signal_handlers(stop_event: threading.Event) -> None:
    def _handler(signum: int, _frame) -> None:
        if not stop_event.is_set():
            log.warning(
                "shutdown_signal", component="ingest", flow="shutdown", meta={"signal": signum}
            )
            stop_event.set()

    signal.signal(signal.SIGTERM, _handler)
    signal.signal(signal.SIGINT, _handler)


def main() -> None:
    setup_logging()
    start_health_server(settings.HEALTH_HOST, settings.INGEST_HEALTH_PORT, component="ingest")

    stop_event = threading.Event()
    _install_signal_handlers(stop_event)

    log.info(
        "startup",
        component="ingest",
        flow="startup",
        meta={
            "pid": os.getpid(),
            "mode": settings.INGEST_MODE,
            "poll_seconds": settings.INGEST_POLL_SECONDS,
        },
    )
    log.info("config", component="ingest", flow="config", meta=settings.model_dump(mode="json"))

    if is_smoke_test_mode("ingest", log=log):
        return

    init_extractors()
    init_providers()

    provider = get_provider(settings.STORAGE_BACKEND)
    if provider is None:
        log.error(
            "provider_missing",
            component="ingest",
            flow="startup",
            meta={"provider": settings.STORAGE_BACKEND, "available": list(list_providers())},
        )
        raise ValueError(f"Unknown storage provider: {settings.STORAGE_BACKEND}")

    try:
        store = RAGStore()
    except Exception:
        log.exception(
            "store_init_failed",
            component="ingest",
            flow="startup",
            meta={"qdrant_url": str(settings.QDRANT_URL)},
        )
        raise

    limiter = RateLimiter(
        rate=settings.STORAGE_GOOGLE_DRIVE_API_RPS,
        burst=settings.STORAGE_GOOGLE_DRIVE_API_BURST,
        stop_event=stop_event,
    )

    service = IngestService(store, provider)

    if settings.INGEST_MODE == "once":
        service.run_once(limiter, stop_event)
        return

    service.run_loop(limiter, stop_event)

    grace = settings.INGEST_SHUTDOWN_GRACE_SECONDS
    if grace > 0:
        log.info(
            "shutdown_grace",
            component="ingest",
            flow="shutdown",
            meta={"shutdown_grace_seconds": grace},
        )
        time.sleep(grace)

    log.info("shutdown", component="ingest", flow="shutdown")


if __name__ == "__main__":
    main()
