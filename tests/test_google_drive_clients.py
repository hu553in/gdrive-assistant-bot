from __future__ import annotations

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

    drive1, docs1, sheets1 = clients.get_thread_clients("sa.json")
    drive2, docs2, sheets2 = clients.get_thread_clients("sa.json")

    assert (drive1, docs1, sheets1) == (drive2, docs2, sheets2)
    assert calls == [("drive", "v3", False), ("docs", "v1", False), ("sheets", "v4", False)]
