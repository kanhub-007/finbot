"""SQLite TelegramChatRepository — persists TelegramChat entities in SQLite."""

from __future__ import annotations

import sqlite3
from datetime import datetime

from finbot.core.domain.entities.telegram_chat import TelegramChat
from finbot.core.domain.interfaces.telegram_chat_repository import (
    TelegramChatRepository,
)


class SqliteTelegramChatRepository(TelegramChatRepository):
    """Persists TelegramChat entities in a SQLite telegram_chats table.

    The connection is cached (S13) — opened on first use and reused across
    calls to avoid the per-call connect/close overhead under Telegram polling.
    """

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._conn: sqlite3.Connection | None = None

    @property
    def _connection(self) -> sqlite3.Connection:
        """Return the cached connection, opening one on first use."""
        if self._conn is None:
            self._conn = sqlite3.connect(self._db_path)
            self._conn.execute("PRAGMA journal_mode=WAL")
        return self._conn

    async def add_chat(self, chat: TelegramChat) -> None:
        self._connection.execute(
            "INSERT OR REPLACE INTO telegram_chats "
            "(chat_id, user_id, registered_at, notifications_enabled) "
            "VALUES (?, ?, ?, ?)",
            (
                chat.chat_id,
                chat.user_id,
                chat.registered_at.isoformat(),
                1 if chat.notifications_enabled else 0,
            ),
        )
        self._connection.commit()

    async def get_chat(self, chat_id: int) -> TelegramChat | None:
        row = self._connection.execute(
            "SELECT chat_id, user_id, registered_at, notifications_enabled "
            "FROM telegram_chats WHERE chat_id = ?",
            (chat_id,),
        ).fetchone()
        if row is None:
            return None
        return _to_domain(row)

    async def list_chats(self) -> list[TelegramChat]:
        rows = self._connection.execute(
            "SELECT chat_id, user_id, registered_at, notifications_enabled "
            "FROM telegram_chats ORDER BY registered_at DESC"
        ).fetchall()
        return [_to_domain(r) for r in rows]

    async def remove_chat(self, chat_id: int) -> None:
        self._connection.execute(
            "DELETE FROM telegram_chats WHERE chat_id = ?", (chat_id,)
        )
        self._connection.commit()

    async def set_notifications(self, chat_id: int, enabled: bool) -> None:
        self._connection.execute(
            "UPDATE telegram_chats SET notifications_enabled = ? " "WHERE chat_id = ?",
            (1 if enabled else 0, chat_id),
        )
        self._connection.commit()


def _to_domain(row: tuple) -> TelegramChat:
    """Map a database row to a TelegramChat domain entity."""
    return TelegramChat(
        chat_id=int(row[0]),
        user_id=int(row[1]),
        registered_at=datetime.fromisoformat(row[2]),
        notifications_enabled=bool(row[3]),
    )
