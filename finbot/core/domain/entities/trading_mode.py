"""Trading mode value object."""

from __future__ import annotations

from enum import StrEnum


class TradingMode(StrEnum):
    """Allowed execution modes for the bot."""

    DRY_RUN = "dry_run"
    TESTNET = "testnet"
    LIVE = "live"
