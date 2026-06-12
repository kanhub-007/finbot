"""Status use case — reports the bot's current state."""

from finbot.core.application.dto.bot_status_result import BotStatusResult
from finbot.core.domain.interfaces.bot_state_repository import (
    BotStateRepository,
)


class StatusUseCase:
    """Query the current bot state from persistent storage."""

    def __init__(self, repo: BotStateRepository) -> None:
        self._repo = repo

    def execute(self) -> BotStatusResult:
        run = self._repo.get_latest_bot_run()
        signal = self._repo.get_last_signal()
        last_order = self._repo.get_last_order_response()

        return BotStatusResult(
            active_bot_run_id=run.run_id if run else "",
            strategy_name=run.strategy_name if run else "",
            strategy_hash=run.strategy_hash if run else "",
            symbol=run.symbol if run else "",
            interval=run.interval if run else "",
            mode=run.mode if run else "",
            last_signal_key=signal.signal_key if signal else "",
            last_signal_action=signal.signal_action if signal else "",
            last_signal_timestamp=signal.bar_timestamp if signal else "",
            last_order_intent_id=(last_order.intent_id if last_order else ""),
            last_order_status=last_order.status if last_order else "",
            total_signals=self._repo.count_signals(),
            total_orders=self._repo.count_orders(),
            total_fills=self._repo.count_fills(),
        )
