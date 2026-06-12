"""Bot status DTO — returned by the status CLI command."""

from dataclasses import dataclass


@dataclass(frozen=True)
class BotStatusResult:
    """Snapshot of the bot's current state for status reporting."""

    active_bot_run_id: str = ""
    strategy_name: str = ""
    strategy_hash: str = ""
    symbol: str = ""
    interval: str = ""
    mode: str = ""
    last_signal_key: str = ""
    last_signal_action: str = ""
    last_signal_timestamp: str = ""
    last_order_intent_id: str = ""
    last_order_status: str = ""
    total_signals: int = 0
    total_orders: int = 0
    total_fills: int = 0
