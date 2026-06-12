"""Trading mode value object."""

from enum import StrEnum


class TradingMode(StrEnum):
    """Allowed execution modes for the bot."""

    DRY_RUN = "dry_run"
    TESTNET = "testnet"
    LIVE = "live"
