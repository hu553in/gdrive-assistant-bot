from __future__ import annotations

import uuid
from collections.abc import Iterable

import pytest

pytest.importorskip("testcontainers.qdrant")
from testcontainers.qdrant import QdrantContainer

from gdrive_assistant_bot import rag


class _FakeEmbedding:
    def __init__(self, model_name: str) -> None:
        self.model_name = model_name

    def embed(self, texts: Iterable[str]):
        for text in texts:
            base = float(len(text) % 10)
            yield [base, base + 1.0, base + 2.0, base + 3.0]


@pytest.fixture(scope="session")
def qdrant_container():
    try:
        with QdrantContainer() as container:
            yield container
    except Exception as exc:
        pytest.skip(f"Qdrant container unavailable: {exc}")


@pytest.mark.integration
def test_rag_store_roundtrip(monkeypatch: pytest.MonkeyPatch, qdrant_container) -> None:
    monkeypatch.setattr(rag, "TextEmbedding", _FakeEmbedding)
    monkeypatch.setattr(
        rag,
        "QdrantClient",
        lambda *_args, **_kwargs: qdrant_container.get_client(check_compatibility=False),
    )

    collection = f"test_{uuid.uuid4().hex}"
    monkeypatch.setattr(rag.settings, "QDRANT_COLLECTION", collection)

    store = rag.RAGStore()

    n = store.upsert_document(
        doc_id="doc1",
        source="test",
        text="hello world",
        payload={"file_id": "doc1", "modified_time": "t1", "file_name": "name"},
        chunk_size=5,
        chunk_overlap=1,
    )

    assert n >= 1
    assert store.exists_file_mtime("doc1", "t1") is True

    hits = store.search("hello", top_k=5)
    assert hits
    assert any(hit.payload.get("file_id") == "doc1" for hit in hits)

    store.delete_by_file_id("doc1")
    assert store.exists_file_mtime("doc1", "t1") is False
