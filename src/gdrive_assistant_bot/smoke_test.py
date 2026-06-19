import os
import time

import structlog


def is_smoke_test_mode(component: str, *, log: structlog.BoundLogger) -> bool:
    raw = os.getenv("SMOKE_TEST_SECONDS", "")
    if not raw:
        return False
    try:
        seconds = float(raw.strip())
    except ValueError:
        log.warning(
            "smoke_test_seconds_invalid",
            component=component,
            flow="smoke_test",
            meta={"value": raw},
        )
        return False
    if seconds <= 0:
        log.warning(
            "smoke_test_seconds_non_positive",
            component=component,
            flow="smoke_test",
            meta={"seconds": seconds},
        )
        return False
    log.info(
        "smoke_test_mode_enabled", component=component, flow="smoke_test", meta={"seconds": seconds}
    )
    time.sleep(seconds)
    log.info(
        "smoke_test_mode_completed",
        component=component,
        flow="smoke_test",
        meta={"seconds": seconds},
    )
    return True
