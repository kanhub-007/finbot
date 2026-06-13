"""Application DTO for the outcome of processing one closed candle.

Crosses the application → presentation boundary.
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class CandleProcessingResult:
    """Testable outcome of one closed candle being processed.

    ``enrichment_valid`` indicates whether the enriched bar passed
    the enrichment validation gate.  When False, no strategy signal
    was produced and no order intent was planned.
    """

    candle_timestamp: int
    """Timestamp of the processed closed candle."""

    enrichment_valid: bool = True
    """True when the enriched bar passed all quality checks."""

    enrichment_errors: list[str] = field(default_factory=list)
    """Rejection reasons from enrichment validation (empty when valid)."""

    signal_action: str = ""
    """Strategy signal action produced (HOLD / LONG_ENTRY / …), empty if skipped."""

    risk_decision: str = ""
    """Risk gate decision if reached (accepted / rejected)."""

    intent_id: str = ""
    """Order intent id if one was persisted."""

    submitted: bool = False
    """Whether an order was submitted to the exchange."""

    message: str = ""
    """Human-readable summary of the processing step."""
