"""Domain events for the Telegram bot control feature."""

from finbot.core.domain.events.trade_executed import TradeExecuted  # noqa: F401
from finbot.core.domain.events.risk_event_triggered import (  # noqa: F401
    RiskEventTriggered,
)
from finbot.core.domain.events.bot_error_event import BotErrorEvent  # noqa: F401
