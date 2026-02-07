from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import Any

from fastembed import TextEmbedding
from qdrant_client import QdrantClient
from qdrant_client.http import models as qm

from .settings import settings


@dataclass(slots=True)
class SearchHit:
    score: float
    text: str
    payload: dict[str, Any]


class RAGStore:
    def __init__(self) -> None:
        self.client = QdrantClient(url=str(settings.QDRANT_URL))
        self.embedder = TextEmbedding(model_name=settings.EMBED_MODEL)

        dim = len(next(iter(self.embedder.embed(["ping"]))))
        self._ensure_collection(dim)

    def _ensure_collection(self, vector_size: int) -> None:
        col = settings.QDRANT_COLLECTION

        try:
            self.client.get_collection(col)
            return
        except Exception:
            pass  # Collection doesn't exist or error occurred; proceed to create it

        self.client.create_collection(
            collection_name=col,
            vectors_config=qm.VectorParams(size=vector_size, distance=qm.Distance.COSINE),
        )

        # indexes for fast deletes / skip checks
        for field in ("file_id", "modified_time", "source"):
            self.client.create_payload_index(
                collection_name=col, field_name=field, field_schema=qm.PayloadSchemaType.KEYWORD
            )

    @staticmethod
    def chunk_text(text: str, max_chars: int = 900, overlap: int = 120) -> list[str]:
        text = " ".join(text.split())
        if not text:
            return []
        if len(text) <= max_chars:
            return [text]

        chunks: list[str] = []
        step = max(1, max_chars - overlap)
        i = 0
        while i < len(text):
            chunks.append(text[i : i + max_chars])
            i += step
        return chunks

    @staticmethod
    def _point_uuid(doc_id: str, chunk_idx: int) -> str:
        # Deterministic UUID per (doc_id, chunk_idx) so re-indexing is stable
        return str(uuid.uuid5(uuid.NAMESPACE_URL, f"gdrive-assistant-bot:{doc_id}:{chunk_idx}"))

    def upsert_document(  # noqa: PLR0913
        self,
        *,
        doc_id: str,
        source: str,
        text: str,
        payload: dict[str, Any],
        chunk_size: int = 900,
        chunk_overlap: int = 120,
    ) -> int:
        chunks = self.chunk_text(text, max_chars=chunk_size, overlap=chunk_overlap)
        if not chunks:
            return 0

        vectors = list(self.embedder.embed(chunks))
        ts = int(time.time())

        points: list[qm.PointStruct] = []
        for idx, (chunk, vec) in enumerate(zip(chunks, vectors, strict=False)):
            pid = self._point_uuid(doc_id, idx)
            points.append(
                qm.PointStruct(
                    id=pid,  # Qdrant requires uint64 or UUID
                    vector=vec,
                    payload={"text": chunk, "source": source, "ts": ts, "chunk": idx, **payload},
                )
            )

        self.client.upsert(collection_name=settings.QDRANT_COLLECTION, points=points)
        return len(points)

    def search(self, query: str, top_k: int | None = None) -> list[SearchHit]:
        top_k = top_k or settings.TOP_K
        qvec = next(iter(self.embedder.embed([query])))

        hits = self.client.query_points(
            collection_name=settings.QDRANT_COLLECTION, query=qvec, limit=top_k, with_payload=True
        ).points

        out: list[SearchHit] = []
        for h in hits:
            payload = dict(h.payload or {})
            out.append(
                SearchHit(score=float(h.score), text=str(payload.get("text", "")), payload=payload)
            )
        return out

    @staticmethod
    def build_context(hits: list[SearchHit], max_chars: int) -> str:
        parts: list[str] = []
        total = 0

        for i, h in enumerate(hits, start=1):
            src = h.payload.get("source", "unknown")
            file_name = h.payload.get("file_name", "")
            piece = f"[{i}] score={h.score:.3f} source={src} file={file_name}\n{h.text}\n"
            if total + len(piece) > max_chars:
                break
            parts.append(piece)
            total += len(piece)

        return "\n".join(parts)

    def delete_by_file_id(self, file_id: str) -> None:
        self.client.delete(
            collection_name=settings.QDRANT_COLLECTION,
            points_selector=qm.FilterSelector(
                filter=qm.Filter(
                    must=[qm.FieldCondition(key="file_id", match=qm.MatchValue(value=file_id))]
                )
            ),
            wait=True,
        )

    def exists_file_mtime(self, file_id: str, modified_time: str) -> bool:
        flt = qm.Filter(
            must=[
                qm.FieldCondition(key="file_id", match=qm.MatchValue(value=file_id)),
                qm.FieldCondition(key="modified_time", match=qm.MatchValue(value=modified_time)),
            ]
        )
        points, _ = self.client.scroll(
            collection_name=settings.QDRANT_COLLECTION,
            scroll_filter=flt,
            limit=1,
            with_payload=False,
            with_vectors=False,
        )
        return bool(points)
