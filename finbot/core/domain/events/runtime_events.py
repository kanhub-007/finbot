"""Runtime event types emitted during the trading pipeline."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RiskTriggeredEvent:
    """Emitted when a risk gate blocks an order or stops the bot."""

    run_id: str
    event_type: str
    reason: str
    bot_stopped: bool


@dataclass(frozen=True)
class EnrichmentRejectedEvent:
    """Emitted when a candle fails enrichment validation."""

    run_id: str
    reason: str
    candle_timestamp: int


@dataclass(frozen=True)
class TradeExecutedEvent:
    """Emitted when a fill is applied to the trade ledger."""

    run_id: str
    symbol: str
    side: str
    size: str
    price: str
    pnl: str | None
    order_id: str
