from typing import Any

import pytest

from gdrive_assistant_bot.providers import init_providers, registry
from gdrive_assistant_bot.providers.base import FileTypeFilter
from gdrive_assistant_bot.providers.registry import get_provider, list_providers, register_provider

_ALL_PROVIDERS = ["google_drive"]


def test_all_providers_registered() -> None:
    init_providers()
    assert all(get_provider(name) is not None for name in _ALL_PROVIDERS)


def test_register_provider_requires_unique_non_empty_name(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(registry, "_registry", {})

    class Provider:
        name = "example"

        def list_files(self, file_filter: FileTypeFilter, limiter: Any, stop_event: Any):
            _ = file_filter, limiter, stop_event
            return []

        def build_extraction_context(self, limiter: Any, stop_event: Any) -> Any:
            _ = limiter, stop_event
            return object()

    register_provider(Provider())
    assert list(list_providers()) == ["example"]

    with pytest.raises(ValueError):
        register_provider(Provider())

    class EmptyProvider:
        name = " "

        def list_files(self, file_filter: FileTypeFilter, limiter: Any, stop_event: Any):
            _ = file_filter, limiter, stop_event
            return []

        def build_extraction_context(self, limiter: Any, stop_event: Any) -> Any:
            _ = limiter, stop_event
            return object()

    with pytest.raises(ValueError):
        register_provider(EmptyProvider())
