from __future__ import annotations

from collections.abc import Iterable

from .base import StorageProvider

_registry: dict[str, StorageProvider] = {}


def register_provider(provider: StorageProvider) -> None:
    name = provider.name.strip()
    if not name:
        raise ValueError("Provider name must be non-empty")
    if name in _registry:
        raise ValueError(f"Provider already registered: {name}")
    _registry[name] = provider


def get_provider(name: str) -> StorageProvider | None:
    return _registry.get(name)


def list_providers() -> Iterable[str]:
    return _registry.keys()
