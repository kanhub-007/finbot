"""In-memory Telegram session store — production implementation."""

from __future__ import annotations

import uuid
from datetime import datetime

from finbot.core.domain.entities.telegram_run_flow_session import (
    TelegramRunFlowSession,
)
from finbot.core.domain.interfaces.telegram_session_store import (
    TelegramSessionStore,
)


class InMemoryTelegramSessionStore(TelegramSessionStore):
    """Stores /run flow sessions in memory. Short-lived, no persistence needed."""

    def __init__(self) -> None:
        self._sessions: dict[str, TelegramRunFlowSession] = {}

    def create(self, chat_id: int, message_id: int) -> TelegramRunFlowSession:
        session_id = uuid.uuid4().hex[:6]
        session = TelegramRunFlowSession(
            session_id=session_id,
            chat_id=chat_id,
            message_id=message_id,
        )
        self._sessions[session_id] = session
        return session

    def get(self, session_id: str) -> TelegramRunFlowSession | None:
        return self._sessions.get(session_id)

    def save(self, session: TelegramRunFlowSession) -> None:
        self._sessions[session.session_id] = session

    def delete(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)

    def expire_old(self, now: object) -> int:
        assert isinstance(now, datetime)
        to_delete = [sid for sid, s in self._sessions.items() if s.is_expired(now)]
        for sid in to_delete:
            del self._sessions[sid]
        return len(to_delete)
