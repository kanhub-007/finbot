"""TelegramBotPort — narrow port for Telegram send/edit operations."""

from abc import ABC, abstractmethod

from finbot.core.domain.entities.send_result import SendResult


class TelegramBotPort(ABC):
    """Port for Telegram message send/edit/callback operations.

    The presentation layer (TelegramBotHandler) uses this port to send
    and edit messages. Infrastructure adapters provide the real Telegram
    implementation or in-memory fakes for testing.
    """

    @abstractmethod
    async def send_message(
        self,
        chat_id: int,
        text: str,
        parse_mode: str | None = None,
        reply_markup: dict | None = None,
    ) -> SendResult: ...

    @abstractmethod
    async def edit_message_text(
        self,
        chat_id: int,
        message_id: int,
        text: str,
        parse_mode: str | None = None,
        reply_markup: dict | None = None,
    ) -> SendResult: ...

    @abstractmethod
    async def answer_callback_query(
        self,
        callback_query_id: str,
        text: str | None = None,
    ) -> bool: ...

    @abstractmethod
    async def edit_message_reply_markup(
        self,
        chat_id: int,
        message_id: int,
        reply_markup: dict | None = None,
    ) -> bool: ...
