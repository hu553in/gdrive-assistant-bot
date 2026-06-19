from __future__ import annotations

import pytest

from gdrive_assistant_bot.providers.google_drive import clients


def test_get_thread_clients_builds_and_caches(monkeypatch):
    calls: list[tuple[str, str, bool]] = []

    class _Creds:
        pass

    def fake_creds(path: str, scopes: list[str]):
        assert path == "sa.json"
        assert scopes == clients.SCOPES
        return _Creds()

    def fake_build(api: str, version: str, *, credentials, cache_discovery: bool):
        assert isinstance(credentials, _Creds)
        calls.append((api, version, cache_discovery))
        return f"{api}-{version}"

    monkeypatch.setattr(
        clients.service_account.Credentials, "from_service_account_file", fake_creds
    )
    monkeypatch.setattr(clients, "build", fake_build)
    monkeypatch.setattr(clients, "_thread_local", type("TL", (), {})())

    drive1, docs1, sheets1, slides1 = clients.get_thread_clients("sa.json")
    drive2, docs2, sheets2, slides2 = clients.get_thread_clients("sa.json")

    assert (drive1, docs1, sheets1, slides1) == (drive2, docs2, sheets2, slides2)
    assert calls == [
        ("drive", "v3", False),
        ("docs", "v1", False),
        ("sheets", "v4", False),
        ("slides", "v1", False),
    ]


def test_get_thread_clients_recovers_after_partial_build_failure(monkeypatch):
    calls: list[tuple[str, str, bool]] = []
    fail_once = {"value": True}

    class _Creds:
        pass

    def fake_creds(path: str, scopes: list[str]):
        assert path == "sa.json"
        assert scopes == clients.SCOPES
        return _Creds()

    def fake_build(api: str, version: str, *, credentials, cache_discovery: bool):
        assert isinstance(credentials, _Creds)
        calls.append((api, version, cache_discovery))
        if api == "slides" and fail_once["value"]:
            fail_once["value"] = False
            raise RuntimeError("temporary failure")
        return f"{api}-{version}"

    monkeypatch.setattr(
        clients.service_account.Credentials, "from_service_account_file", fake_creds
    )
    monkeypatch.setattr(clients, "build", fake_build)
    monkeypatch.setattr(clients, "_thread_local", type("TL", (), {})())

    with pytest.raises(RuntimeError, match="temporary failure"):
        clients.get_thread_clients("sa.json")
    assert clients._thread_local.__dict__ == {}

    drive, docs, sheets, slides = clients.get_thread_clients("sa.json")

    assert (drive, docs, sheets, slides) == ("drive-v3", "docs-v1", "sheets-v4", "slides-v1")
    assert calls == [
        ("drive", "v3", False),
        ("docs", "v1", False),
        ("sheets", "v4", False),
        ("slides", "v1", False),
        ("drive", "v3", False),
        ("docs", "v1", False),
        ("sheets", "v4", False),
        ("slides", "v1", False),
    ]


def test_get_thread_client_failure_keeps_other_cached_clients(monkeypatch):
    calls: list[tuple[str, str, bool]] = []
    fail_once = {"value": True}

    class _Creds:
        pass

    def fake_creds(path: str, scopes: list[str]):
        assert path == "sa.json"
        assert scopes == clients.SCOPES
        return _Creds()

    def fake_build(api: str, version: str, *, credentials, cache_discovery: bool):
        assert isinstance(credentials, _Creds)
        calls.append((api, version, cache_discovery))
        if api == "slides" and fail_once["value"]:
            fail_once["value"] = False
            raise RuntimeError("slides unavailable")
        return f"{api}-{version}"

    monkeypatch.setattr(
        clients.service_account.Credentials, "from_service_account_file", fake_creds
    )
    monkeypatch.setattr(clients, "build", fake_build)
    monkeypatch.setattr(clients, "_thread_local", type("TL", (), {})())

    drive1 = clients.get_thread_client("sa.json", "drive")
    with pytest.raises(RuntimeError, match="slides unavailable"):
        clients.get_thread_client("sa.json", "slides")

    drive2 = clients.get_thread_client("sa.json", "drive")
    slides = clients.get_thread_client("sa.json", "slides")

    assert drive1 == drive2 == "drive-v3"
    assert slides == "slides-v1"
    assert calls == [("drive", "v3", False), ("slides", "v1", False), ("slides", "v1", False)]


def test_get_thread_clients_builds_only_requested_apis(monkeypatch):
    calls: list[tuple[str, str, bool]] = []

    class _Creds:
        pass

    def fake_creds(path: str, scopes: list[str]):
        assert path == "sa.json"
        assert scopes == clients.SCOPES
        return _Creds()

    def fake_build(api: str, version: str, *, credentials, cache_discovery: bool):
        assert isinstance(credentials, _Creds)
        calls.append((api, version, cache_discovery))
        return f"{api}-{version}"

    monkeypatch.setattr(
        clients.service_account.Credentials, "from_service_account_file", fake_creds
    )
    monkeypatch.setattr(clients, "build", fake_build)
    monkeypatch.setattr(clients, "_thread_local", type("TL", (), {})())

    drive, sheets = clients.get_thread_clients("sa.json", ("drive", "sheets"))

    assert (drive, sheets) == ("drive-v3", "sheets-v4")
    assert calls == [("drive", "v3", False), ("sheets", "v4", False)]
