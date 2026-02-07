from __future__ import annotations

import threading
import time
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from typing import Any, Literal, Protocol, cast

import structlog

from ...errors import ShutdownRequested
from ...extractors.registry import (
    get_extractor,
    get_supported_extensions,
    get_supported_mime_prefixes,
    get_supported_mimes,
)
from ...providers.base import FileTypeFilter, Limiter, StorageFileMeta, StorageProvider
from ...settings import settings

log = structlog.get_logger("gdrive-assistant-bot.ingest")

# Status codes returned by IngestService.
IngestStatus = Literal[
    "ok", "failed", "skipped_unchanged", "skipped_empty", "skipped_unsupported", "skipped_stopped"
]


class IngestStore(Protocol):
    """Store contract required by ingest."""

    def exists_file_mtime(self, file_id: str, modified_time: str) -> bool: ...

    def delete_by_file_id(self, file_id: str) -> None: ...

    def upsert_document(
        self, *, doc_id: str, source: str, text: str, payload: dict[str, Any]
    ) -> int: ...


class IngestService:
    """Ingest pipeline that lists files, extracts content, and writes to the store."""

    def __init__(self, store: IngestStore, provider: StorageProvider) -> None:
        self.store = store
        self.provider = provider

    @staticmethod
    def _file_log_meta(file_id: str | None, file_name: str | None, **extra: Any) -> dict[str, Any]:
        return {"file_id": file_id, "file_name": file_name, **extra}

    @staticmethod
    def _ingest_stats_meta(  # noqa: PLR0913
        *,
        total: int,
        completed: int,
        ok: int,
        fail: int,
        skipped_unchanged: int,
        skipped_empty: int,
        skipped_unsupported: int,
        skipped_stopped: int,
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
            "skipped_unsupported": skipped_unsupported,
            "skipped_stopped": skipped_stopped,
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

    def _build_filter(self) -> FileTypeFilter:
        return FileTypeFilter(
            mime_types=get_supported_mimes(),
            mime_prefixes=get_supported_mime_prefixes(),
            extensions=get_supported_extensions(),
        )

    def _ingest_one_file(
        self, file_meta: StorageFileMeta, limiter: Limiter, stop_event: threading.Event
    ) -> IngestStatus:
        if stop_event.is_set():
            return "skipped_stopped"

        fid = file_meta.id
        name = file_meta.name or fid
        mime = file_meta.mime_type
        mtime = file_meta.modified_time or ""

        if mtime and self.store.exists_file_mtime(fid, mtime):
            return "skipped_unchanged"

        extractor_meta = file_meta.as_extractor_meta()
        extractor = get_extractor(extractor_meta)
        if extractor is None:
            log.debug(
                "unsupported_file_type",
                component="ingest",
                flow="ingest_file",
                meta={"file_id": fid, "file_name": name, "mime_type": mime},
            )
            return "skipped_unsupported"

        context = self.provider.build_extraction_context(limiter, stop_event)
        try:
            result = extractor.extract(extractor_meta, context)
        except ShutdownRequested:
            raise
        except Exception:
            log.exception(
                "extraction_failed",
                component="ingest",
                flow="ingest_file",
                meta={"file_id": fid, "file_name": name, "mime_type": mime},
            )
            return "failed"

        if stop_event.is_set() or not result.text.strip():
            return "skipped_stopped" if stop_event.is_set() else "skipped_empty"

        payload = {
            "file_id": fid,
            "file_name": name,
            "file_type": result.file_type,
            "modified_time": mtime,
            **result.metadata,
        }
        self.store.delete_by_file_id(fid)
        n = self.store.upsert_document(
            doc_id=fid, source=self.provider.name, text=result.text, payload=payload
        )

        log.info(
            "indexed",
            component="ingest",
            flow="ingest_file",
            meta=self._file_log_meta(
                fid, name, chunks=n, file_type=result.file_type, modified_time=mtime
            ),
        )
        return "ok"

    def run_once(self, limiter: Limiter, stop_event: threading.Event) -> None:  # noqa: PLR0912, PLR0915
        file_filter = self._build_filter()
        try:
            files = list(self.provider.list_files(file_filter, limiter, stop_event))
        except Exception:
            log.exception(
                "ingest_scope_failed",
                component="ingest",
                flow="ingest_scope",
                meta={"provider": self.provider.name},
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
            meta={
                "workers": workers,
                "total": total,
                "configured_workers": settings.INGEST_WORKERS,
            },
        )

        ok = fail = skipped_unchanged = skipped_empty = skipped_unsupported = skipped_stopped = 0
        completed = 0

        t0 = time.time()
        last_progress_ts = time.time()

        it = iter(files)
        in_flight: set[Future[IngestStatus]] = set()
        fut_meta: dict[Future[IngestStatus], StorageFileMeta] = {}

        def submit_one(executor: ThreadPoolExecutor) -> bool:
            if stop_event.is_set():
                return False
            try:
                f = next(it)
            except StopIteration:
                return False
            fut = cast(
                Future[IngestStatus], executor.submit(self._ingest_one_file, f, limiter, stop_event)
            )
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
                meta=self._ingest_stats_meta(
                    total=total,
                    completed=completed,
                    ok=ok,
                    fail=fail,
                    skipped_unchanged=skipped_unchanged,
                    skipped_empty=skipped_empty,
                    skipped_unsupported=skipped_unsupported,
                    skipped_stopped=skipped_stopped,
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
                    done, _ = wait(in_flight, timeout=1.0, return_when=FIRST_COMPLETED)
                    if not done:
                        progress(force=False)
                        continue

                    for fut in done:
                        in_flight.remove(fut)
                        file_meta = fut_meta.pop(fut, None)
                        fid = file_meta.id if file_meta else None
                        name = file_meta.name if file_meta else None

                        try:
                            status = fut.result()
                            if status == "ok":
                                ok += 1
                            elif status == "failed":
                                fail += 1
                            elif status == "skipped_unchanged":
                                skipped_unchanged += 1
                            elif status == "skipped_unsupported":
                                skipped_unsupported += 1
                            elif status == "skipped_stopped":
                                skipped_stopped += 1
                            else:
                                skipped_empty += 1
                        except ShutdownRequested:
                            stop_event.set()
                            skipped_stopped += 1
                        except Exception:
                            fail += 1
                            log.exception(
                                "ingest_failed",
                                component="ingest",
                                flow="ingest_file",
                                meta=self._file_log_meta(
                                    fid,
                                    name,
                                    mime_type=(file_meta.mime_type if file_meta else None),
                                    modified_time=(file_meta.modified_time if file_meta else None),
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
                meta=self._ingest_stats_meta(
                    total=total,
                    completed=completed,
                    ok=ok,
                    fail=fail,
                    skipped_unchanged=skipped_unchanged,
                    skipped_empty=skipped_empty,
                    skipped_unsupported=skipped_unsupported,
                    skipped_stopped=skipped_stopped,
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
            meta=self._ingest_stats_meta(
                total=total,
                completed=completed,
                ok=ok,
                fail=fail,
                skipped_unchanged=skipped_unchanged,
                skipped_empty=skipped_empty,
                skipped_unsupported=skipped_unsupported,
                skipped_stopped=skipped_stopped,
                workers=workers,
                elapsed_ms=elapsed_ms,
                stopped=stop_event.is_set(),
                mode=settings.INGEST_MODE,
            ),
        )

    def run_loop(self, limiter: Limiter, stop_event: threading.Event) -> None:
        while not stop_event.is_set():
            self.run_once(limiter, stop_event)
            stop_event.wait(timeout=settings.INGEST_POLL_SECONDS)
