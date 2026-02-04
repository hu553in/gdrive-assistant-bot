from __future__ import annotations

from gdrive_assistant_bot.rag import RAGStore, SearchHit


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
