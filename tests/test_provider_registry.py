import pytest

from gdrive_assistant_bot.providers import init_providers, registry
from gdrive_assistant_bot.providers.registry import get_provider, list_providers, register_provider

_ALL_PROVIDERS = ["google_drive"]


def test_all_providers_registered() -> None:
    init_providers()
    assert all(get_provider(name) is not None for name in _ALL_PROVIDERS)


def test_register_provider_requires_unique_non_empty_name(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(registry, "_registry", {})

    class Provider:
        name = "example"

    register_provider(Provider())
    assert list(list_providers()) == ["example"]

    with pytest.raises(ValueError):
        register_provider(Provider())

    class EmptyProvider:
        name = " "

    with pytest.raises(ValueError):
        register_provider(EmptyProvider())
