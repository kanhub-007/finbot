"""EnrichmentRejectedEvent — emitted for failed candle enrichment."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class EnrichmentRejectedEvent:
    """Emitted when a candle fails enrichment validation."""

    run_id: str
    reason: str
    candle_timestamp: int
