"""BotNotificationSender — synchronous notification port used by runtime code."""

from abc import ABC, abstractmethod

from finbot.core.domain.events.bot_error_event import BotErrorEvent
from finbot.core.domain.events.risk_event_triggered import RiskEventTriggered
from finbot.core.domain.events.trade_executed import TradeExecuted


class BotNotificationSender(ABC):
    """Thread-safe notification port used by runtime/account handler code.

    Runtime code runs synchronously in a background thread. Implementations
    of this interface must be thread-safe and handle the dispatch to async
    Telegram operations internally.
    """

    @abstractmethod
    def notify_trade(self, event: TradeExecuted) -> None: ...

    @abstractmethod
    def notify_risk(self, event: RiskEventTriggered) -> None: ...

    @abstractmethod
    def notify_error(self, event: BotErrorEvent) -> None: ...
