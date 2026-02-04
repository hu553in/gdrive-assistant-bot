from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


@dataclass(slots=True)
class FakeUser:
    id: int
    username: str | None = None


@dataclass(slots=True)
class FakeChat:
    id: int
    type: str


@dataclass(slots=True)
class FakeMessage:
    chat: FakeChat
    message_id: int
    text: str | None = None
    from_user: FakeUser | None = None
    date: datetime = field(default_factory=lambda: datetime(2024, 1, 1, tzinfo=UTC))
    replies: list[str] = field(default_factory=list)

    @property
    def chat_id(self) -> int:
        return self.chat.id

    async def reply_text(self, text: str) -> None:
        self.replies.append(text)


@dataclass(slots=True)
class FakeUpdate:
    message: FakeMessage | None = None
    effective_message: FakeMessage | None = None

    def __post_init__(self) -> None:
        if self.effective_message is None:
            self.effective_message = self.message


@dataclass(slots=True)
class FakeApplication:
    bot_data: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class FakeContext:
    application: FakeApplication


@dataclass(slots=True)
class FakeRAGStore:
    hits: list[Any] = field(default_factory=list)
    context: str = ""
    search_error: Exception | None = None
    build_context_error: Exception | None = None
    upsert_return: int = 1
    existing_mtimes: set[tuple[str, str]] = field(default_factory=set)
    upserts: list[dict[str, Any]] = field(default_factory=list)
    deletes: list[str] = field(default_factory=list)

    def search(self, _query: str) -> list[Any]:
        if self.search_error:
            raise self.search_error
        return list(self.hits)

    def build_context(self, hits: list[Any], max_chars: int) -> str:
        _ = hits, max_chars
        if self.build_context_error:
            raise self.build_context_error
        return self.context

    def upsert_document(
        self, *, doc_id: str, source: str, text: str, payload: dict[str, Any]
    ) -> int:
        self.upserts.append({"doc_id": doc_id, "source": source, "text": text, "payload": payload})
        return self.upsert_return

    def delete_by_file_id(self, file_id: str) -> None:
        self.deletes.append(file_id)

    def exists_file_mtime(self, file_id: str, modified_time: str) -> bool:
        return (file_id, modified_time) in self.existing_mtimes
