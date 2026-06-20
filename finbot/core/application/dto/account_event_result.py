"""Account event result — typed return from AccountEventHandler.handle()."""

from __future__ import annotations

from dataclasses import dataclass

from finbot.core.domain.dto.fill_outcome import FillOutcome


@dataclass(frozen=True)
class AccountEventResult:
    """Result of processing one account websocket event.

    Attributes:
        status: ``"processed"``, ``"skipped"``, ``"duplicate"``,
            ``"transition_rejected"``, or ``"unknown_status"``.
        reason: Human-readable reason for non-processed events.
        outcome: Fill outcome (PnL, position_id) when a fill was applied.
    """

    status: str
    reason: str = ""
    outcome: FillOutcome | None = None
