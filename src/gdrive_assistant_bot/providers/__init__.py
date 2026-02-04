from .google_drive.provider import GoogleDriveProvider
from .registry import register_provider


def init_providers() -> None:
    """Register built-in storage providers once."""

    if getattr(init_providers, "_initialized", False):
        return

    register_provider(GoogleDriveProvider())
    init_providers._initialized = True


__all__ = []
