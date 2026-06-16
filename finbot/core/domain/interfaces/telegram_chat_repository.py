"""TelegramChatRepository — persistence port for registered Telegram chats."""

from abc import ABC, abstractmethod

from finbot.core.domain.entities.telegram_chat import TelegramChat


class TelegramChatRepository(ABC):
    """Repository for authorized Telegram chat registrations.

    Chats are registered via /start and store chat_id, user_id,
    registration timestamp, and notification preferences.
    """

    @abstractmethod
    async def add_chat(self, chat: TelegramChat) -> None: ...

    @abstractmethod
    async def get_chat(self, chat_id: int) -> TelegramChat | None: ...

    @abstractmethod
    async def list_chats(self) -> list[TelegramChat]: ...

    @abstractmethod
    async def remove_chat(self, chat_id: int) -> None: ...

    @abstractmethod
    async def set_notifications(self, chat_id: int, enabled: bool) -> None: ...
