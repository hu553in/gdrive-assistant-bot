from .google_drive.provider import GoogleDriveProvider
from .registry import register_provider

_state: dict[str, bool] = {"initialized": False}


def init_providers() -> None:
    """Register built-in storage providers once."""
    if _state["initialized"]:
        return

    register_provider(GoogleDriveProvider())
    _state["initialized"] = True


__all__ = []
