from __future__ import annotations

from types import SimpleNamespace

import pytest
from openai import OpenAIError

from gdrive_assistant_bot.core.qa.service import LLMError, QAService, SearchError
from gdrive_assistant_bot.rag import SearchHit
from tests.fakes import FakeRAGStore


class _FakeLLM:
    def __init__(
        self, *, response_text: str | None = None, raise_error: Exception | None = None
    ) -> None:
        self._response_text = response_text
        self._raise_error = raise_error
        self.calls: list[dict[str, object]] = []

    class _Completions:
        def __init__(self, parent: _FakeLLM) -> None:
            self._parent = parent

        def create(self, *, model: str, messages: list[dict[str, str]]):
            if self._parent._raise_error:
                raise self._parent._raise_error

            self._parent.calls.append({"model": model, "messages": messages})
            if self._parent._response_text is None:
                return SimpleNamespace(choices=[])

            msg = SimpleNamespace(content=self._parent._response_text)
            return SimpleNamespace(choices=[SimpleNamespace(message=msg)])

    @property
    def chat(self) -> SimpleNamespace:
        return SimpleNamespace(completions=self._Completions(self))


def test_ask_returns_empty_when_no_context() -> None:
    store = FakeRAGStore(hits=[SearchHit(score=0.9, text="", payload={})], context="  ")
    service = QAService(store, llm=None)

    answer = service.ask("question")

    assert answer.kind == "empty"
    assert answer.hits == 1
    assert answer.context_chars == 0


def test_ask_returns_fragments_when_llm_disabled() -> None:
    long_text = "x" * 4100
    store = FakeRAGStore(hits=[SearchHit(score=0.9, text="", payload={})], context=long_text)
    service = QAService(store, llm=None)

    answer = service.ask("question")

    assert answer.kind == "fragments"
    assert "LLM не настроена" in answer.text
    assert "...(информация обрезана)" in answer.text


def test_ask_returns_llm_answer() -> None:
    store = FakeRAGStore(hits=[SearchHit(score=0.9, text="", payload={})], context="ctx")
    llm = _FakeLLM(response_text="answer")
    service = QAService(store, llm=llm)

    answer = service.ask("question")

    assert answer.kind == "llm"
    assert answer.text == "answer"
    assert llm.calls


def test_ask_falls_back_when_llm_returns_empty_choices() -> None:
    store = FakeRAGStore(hits=[SearchHit(score=0.9, text="", payload={})], context="ctx")
    llm = _FakeLLM(response_text=None)
    service = QAService(store, llm=llm)

    answer = service.ask("question")

    assert answer.kind == "fragments"
    assert "Пустой ответ от LLM" in answer.text


def test_ask_raises_search_error_on_store_failure() -> None:
    store = FakeRAGStore(search_error=RuntimeError("boom"))
    service = QAService(store, llm=None)

    with pytest.raises(SearchError):
        service.ask("question")


def test_ask_wraps_openai_errors() -> None:
    store = FakeRAGStore(hits=[SearchHit(score=0.9, text="", payload={})], context="ctx")
    llm = _FakeLLM(raise_error=OpenAIError("oops"))
    service = QAService(store, llm=llm)

    with pytest.raises(LLMError) as exc_info:
        service.ask("question")

    assert exc_info.value.preview
