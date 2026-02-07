from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Protocol

from openai import OpenAIError

from ...settings import settings

# Kinds of answers returned by QAService.
QAAnswerKind = Literal["empty", "fragments", "llm"]


@dataclass(slots=True)
class QAAnswer:
    """Answer payload returned by QAService.ask."""

    kind: QAAnswerKind
    text: str
    hits: int
    context_chars: int


class SearchError(RuntimeError):
    pass


class LLMError(RuntimeError):
    def __init__(
        self,
        *,
        preview: str,
        status: int | None = None,
        error_type: str | None = None,
        hits: int = 0,
        context_chars: int = 0,
    ) -> None:
        super().__init__("llm_call_failed")
        self.preview = preview
        self.status = status
        self.error_type = error_type
        self.hits = hits
        self.context_chars = context_chars


class QAStore(Protocol):
    """Store contract required by QAService."""

    def search(self, query: str) -> list[Any]: ...

    def build_context(self, hits: list[Any], max_chars: int) -> str: ...

    def upsert_document(
        self, *, doc_id: str, source: str, text: str, payload: dict[str, Any]
    ) -> int: ...


class QAService:
    """Query/ingest service used by the Telegram bot."""

    def __init__(self, store: QAStore, llm: Any | None) -> None:
        self.store = store
        self.llm = llm

    @staticmethod
    def _truncate_text(text: str, max_chars: int = 4000) -> str:
        if len(text) <= max_chars:
            return text
        return text[:max_chars] + "...\n\n...(информация обрезана)"

    def ingest_text(self, *, text: str, payload: dict[str, Any], doc_id: str, source: str) -> int:
        return self.store.upsert_document(doc_id=doc_id, source=source, text=text, payload=payload)

    def ask(self, question: str) -> QAAnswer:
        try:
            hits = self.store.search(question)
            context_text = self.store.build_context(hits, max_chars=settings.MAX_CONTEXT_CHARS)
        except Exception as exc:
            raise SearchError() from exc

        if not context_text.strip():
            return QAAnswer(
                kind="empty", text="Ничего не найдено.", hits=len(hits), context_chars=0
            )

        if not self.llm:
            preview = self._truncate_text(context_text)
            return QAAnswer(
                kind="fragments",
                text="LLM не настроена. Найденные фрагменты:\n\n" + preview,
                hits=len(hits),
                context_chars=len(context_text),
            )

        prompt = f"Контекст:\n\n{context_text}\n\nВопрос пользователя:\n\n{question}"

        try:
            resp = self.llm.chat.completions.create(
                model=settings.LLM_MODEL,
                messages=[
                    {"role": "system", "content": settings.LLM_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
            )
        except OpenAIError as exc:
            preview = self._truncate_text(context_text)
            status = getattr(exc, "status_code", None)
            raise LLMError(
                preview=preview, status=status, hits=len(hits), context_chars=len(context_text)
            ) from exc
        except Exception as exc:
            preview = self._truncate_text(context_text)
            raise LLMError(
                preview=preview,
                error_type=type(exc).__name__,
                hits=len(hits),
                context_chars=len(context_text),
            ) from exc

        if not resp.choices:
            preview = self._truncate_text(context_text)
            return QAAnswer(
                kind="fragments",
                text="Пустой ответ от LLM. Найденные фрагменты:\n\n" + preview,
                hits=len(hits),
                context_chars=len(context_text),
            )

        answer = self._truncate_text((resp.choices[0].message.content or "").strip())
        if not answer:
            answer = "Пустой ответ"
        return QAAnswer(kind="llm", text=answer, hits=len(hits), context_chars=len(context_text))
