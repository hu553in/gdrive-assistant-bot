import os
import random
import signal
import threading
import time
from collections.abc import Callable, Iterable
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from typing import Any, TypeVar

import structlog
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from .health import start_health_server
from .logging import setup_logging
from .rag import RAGStore
from .settings import settings

log = structlog.get_logger("gdrive-assistant-bot.ingest")

SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]

DOC_MIME = "application/vnd.google-apps.document"
SHEET_MIME = "application/vnd.google-apps.spreadsheet"
FOLDER_MIME = "application/vnd.google-apps.folder"

T = TypeVar("T")


class ShutdownRequested(RuntimeError):
    pass


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

        raise ShutdownRequested("shutdown requested")


_thread_local = threading.local()


def _file_log_meta(file_id: str | None, file_name: str | None, **extra: Any) -> dict[str, Any]:
    return {"file_id": file_id, "file_name": file_name, **extra}


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


def _execute_with_backoff[T](call: Callable[[], T], limiter: RateLimiter) -> T:
    retries = settings.GOOGLE_BACKOFF_RETRIES
    base_delay = settings.GOOGLE_BACKOFF_BASE_DELAY_SECONDS
    max_delay = settings.GOOGLE_BACKOFF_MAX_DELAY_SECONDS

    attempt = 0
    while True:
        limiter.acquire()
        try:
            return call()
        except HttpError as e:
            status = getattr(e, "status_code", None)
            if status is None and hasattr(e, "resp"):
                status = getattr(e.resp, "status", None)

            retryable = status in (429, 500, 502, 503, 504)

            if not retryable:
                raise

            attempt += 1
            if attempt > retries:
                raise

            delay = min(max_delay, base_delay * (2 ** (attempt - 1)))
            delay *= 0.7 + random.random() * 0.6

            log.warning(
                "google_api_retry",
                component="ingest",
                flow="google_api",
                meta={
                    "status": status,
                    "attempt": attempt,
                    "delay_seconds": round(delay, 2),
                    "max_retries": retries,
                    "backoff_base_seconds": base_delay,
                    "backoff_max_seconds": max_delay,
                },
            )
            time.sleep(delay)


def _list_children(drive, parent_id: str, limiter: RateLimiter) -> list[dict[str, Any]]:
    q = f"'{parent_id}' in parents and trashed=false"
    files: list[dict[str, Any]] = []
    page_token = None

    while True:
        pt = page_token
        resp = _execute_with_backoff(
            lambda pt=pt: drive.files()
            .list(
                q=q,
                fields="nextPageToken, files(id, name, mimeType, modifiedTime)",
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
            elif mime in (DOC_MIME, SHEET_MIME):
                yield f


def _list_all_accessible_files(drive, limiter: RateLimiter) -> list[dict[str, Any]]:
    q = f"trashed=false and (mimeType='{DOC_MIME}' or mimeType='{SHEET_MIME}')"
    files: list[dict[str, Any]] = []
    page_token = None

    while True:
        pt = page_token
        resp = _execute_with_backoff(
            lambda pt=pt: drive.files()
            .list(
                q=q,
                fields="nextPageToken, files(id, name, mimeType, modifiedTime)",
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


def _extract_doc_text(docs, doc_id: str, limiter: RateLimiter) -> str:
    doc = _execute_with_backoff(lambda: docs.documents().get(documentId=doc_id).execute(), limiter)
    body = (doc.get("body") or {}).get("content") or []

    out: list[str] = []
    for el in body:
        p = el.get("paragraph")
        if not p:
            continue
        for pe in p.get("elements") or []:
            tr = pe.get("textRun")
            if tr and "content" in tr:
                out.append(tr["content"])

    return "".join(out).replace("\u000b", "\n").strip()


def _extract_sheet_text(sheets, spreadsheet_id: str, limiter: RateLimiter) -> str:
    ss = _execute_with_backoff(
        lambda: sheets.spreadsheets().get(spreadsheetId=spreadsheet_id).execute(), limiter
    )
    sheet_infos = ss.get("sheets") or []

    lines: list[str] = []
    for s in sheet_infos:
        if not s or not isinstance(s, dict):
            continue
        title = (s.get("properties") or {}).get("title") or "Sheet"
        rng = f"'{title}'!A1:ZZ{settings.GOOGLE_MAX_ROWS_PER_SHEET}"
        resp = _execute_with_backoff(
            lambda rng=rng: sheets.spreadsheets()
            .values()
            .get(spreadsheetId=spreadsheet_id, range=rng)
            .execute(),
            limiter,
        )
        values = resp.get("values") or []
        if not values:
            continue

        lines.append(f"=== SHEET: {title} ===")
        for row in values:
            row_str = "\t".join(str(x).strip() for x in row if str(x).strip())
            if row_str:
                lines.append(row_str)

    return "\n".join(lines).strip()


def _ingest_one_file(
    store: RAGStore, file_meta: dict[str, Any], limiter: RateLimiter, stop_event: threading.Event
) -> str:
    """
    Returns status: ok | skipped_unchanged | skipped_empty
    """
    if stop_event.is_set():
        return "skipped_empty"

    fid = file_meta["id"]
    name = file_meta.get("name", fid)
    mime = file_meta.get("mimeType")
    mtime = file_meta.get("modifiedTime") or ""

    if mtime and store.exists_file_mtime(fid, mtime):
        return "skipped_unchanged"

    _, docs, sheets = _get_thread_clients()

    if mime == DOC_MIME:
        text = _extract_doc_text(docs, fid, limiter)
        ftype = "gdoc"
    elif mime == SHEET_MIME:
        text = _extract_sheet_text(sheets, fid, limiter)
        ftype = "gsheet"
    else:
        return "skipped_empty"

    if stop_event.is_set():
        return "skipped_empty"

    if not text.strip():
        return "skipped_empty"

    store.delete_by_file_id(fid)
    n = store.upsert_document(
        doc_id=fid,
        source="gdrive",
        text=text,
        payload={"file_id": fid, "file_name": name, "file_type": ftype, "modified_time": mtime},
    )

    log.info(
        "indexed",
        component="ingest",
        flow="ingest_file",
        meta=_file_log_meta(fid, name, chunks=n, file_type=ftype, modified_time=mtime),
    )
    return "ok"


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
