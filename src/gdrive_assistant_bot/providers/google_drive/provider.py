from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any

import structlog

from ...extractors.base import ExtractionContext
from ...settings import settings
from ..base import FileTypeFilter, Limiter, StopEvent, StorageFileMeta, StorageProvider
from .api import download_binary, download_export, execute_with_backoff
from .clients import get_thread_client

log = structlog.get_logger("gdrive-assistant-bot.providers.google_drive")

FOLDER_MIME = "application/vnd.google-apps.folder"
SHORTCUT_MIME = "application/vnd.google-apps.shortcut"


class _LazyGoogleClient:
    """Create Google API clients on first use to avoid eager optional API initialization."""

    def __init__(self, factory: Callable[[], Any]) -> None:
        self._factory = factory
        self._client: Any | None = None

    def _resolve(self) -> Any:
        if self._client is None:
            self._client = self._factory()
        return self._client

    def __getattr__(self, name: str) -> Any:
        return getattr(self._resolve(), name)


class GoogleDriveProvider(StorageProvider):
    """Google Drive storage provider implementation."""

    name = "google_drive"

    def list_files(
        self, file_filter: FileTypeFilter, limiter: Limiter, stop_event: StopEvent
    ) -> Iterable[StorageFileMeta]:
        try:
            drive = get_thread_client(settings.STORAGE_GOOGLE_DRIVE_SERVICE_ACCOUNT_JSON, "drive")
        except Exception:
            log.exception(
                "google_client_init_failed",
                component="ingest",
                flow="google_api",
                meta={"service_account_path": settings.STORAGE_GOOGLE_DRIVE_SERVICE_ACCOUNT_JSON},
            )
            raise

        if settings.STORAGE_GOOGLE_DRIVE_ALL_ACCESSIBLE:
            files = self._list_all_accessible_files(drive, limiter, file_filter)
            log.warning(
                "all_accessible_enabled",
                component="ingest",
                flow="ingest_scope",
                meta={"files": len(files), "all_accessible": True},
            )
        else:
            files = list(
                self._walk_recursive(
                    drive,
                    settings.STORAGE_GOOGLE_DRIVE_FOLDER_IDS,
                    limiter,
                    stop_event,
                    file_filter,
                )
            )
            log.info(
                "folder_recursive_scope",
                component="ingest",
                flow="ingest_scope",
                meta={
                    "roots": settings.STORAGE_GOOGLE_DRIVE_FOLDER_IDS,
                    "files": len(files),
                    "all_accessible": False,
                },
            )

        return [self._to_storage_meta(f) for f in files]

    def build_extraction_context(
        self, limiter: Limiter, stop_event: StopEvent
    ) -> ExtractionContext:
        service_account_json = settings.STORAGE_GOOGLE_DRIVE_SERVICE_ACCOUNT_JSON
        drive = get_thread_client(service_account_json, "drive")

        class Context:
            pass

        ctx = Context()
        ctx.limiter = limiter
        ctx.stop_event = stop_event
        ctx.settings = settings
        ctx.drive = drive
        ctx.docs = (
            _LazyGoogleClient(lambda: get_thread_client(service_account_json, "docs"))
            if settings.FILE_TYPE_GDOCS_ENABLED
            else None
        )
        ctx.sheets = (
            _LazyGoogleClient(lambda: get_thread_client(service_account_json, "sheets"))
            if settings.FILE_TYPE_GSHEETS_ENABLED
            else None
        )
        ctx.slides = (
            _LazyGoogleClient(lambda: get_thread_client(service_account_json, "slides"))
            if settings.FILE_TYPE_GSLIDES_ENABLED
            else None
        )
        ctx.execute_with_backoff = lambda call: execute_with_backoff(call, limiter)
        ctx.download_binary = lambda file_id: download_binary(drive, file_id, limiter, stop_event)
        ctx.download_export = lambda file_id, mime: download_export(
            drive, file_id, mime, limiter, stop_event
        )
        return ctx

    @staticmethod
    def _to_storage_meta(file_meta: dict[str, Any]) -> StorageFileMeta:
        size = file_meta.get("size")
        if isinstance(size, str) and size.isdigit():
            size = int(size)
        return StorageFileMeta(
            id=str(file_meta.get("id", "")),
            name=file_meta.get("name"),
            mime_type=file_meta.get("mimeType"),
            modified_time=file_meta.get("modifiedTime"),
            size=size if isinstance(size, int) else None,
            extension=(file_meta.get("fileExtension") or None),
            raw=dict(file_meta),
        )

    @staticmethod
    def _is_shortcut(file_meta: dict[str, Any]) -> bool:
        return file_meta.get("mimeType") == SHORTCUT_MIME

    @staticmethod
    def _matches_filter(file_meta: dict[str, Any], file_filter: FileTypeFilter) -> bool:
        mime = file_meta.get("mimeType") or ""
        ext = (file_meta.get("fileExtension") or "").lower()
        if not ext:
            name = file_meta.get("name") or ""
            if "." in name:
                ext = name.rsplit(".", 1)[-1].lower()
        if mime in file_filter.mime_types:
            return True
        for prefix in file_filter.mime_prefixes:
            if prefix and mime.startswith(prefix):
                return True
        return ext in {x.lower() for x in file_filter.extensions} if ext else False

    def _list_children(self, drive: Any, parent_id: str, limiter: Limiter) -> list[dict[str, Any]]:
        q = f"'{parent_id}' in parents and trashed=false"
        files: list[dict[str, Any]] = []
        page_token = None

        while True:
            pt = page_token
            resp = execute_with_backoff(
                lambda pt=pt: (
                    drive.files()
                    .list(
                        q=q,
                        fields=(
                            "nextPageToken, files(id, name, mimeType, modifiedTime, "
                            "size, fileExtension, shortcutDetails)"
                        ),
                        pageToken=pt,
                        pageSize=1000,
                    )
                    .execute()
                ),
                limiter,
            )
            files.extend(resp.get("files") or [])
            page_token = resp.get("nextPageToken")
            if not page_token:
                break

        return files

    def _walk_recursive(
        self,
        drive: Any,
        root_ids: Iterable[str],
        limiter: Limiter,
        stop_event: StopEvent,
        file_filter: FileTypeFilter,
    ) -> Iterable[dict[str, Any]]:
        stack = list(root_ids)
        seen: set[str] = set()

        while stack and not stop_event.is_set():
            folder_id = stack.pop()
            if folder_id in seen:
                continue
            seen.add(folder_id)

            for f in self._list_children(drive, folder_id, limiter):
                if stop_event.is_set():
                    break
                mime = f.get("mimeType")
                if mime == FOLDER_MIME:
                    stack.append(f["id"])
                elif self._is_shortcut(f):
                    log.debug(
                        "shortcut_skipped",
                        component="ingest",
                        flow="walk_recursive",
                        meta={"file_id": f.get("id"), "file_name": f.get("name")},
                    )
                elif self._matches_filter(f, file_filter):
                    yield f

    def _build_drive_query_terms(self, file_filter: FileTypeFilter) -> list[str]:
        terms: list[str] = []
        for mime in file_filter.mime_types:
            terms.append(f"mimeType='{mime}'")
        for prefix in sorted(file_filter.mime_prefixes):
            terms.append(f"mimeType contains '{prefix}'")
        for ext in sorted({ext.lower() for ext in file_filter.extensions if ext}):
            terms.append(f"fileExtension='{ext}'")
            terms.append(f"name contains '.{ext}'")
        return terms

    def _list_all_accessible_files(
        self, drive: Any, limiter: Limiter, file_filter: FileTypeFilter
    ) -> list[dict[str, Any]]:
        terms = self._build_drive_query_terms(file_filter)
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
                lambda pt=pt: (
                    drive.files()
                    .list(
                        q=q,
                        fields=(
                            "nextPageToken, files(id, name, mimeType, modifiedTime, "
                            "size, fileExtension, shortcutDetails)"
                        ),
                        pageToken=pt,
                        pageSize=1000,
                    )
                    .execute()
                ),
                limiter,
            )
            files.extend(resp.get("files") or [])
            page_token = resp.get("nextPageToken")
            if not page_token:
                break

        return [
            f for f in files if not self._is_shortcut(f) and self._matches_filter(f, file_filter)
        ]
