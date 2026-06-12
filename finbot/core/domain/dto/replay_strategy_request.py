"""Request DTO for replaying a strategy over historical bars."""

from dataclasses import dataclass


@dataclass(frozen=True)
class ReplayStrategyRequest:
    """Input for replaying a strategy against historical bar data."""

    strategy_path: str
    strategy_content: str
    bars_csv: str = ""
    symbol: str = "BTC"
    interval: str = "1h"
