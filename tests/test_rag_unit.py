from __future__ import annotations

from typing import Any

import pytest
from httpx import Headers
from qdrant_client.http.exceptions import UnexpectedResponse

from gdrive_assistant_bot.rag import RAGStore, SearchHit
from gdrive_assistant_bot.settings import settings


def test_chunk_text_handles_empty_and_short_text() -> None:
    assert RAGStore.chunk_text("   ") == []
    assert RAGStore.chunk_text("short", max_chars=10) == ["short"]


def test_chunk_text_splits_with_overlap() -> None:
    text = "abcdefghij"  # 10 chars
    chunks = RAGStore.chunk_text(text, max_chars=4, overlap=1)
    assert chunks == ["abcd", "defg", "ghij", "j"]


def test_point_uuid_is_deterministic() -> None:
    first = RAGStore._point_uuid("doc", 0)
    second = RAGStore._point_uuid("doc", 0)
    other = RAGStore._point_uuid("doc", 1)
    assert first == second
    assert first != other


def test_build_context_respects_max_chars() -> None:
    hits = [
        SearchHit(score=0.9, text="alpha", payload={"source": "s", "file_name": "a"}),
        SearchHit(score=0.8, text="beta", payload={"source": "s", "file_name": "b"}),
    ]

    context = RAGStore.build_context(hits, max_chars=40)
    assert "alpha" in context
    assert "beta" not in context


class _FakeRagClient:
    def __init__(self, get_collection_error: Exception | None = None) -> None:
        self.get_collection_error = get_collection_error
        self.get_collection_calls: list[str] = []
        self.create_collection_calls: list[dict[str, Any]] = []
        self.create_payload_index_calls: list[dict[str, Any]] = []

    def get_collection(self, collection_name: str) -> dict[str, str]:
        self.get_collection_calls.append(collection_name)
        if self.get_collection_error is not None:
            raise self.get_collection_error
        return {"status": "ok"}

    def create_collection(self, **kwargs: Any) -> None:
        self.create_collection_calls.append(kwargs)

    def create_payload_index(self, **kwargs: Any) -> None:
        self.create_payload_index_calls.append(kwargs)


def _store_with_client(client: _FakeRagClient) -> RAGStore:
    store = object.__new__(RAGStore)
    store.client = client
    return store


def test_ensure_collection_keeps_existing_collection() -> None:
    client = _FakeRagClient()
    store = _store_with_client(client)

    store._ensure_collection(vector_size=123)

    assert client.get_collection_calls == [settings.QDRANT_COLLECTION]
    assert client.create_collection_calls == []
    assert client.create_payload_index_calls == []


def test_ensure_collection_creates_on_404_not_found() -> None:
    error = UnexpectedResponse(
        status_code=404, reason_phrase="Not Found", content=b"missing", headers=Headers()
    )
    client = _FakeRagClient(get_collection_error=error)
    store = _store_with_client(client)

    store._ensure_collection(vector_size=123)

    assert client.get_collection_calls == [settings.QDRANT_COLLECTION]
    assert len(client.create_collection_calls) == 1
    assert client.create_collection_calls[0]["collection_name"] == settings.QDRANT_COLLECTION
    expected_index_count = 3
    assert len(client.create_payload_index_calls) == expected_index_count
    assert {call["field_name"] for call in client.create_payload_index_calls} == {
        "file_id",
        "modified_time",
        "source",
    }


def test_ensure_collection_reraises_non_404_errors() -> None:
    error = UnexpectedResponse(
        status_code=500, reason_phrase="Internal Server Error", content=b"boom", headers=Headers()
    )
    client = _FakeRagClient(get_collection_error=error)
    store = _store_with_client(client)

    with pytest.raises(UnexpectedResponse):
        store._ensure_collection(vector_size=123)

    assert client.get_collection_calls == [settings.QDRANT_COLLECTION]
    assert client.create_collection_calls == []
    assert client.create_payload_index_calls == []
