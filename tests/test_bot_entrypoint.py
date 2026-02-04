from __future__ import annotations

import pytest

from gdrive_assistant_bot import bot as bot_app


class _FakeApp:
    def __init__(self) -> None:
        self.bot_data: dict[str, object] = {}
        self.ran = False
        self.close_loop = None

    def run_polling(self, *, close_loop: bool) -> None:
        self.ran = True
        self.close_loop = close_loop


class _FakeBuilder:
    def __init__(self) -> None:
        self._token: str | None = None
        self._app = _FakeApp()

    def token(self, token: str) -> _FakeBuilder:
        self._token = token
        return self

    def build(self) -> _FakeApp:
        return self._app


class _FakeApplication:
    def __init__(self) -> None:
        self.builder_called = False
        self.builder_instance = _FakeBuilder()

    def builder(self) -> _FakeBuilder:
        self.builder_called = True
        return self.builder_instance


class _FakeStore:
    pass


def test_bot_main_wires_dependencies(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_app = _FakeApplication()
    fake_register: list[_FakeApp] = []

    def noop() -> None:
        return None

    def noop_health(*_args, **_kwargs) -> None:
        return None

    def make_store() -> _FakeStore:
        return _FakeStore()

    def make_llm() -> object:
        return object()

    def register(app: _FakeApp) -> None:
        fake_register.append(app)

    monkeypatch.setattr(bot_app, "setup_logging", noop)
    monkeypatch.setattr(bot_app, "start_health_server", noop_health)
    monkeypatch.setattr(bot_app, "RAGStore", make_store)
    monkeypatch.setattr(bot_app, "make_llm_client", make_llm)
    monkeypatch.setattr(bot_app, "Application", fake_app)
    monkeypatch.setattr(bot_app, "register_handlers", register)

    bot_app.main()

    assert fake_app.builder_called is True
    assert fake_app.builder_instance._token is not None
    assert fake_register
    assert fake_register[0].bot_data.get("qa") is not None
    assert fake_app.builder_instance._app.ran is True
    assert fake_app.builder_instance._app.close_loop is False
