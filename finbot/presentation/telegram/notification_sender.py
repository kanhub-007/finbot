"""Telegram notification sender — formats events and sends via TelegramBotPort."""

from __future__ import annotations

from finbot.core.domain.events.bot_error_event import BotErrorEvent
from finbot.core.domain.events.risk_event_triggered import RiskEventTriggered
from finbot.core.domain.events.trade_executed import TradeExecuted
from finbot.core.domain.interfaces.telegram_bot_port import TelegramBotPort
from finbot.core.domain.interfaces.telegram_chat_repository import (
    TelegramChatRepository,
)


class TelegramNotificationSender:
    """Formats domain events as MarkdownV2 messages and sends to all chats.

    Runs on the Telegram asyncio loop. Uses TelegramBotPort for sending
    and TelegramChatRepository to discover registered chats.
    """

    def __init__(
        self,
        bot_port: TelegramBotPort,
        chat_repo: TelegramChatRepository,
    ) -> None:
        self._bot_port = bot_port
        self._chat_repo = chat_repo

    async def notify_trade(self, event: TradeExecuted) -> None:
        """Send a trade execution notification to all registered chats."""
        pnl_line = ""
        if event.pnl is not None:
            try:
                from decimal import Decimal

                pnl_val = Decimal(event.pnl)
                if pnl_val > Decimal("0"):
                    pnl_line = f"\\nPnL: \\+${event.pnl}"
                elif pnl_val < Decimal("0"):
                    pnl_line = f"\\nPnL: \\-${abs(pnl_val)}"
                else:
                    pnl_line = f"\\nPnL: ${event.pnl}"
            except Exception:
                pnl_line = f"\\nPnL: ${event.pnl}"

        text = (
            f"🔔 *Trade Executed*\n"
            f"{event.side.upper()} {event.size} {event.symbol} @ ${event.price}"
            f"{pnl_line}\n"
            f"Order: \\#{event.order_id} | Run: {event.run_id}"
        )
        await self._broadcast(text)

    async def notify_risk(self, event: RiskEventTriggered) -> None:
        """Send a risk event notification to all registered chats."""
        text = (
            f"⚠️ *Risk Event*\n"
            f"{event.reason}\n"
            f"Run: {event.run_id}"
        )
        if event.bot_stopped:
            text += "\n*Bot stopped\\.* No further orders will be placed\\."
        await self._broadcast(text)

    async def notify_error(self, event: BotErrorEvent) -> None:
        """Send a bot error notification to all registered chats."""
        text = (
            f"❌ *Error*\n"
            f"{event.message}\n"
            f"Run: {event.run_id}"
        )
        await self._broadcast(text)

    async def _broadcast(self, text: str) -> None:
        """Send a message to all registered chats with notifications enabled."""
        chats = await self._chat_repo.list_chats()
        for chat in chats:
            if chat.notifications_enabled:
                await self._bot_port.send_message(
                    chat_id=chat.chat_id,
                    text=text,
                    parse_mode="MarkdownV2",
                    reply_markup={
                        "inline_keyboard": [
                            [
                                {
                                    "text": "View status",
                                    "callback_data": "/status",
                                },
                            ],
                        ]
                    },
                )
