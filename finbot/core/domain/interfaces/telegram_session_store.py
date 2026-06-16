"""TelegramSessionStore — short-lived in-memory session store for callback flows."""

from abc import ABC, abstractmethod

from finbot.core.domain.entities.telegram_run_flow_session import (
    TelegramRunFlowSession,
)


class TelegramSessionStore(ABC):
    """Stores short-lived run-flow sessions for the multi-step /run flow.

    Sessions are keyed by session_id (a short string carried in callback_data)
    and expire after a configurable TTL. Expired sessions are cleaned up
    periodically or lazily.
    """

    @abstractmethod
    def create(self, chat_id: int, message_id: int) -> TelegramRunFlowSession: ...

    @abstractmethod
    def get(self, session_id: str) -> TelegramRunFlowSession | None: ...

    @abstractmethod
    def save(self, session: TelegramRunFlowSession) -> None: ...

    @abstractmethod
    def delete(self, session_id: str) -> None: ...

    @abstractmethod
    def expire_old(self, now: object) -> int: ...
