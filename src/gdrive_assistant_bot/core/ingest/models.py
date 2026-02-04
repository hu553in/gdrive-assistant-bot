from __future__ import annotations

from typing import Literal

# Status codes returned by IngestService.
IngestStatus = Literal["ok", "skipped_unchanged", "skipped_empty"]
