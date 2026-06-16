"""BotManagerPort — domain protocol for bot lifecycle operations needed by Telegram."""

from __future__ import annotations

from typing import Any, Protocol


class BotManagerPort(Protocol):
    """Protocol defining the bot lifecycle methods used by HandleTelegramCommand.

    Both the real BotManager and test fakes implement this interface.
    Using a Protocol rather than ABC+inheritance keeps BotManager unaware
    of the Telegram use case's specific needs.
    """

    def is_running(self) -> bool: ...

    def get_status(self) -> dict[str, object]: ...

    def start(
        self,
        strategy_path: str,
        symbol: str,
        interval: str,
        mode: str,
        warmup_bars: int = 100,
        live_trading_ack: bool = False,
    ) -> dict[str, str]: ...

    def stop(self) -> dict[str, str]: ...

    def list_bot_runs(
        self, limit: int = 20, mode_filter: str | None = None
    ) -> list[Any]: ...

    def cancel_all_orders(self, symbol: str) -> dict[str, object]: ...

    def close_position(self, symbol: str) -> dict[str, object]: ...
