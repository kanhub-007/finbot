"""ActiveSymbolState — the currently selected trading symbol + leverage.

Lives on BotManager. On startup it is None (bot fully idle). Persisted to the
DB so leverage survives restarts. Read from the exchange on /symbol (no
overwrite); set explicitly via /leverage.
"""

from dataclasses import dataclass


@dataclass
class ActiveSymbolState:
    """The symbol a manual-order or strategy session operates on.

    Leverage and margin mode are tracked here (not in .env, not in
    RuntimeBotConfig) because they are per-symbol and must be synced to the
    exchange on change.
    """

    symbol: str
    leverage: int = 1
    margin_mode: str = "isolated"
