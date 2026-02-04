from gdrive_assistant_bot.providers import init_providers
from gdrive_assistant_bot.providers.registry import get_provider

_ALL_PROVIDERS = ["google_drive"]


def test_all_providers_registered() -> None:
    init_providers()
    assert all(get_provider(name) is not None for name in _ALL_PROVIDERS)
