"""ThreadSafeTelegramNotificationDispatcher — bridges sync runtime to async Telegram."""

from __future__ import annotations

import asyncio

from finbot.core.domain.events.bot_error_event import BotErrorEvent
from finbot.core.domain.events.risk_event_triggered import RiskEventTriggered
from finbot.core.domain.events.trade_executed import TradeExecuted
from finbot.core.domain.interfaces.bot_notification_sender import (
    BotNotificationSender,
)


class ThreadSafeTelegramNotificationDispatcher(BotNotificationSender):
    """Implements the synchronous BotNotificationSender interface.

    Schedules async notification sends onto a specific asyncio event
    loop using ``asyncio.run_coroutine_threadsafe()`` so the trading
    runtime thread does not need to know about asyncio.
    """

    def __init__(self, loop: asyncio.AbstractEventLoop, sender: object) -> None:
        """Initialize the dispatcher.

        Args:
            loop: The Telegram asyncio event loop.
            sender: An object with async ``notify_trade``, ``notify_risk``,
                and ``notify_error`` methods (e.g., TelegramNotificationSender).
        """
        self._loop = loop
        self._sender = sender

    def notify_trade(self, event: TradeExecuted) -> None:
        """Schedule a trade notification on the Telegram event loop."""
        try:
            asyncio.run_coroutine_threadsafe(
                self._sender.notify_trade(event), self._loop  # type: ignore[attr-defined]
            )
        except Exception:
            pass  # Fire-and-forget; notification may be lost

    def notify_risk(self, event: RiskEventTriggered) -> None:
        """Schedule a risk notification on the Telegram event loop."""
        try:
            asyncio.run_coroutine_threadsafe(
                self._sender.notify_risk(event), self._loop  # type: ignore[attr-defined]
            )
        except Exception:
            pass

    def notify_error(self, event: BotErrorEvent) -> None:
        """Schedule an error notification on the Telegram event loop."""
        try:
            asyncio.run_coroutine_threadsafe(
                self._sender.notify_error(event), self._loop  # type: ignore[attr-defined]
            )
        except Exception:
            pass
