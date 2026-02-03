import os
import signal
import threading
import time
from collections.abc import Iterable
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from typing import Any

import structlog
from google.oauth2 import service_account
from googleapiclient.discovery import build

from .errors import ShutdownRequested
from .extractors import init_extractors
from .extractors.registry import get_drive_query_terms, get_extractor
from .extractors.utils import download_binary, download_export, execute_with_backoff
from .health import start_health_server
from .logging import setup_logging
from .rag import RAGStore
from .settings import settings

log = structlog.get_logger("gdrive-assistant-bot.ingest")

SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]

FOLDER_MIME = "application/vnd.google-apps.folder"
SHORTCUT_MIME = "application/vnd.google-apps.shortcut"
init_extractors()


class RateLimiter:
    """
    Token bucket limiter:
      - rate: tokens/sec
      - burst: max bucket size
    acquire() blocks until token available or stop_event set.
    """

    def __init__(self, *, rate: float, burst: float, stop_event: threading.Event) -> None:
        self.rate = float(rate)
        self.capacity = float(burst)
        self.tokens = float(burst)
        self.updated = time.monotonic()
        self.lock = threading.Lock()
        self.stop_event = stop_event

    def acquire(self) -> None:
        while not self.stop_event.is_set():
            with self.lock:
                now = time.monotonic()
                elapsed = now - self.updated
                if elapsed > 0:
                    self.tokens = min(self.capacity, self.tokens + elapsed * self.rate)
                    self.updated = now

                if self.tokens >= 1.0:
                    self.tokens -= 1.0
                    return

                needed = 1.0 - self.tokens
                sleep_for = max(0.001, needed / self.rate)

            self.stop_event.wait(timeout=sleep_for)

        raise ShutdownRequested()


_thread_local = threading.local()


def _file_log_meta(file_id: str | None, file_name: str | None, **extra: Any) -> dict[str, Any]:
    return {"file_id": file_id, "file_name": file_name, **extra}


def _is_shortcut(file_meta: dict[str, Any]) -> bool:
    return file_meta.get("mimeType") == SHORTCUT_MIME


def _ingest_stats_meta(  # noqa: PLR0913
    *,
    total: int,
    completed: int,
    ok: int,
    fail: int,
    skipped_unchanged: int,
    skipped_empty: int,
    workers: int,
    elapsed_ms: int,
    in_flight: int | None = None,
    stopped: bool | None = None,
    mode: str | None = None,
) -> dict[str, Any]:
    meta: dict[str, Any] = {
        "completed": completed,
        "total": total,
        "ok": ok,
        "fail": fail,
        "skipped_unchanged": skipped_unchanged,
        "skipped_empty": skipped_empty,
        "workers": workers,
        "elapsed_ms": elapsed_ms,
    }
    if in_flight is not None:
        meta["in_flight"] = in_flight
    if stopped is not None:
        meta["stopped"] = stopped
    if mode is not None:
        meta["mode"] = mode
    return meta


def _get_thread_clients():
    """
    googleapiclient clients are not guaranteed thread-safe -> keep per-thread instances.
    """
    if getattr(_thread_local, "creds", None) is None:
        _thread_local.creds = service_account.Credentials.from_service_account_file(
            settings.GOOGLE_SERVICE_ACCOUNT_JSON, scopes=SCOPES
        )
        _thread_local.drive = build(
            "drive", "v3", credentials=_thread_local.creds, cache_discovery=False
        )
        _thread_local.docs = build(
            "docs", "v1", credentials=_thread_local.creds, cache_discovery=False
        )
        _thread_local.sheets = build(
            "sheets", "v4", credentials=_thread_local.creds, cache_discovery=False
        )

    return _thread_local.drive, _thread_local.docs, _thread_local.sheets


def _get_extraction_context(limiter: RateLimiter, stop_event: threading.Event):
    drive, docs, sheets = _get_thread_clients()

    class Context:
        pass

    ctx = Context()
    ctx.limiter = limiter
    ctx.stop_event = stop_event
    ctx.settings = settings
    ctx.drive = drive
    ctx.docs = docs
    ctx.sheets = sheets
    ctx.execute_with_backoff = lambda call: execute_with_backoff(call, limiter)
    ctx.download_binary = lambda file_id: download_binary(drive, file_id, limiter, stop_event)
    ctx.download_export = lambda file_id, mime: download_export(
        drive, file_id, mime, limiter, stop_event
    )
    return ctx


def _list_children(drive, parent_id: str, limiter: RateLimiter) -> list[dict[str, Any]]:
    q = f"'{parent_id}' in parents and trashed=false"
    files: list[dict[str, Any]] = []
    page_token = None

    while True:
        pt = page_token
        resp = execute_with_backoff(
            lambda pt=pt: drive.files()
            .list(
                q=q,
                fields=(
                    "nextPageToken, files(id, name, mimeType, modifiedTime, "
                    "size, fileExtension, shortcutDetails)"
                ),
                pageToken=pt,
                pageSize=1000,
            )
            .execute(),
            limiter,
        )
        files.extend(resp.get("files") or [])
        page_token = resp.get("nextPageToken")
        if not page_token:
            break

    return files


def _walk_recursive(
    drive, root_ids: Iterable[str], limiter: RateLimiter, stop_event: threading.Event
) -> Iterable[dict[str, Any]]:
    stack = list(root_ids)
    seen: set[str] = set()

    while stack and not stop_event.is_set():
        folder_id = stack.pop()
        if folder_id in seen:
            continue
        seen.add(folder_id)

        for f in _list_children(drive, folder_id, limiter):
            if stop_event.is_set():
                break
            mime = f.get("mimeType")
            if mime == FOLDER_MIME:
                stack.append(f["id"])
            elif _is_shortcut(f):
                log.debug(
                    "shortcut_skipped",
                    component="ingest",
                    flow="walk_recursive",
                    meta={"file_id": f.get("id"), "file_name": f.get("name")},
                )
            elif get_extractor(f) is not None:
                yield f


def _list_all_accessible_files(drive, limiter: RateLimiter) -> list[dict[str, Any]]:
    terms = get_drive_query_terms()
    if terms:
        mime_conditions = " or ".join(terms)
        q = f"trashed=false and ({mime_conditions})"
    else:
        q = "trashed=false"
    files: list[dict[str, Any]] = []
    page_token = None

    while True:
        pt = page_token
        resp = execute_with_backoff(
            lambda pt=pt: drive.files()
            .list(
                q=q,
                fields=(
                    "nextPageToken, files(id, name, mimeType, modifiedTime, "
                    "size, fileExtension, shortcutDetails)"
                ),
                pageToken=pt,
                pageSize=1000,
            )
            .execute(),
            limiter,
        )
        files.extend(resp.get("files") or [])
        page_token = resp.get("nextPageToken")
        if not page_token:
            break

    return [f for f in files if not _is_shortcut(f) and get_extractor(f) is not None]


def _ingest_one_file(
    store: RAGStore, file_meta: dict[str, Any], limiter: RateLimiter, stop_event: threading.Event
) -> str:
    """
    Returns status: ok | skipped_unchanged | skipped_empty
    """
    status = "skipped_empty"
    if stop_event.is_set():
        return status

    fid = file_meta["id"]
    name = file_meta.get("name", fid)
    mime = file_meta.get("mimeType")
    mtime = file_meta.get("modifiedTime") or ""

    if mtime and store.exists_file_mtime(fid, mtime):
        return "skipped_unchanged"

    if _is_shortcut(file_meta):
        log.debug(
            "shortcut_skipped",
            component="ingest",
            flow="ingest_file",
            meta={"file_id": fid, "file_name": name},
        )
        return status

    extractor = get_extractor(file_meta)
    if extractor is None:
        log.debug(
            "unsupported_file_type",
            component="ingest",
            flow="ingest_file",
            meta={"file_id": fid, "file_name": name, "mime_type": mime},
        )
        return status

    context = _get_extraction_context(limiter, stop_event)
    try:
        result = extractor.extract(file_meta, context)
    except ShutdownRequested:
        raise
    except Exception:
        log.exception(
            "extraction_failed",
            component="ingest",
            flow="ingest_file",
            meta={"file_id": fid, "file_name": name, "mime_type": mime},
        )
        return status

    if not stop_event.is_set() and result.text.strip():
        payload = {
            "file_id": fid,
            "file_name": name,
            "file_type": result.file_type,
            "modified_time": mtime,
            **result.metadata,
        }
        store.delete_by_file_id(fid)
        n = store.upsert_document(doc_id=fid, source="gdrive", text=result.text, payload=payload)

        log.info(
            "indexed",
            component="ingest",
            flow="ingest_file",
            meta=_file_log_meta(
                fid, name, chunks=n, file_type=result.file_type, modified_time=mtime
            ),
        )
        status = "ok"

    return status


def ingest_once(store: RAGStore, limiter: RateLimiter, stop_event: threading.Event) -> None:  # noqa: PLR0912, PLR0915
    try:
        drive, _, _ = _get_thread_clients()
    except Exception:
        log.exception(
            "google_client_init_failed",
            component="ingest",
            flow="google_api",
            meta={"service_account_path": settings.GOOGLE_SERVICE_ACCOUNT_JSON},
        )
        raise

    try:
        if settings.ALL_ACCESSIBLE:
            files = _list_all_accessible_files(drive, limiter)
            log.warning(
                "all_accessible_enabled",
                component="ingest",
                flow="ingest_scope",
                meta={"files": len(files), "all_accessible": True},
            )
        else:
            files = list(
                _walk_recursive(drive, settings.GOOGLE_DRIVE_FOLDER_IDS, limiter, stop_event)
            )
            log.info(
                "folder_recursive_scope",
                component="ingest",
                flow="ingest_scope",
                meta={
                    "roots": settings.GOOGLE_DRIVE_FOLDER_IDS,
                    "files": len(files),
                    "all_accessible": False,
                },
            )
    except Exception:
        log.exception(
            "ingest_scope_failed",
            component="ingest",
            flow="ingest_scope",
            meta={
                "all_accessible": settings.ALL_ACCESSIBLE,
                "roots": settings.GOOGLE_DRIVE_FOLDER_IDS,
            },
        )
        raise

    total = len(files)
    if total == 0:
        log.info(
            "nothing_to_ingest",
            component="ingest",
            flow="ingest",
            meta={"total": 0, "mode": settings.INGEST_MODE},
        )
        return

    workers = min(settings.INGEST_WORKERS, total)
    log.info(
        "parallelism",
        component="ingest",
        flow="ingest",
        meta={"workers": workers, "total": total, "configured_workers": settings.INGEST_WORKERS},
    )

    ok = fail = skipped_unchanged = skipped_empty = 0
    completed = 0

    t0 = time.time()
    last_progress_ts = time.time()

    it = iter(files)
    in_flight: set[Future[str]] = set()
    fut_meta: dict[Future[str], dict[str, Any]] = {}

    def submit_one(executor: ThreadPoolExecutor) -> bool:
        if stop_event.is_set():
            return False
        try:
            f = next(it)
        except StopIteration:
            return False
        fut = executor.submit(_ingest_one_file, store, f, limiter, stop_event)
        in_flight.add(fut)
        fut_meta[fut] = f
        return True

    def progress(force: bool = False) -> None:
        nonlocal last_progress_ts
        now = time.time()
        if (
            not force
            and (completed % settings.INGEST_PROGRESS_FILES) != 0
            and (now - last_progress_ts) < settings.INGEST_PROGRESS_SECONDS
        ):
            return

        last_progress_ts = now
        elapsed_ms = int((now - t0) * 1000)
        log.info(
            "progress",
            component="ingest",
            flow="ingest",
            meta=_ingest_stats_meta(
                total=total,
                completed=completed,
                ok=ok,
                fail=fail,
                skipped_unchanged=skipped_unchanged,
                skipped_empty=skipped_empty,
                workers=workers,
                elapsed_ms=elapsed_ms,
                in_flight=len(in_flight),
            ),
        )

    try:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            for _ in range(workers):
                if not submit_one(executor):
                    break

            while in_flight:
                if stop_event.is_set():
                    break

                done, _ = wait(in_flight, timeout=1.0, return_when=FIRST_COMPLETED)
                if not done:
                    progress(force=False)
                    continue

                for fut in done:
                    in_flight.remove(fut)
                    file_meta = fut_meta.pop(fut, {})
                    fid = file_meta.get("id")
                    name = file_meta.get("name", fid)

                    try:
                        status = fut.result()
                        if status == "ok":
                            ok += 1
                        elif status == "skipped_unchanged":
                            skipped_unchanged += 1
                        else:
                            skipped_empty += 1
                    except ShutdownRequested:
                        stop_event.set()
                        skipped_empty += 1
                    except Exception:
                        fail += 1
                        log.exception(
                            "ingest_failed",
                            component="ingest",
                            flow="ingest_file",
                            meta=_file_log_meta(
                                fid,
                                name,
                                mime_type=file_meta.get("mimeType"),
                                modified_time=file_meta.get("modifiedTime"),
                            ),
                        )

                    completed += 1
                    progress(force=False)

                    submit_one(executor)

            progress(force=True)

    except ShutdownRequested:
        stop_event.set()
        progress(force=True)
    except Exception:
        elapsed_ms = int((time.time() - t0) * 1000)
        log.exception(
            "ingest_run_failed",
            component="ingest",
            flow="ingest",
            meta=_ingest_stats_meta(
                total=total,
                completed=completed,
                ok=ok,
                fail=fail,
                skipped_unchanged=skipped_unchanged,
                skipped_empty=skipped_empty,
                workers=workers,
                elapsed_ms=elapsed_ms,
                stopped=stop_event.is_set(),
            ),
        )
        raise

    elapsed_ms = int((time.time() - t0) * 1000)
    log.info(
        "ingest_done",
        component="ingest",
        flow="ingest",
        meta=_ingest_stats_meta(
            total=total,
            completed=completed,
            ok=ok,
            fail=fail,
            skipped_unchanged=skipped_unchanged,
            skipped_empty=skipped_empty,
            workers=workers,
            elapsed_ms=elapsed_ms,
            stopped=stop_event.is_set(),
            mode=settings.INGEST_MODE,
        ),
    )


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
    log.info("config", component="ingest", flow="config", meta=settings.safe_dump())

    try:
        store = RAGStore()
    except Exception:
        log.exception(
            "store_init_failed",
            component="ingest",
            flow="startup",
            meta={"qdrant_url": settings.QDRANT_URL},
        )
        raise
    limiter = RateLimiter(
        rate=settings.GOOGLE_API_RPS, burst=settings.GOOGLE_API_BURST, stop_event=stop_event
    )

    if settings.INGEST_MODE == "once":
        ingest_once(store, limiter, stop_event)
        return

    while not stop_event.is_set():
        ingest_once(store, limiter, stop_event)
        stop_event.wait(timeout=settings.INGEST_POLL_SECONDS)

    grace = settings.INGEST_SHUTDOWN_GRACE_SECONDS
    if grace > 0:
        log.info(
            "shutdown_grace",
            component="ingest",
            flow="shutdown",
            meta={"shutdown_grace_seconds": grace},
        )
        time.sleep(grace)

    log.info("shutdown", component="ingest", flow="shutdown", meta={"stopped": stop_event.is_set()})


if __name__ == "__main__":
    main()
