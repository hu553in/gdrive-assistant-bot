import logging
import random
import signal
import threading
import time
from collections.abc import Callable, Iterable
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from typing import Any, TypeVar

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from .health import start_health_server
from .logging import setup_logging
from .rag import RAGStore
from .settings import settings

log = logging.getLogger("gdrive-assistant-bot.ingest")

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
    base_delay = settings.GOOGLE_BACKOFF_BASE_DELAY
    max_delay = settings.GOOGLE_BACKOFF_MAX_DELAY

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
            attempt += 1

            if not retryable or attempt > retries:
                raise

            delay = min(max_delay, base_delay * (2 ** (attempt - 1)))
            delay *= 0.7 + random.random() * 0.6

            log.warning(
                "google_api_retry",
                extra={
                    "component": "ingest",
                    "event": "retry",
                    "count": {"status": status, "attempt": attempt, "delay": round(delay, 2)},
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
        extra={
            "component": "ingest",
            "event": "indexed",
            "file_id": fid,
            "file_name": name,
            "count": {"chunks": n},
        },
    )
    return "ok"


def ingest_once(store: RAGStore, limiter: RateLimiter, stop_event: threading.Event) -> None:  # noqa: PLR0912, PLR0915
    drive, _, _ = _get_thread_clients()

    if settings.ALL_ACCESSIBLE:
        files = _list_all_accessible_files(drive, limiter)
        log.warning(
            "all_accessible_enabled",
            extra={"component": "ingest", "event": "scope", "count": {"files": len(files)}},
        )
    else:
        files = list(_walk_recursive(drive, settings.GOOGLE_DRIVE_FOLDER_IDS, limiter, stop_event))
        log.info(
            "folder_recursive_scope",
            extra={
                "component": "ingest",
                "event": "scope",
                "count": {"roots": settings.GOOGLE_DRIVE_FOLDER_IDS, "files": len(files)},
            },
        )

    total = len(files)
    if total == 0:
        log.info(
            "nothing_to_ingest",
            extra={"component": "ingest", "event": "done", "count": {"total": 0}},
        )
        return

    workers = min(settings.INGEST_WORKERS, total)
    log.info(
        "parallelism",
        extra={"component": "ingest", "event": "workers", "count": {"workers": workers}},
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
            and (completed % settings.INGEST_PROGRESS_EVERY) != 0
            and (now - last_progress_ts) < settings.INGEST_PROGRESS_SECONDS
        ):
            return

        last_progress_ts = now
        elapsed_ms = int((now - t0) * 1000)
        log.info(
            "progress",
            extra={
                "component": "ingest",
                "event": "progress",
                "elapsed_ms": elapsed_ms,
                "count": {
                    "completed": completed,
                    "total": total,
                    "ok": ok,
                    "fail": fail,
                    "skipped_unchanged": skipped_unchanged,
                    "skipped_empty": skipped_empty,
                    "in_flight": len(in_flight),
                },
            },
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
                    meta = fut_meta.pop(fut, {})
                    fid = meta.get("id")
                    name = meta.get("name", fid)

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
                            extra={
                                "component": "ingest",
                                "event": "failed",
                                "file_id": fid,
                                "file_name": name,
                            },
                        )

                    completed += 1
                    progress(force=False)

                    submit_one(executor)

            progress(force=True)

    except ShutdownRequested:
        stop_event.set()
        progress(force=True)

    elapsed_ms = int((time.time() - t0) * 1000)
    log.info(
        "ingest_done",
        extra={
            "component": "ingest",
            "event": "done",
            "elapsed_ms": elapsed_ms,
            "count": {
                "ok": ok,
                "fail": fail,
                "skipped_unchanged": skipped_unchanged,
                "skipped_empty": skipped_empty,
                "total": total,
                "completed": completed,
                "stopped": stop_event.is_set(),
            },
        },
    )


def _install_signal_handlers(stop_event: threading.Event) -> None:
    def _handler(signum: int, _frame) -> None:
        if not stop_event.is_set():
            log.warning(
                "shutdown_signal",
                extra={
                    "component": "ingest",
                    "event": "shutdown_signal",
                    "count": {"signal": signum},
                },
            )
            stop_event.set()

    signal.signal(signal.SIGTERM, _handler)
    signal.signal(signal.SIGINT, _handler)


def main() -> None:
    setup_logging()
    start_health_server(settings.HEALTH_HOST, settings.INGEST_HEALTH_PORT, component="ingest")

    stop_event = threading.Event()
    _install_signal_handlers(stop_event)

    log.info("startup", extra={"component": "ingest", "event": "startup"})
    log.info(
        "config", extra={"component": "ingest", "event": "config", "count": settings.safe_dump()}
    )

    store = RAGStore()
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
            extra={"component": "ingest", "event": "shutdown_grace", "count": {"seconds": grace}},
        )
        time.sleep(grace)

    log.info("shutdown", extra={"component": "ingest", "event": "shutdown"})


if __name__ == "__main__":
    main()
