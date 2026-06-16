"""Telegram notification sender — delegates formatting, handles broadcast loop."""

from __future__ import annotations

from finbot.core.application.use_cases.send_bot_notification import (
    format_error_text,
    format_risk_text,
    format_trade_text,
)
from finbot.core.domain.events.bot_error_event import BotErrorEvent
from finbot.core.domain.events.risk_event_triggered import RiskEventTriggered
from finbot.core.domain.events.trade_executed import TradeExecuted
from finbot.core.domain.interfaces.telegram_bot_port import TelegramBotPort
from finbot.core.domain.interfaces.telegram_chat_repository import (
    TelegramChatRepository,
)


class TelegramNotificationSender:
    """Formats domain events and sends to all registered Telegram chats.

    Delegates text formatting to shared functions in
    ``finbot.core.application.use_cases.send_bot_notification``
    so formatting logic is defined once.

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
        await self._broadcast(format_trade_text(event))

    async def notify_risk(self, event: RiskEventTriggered) -> None:
        """Send a risk event notification to all registered chats."""
        await self._broadcast(format_risk_text(event))

    async def notify_error(self, event: BotErrorEvent) -> None:
        """Send a bot error notification to all registered chats."""
        await self._broadcast(format_error_text(event))

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
