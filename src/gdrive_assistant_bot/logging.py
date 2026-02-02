import logging
import sys

import structlog

from .settings import settings


def setup_logging() -> None:
    """
    Logs to stdout.
    Default format is JSON (one line = one JSON object) for log aggregation tooling.
    Set LOG_PLAIN_TEXT=1 for plain text logs in development.
    """
    timestamper = structlog.processors.TimeStamper(fmt="iso", utc=True, key="timestamp")
    timestamperUnix = structlog.processors.TimeStamper(fmt=None, utc=True, key="timestamp_unix")

    shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        timestamper,
        timestamperUnix,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.StackInfoRenderer(),
    ]

    foreign_pre_chain = [*shared_processors]
    processors = [structlog.stdlib.filter_by_level, *shared_processors]

    if settings.LOG_PLAIN_TEXT:
        renderer = structlog.dev.ConsoleRenderer(timestamp_key="timestamp")
    else:
        renderer = structlog.processors.JSONRenderer(ensure_ascii=False)
        foreign_pre_chain.append(structlog.processors.format_exc_info)
        processors.append(structlog.processors.format_exc_info)

    processors.append(structlog.stdlib.ProcessorFormatter.wrap_for_formatter)

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.stdlib.BoundLogger,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(processor=renderer, foreign_pre_chain=foreign_pre_chain)
    )

    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(settings.LOG_LEVEL)
    root.addHandler(handler)

    # reduce noisy libs
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("googleapiclient.discovery_cache").setLevel(logging.ERROR)
