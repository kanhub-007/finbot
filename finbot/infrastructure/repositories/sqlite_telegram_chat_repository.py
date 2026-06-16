"""SQLite TelegramChatRepository — persists TelegramChat entities in SQLite."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from finbot.core.domain.entities.telegram_chat import TelegramChat
from finbot.core.domain.interfaces.telegram_chat_repository import (
    TelegramChatRepository,
)


class SqliteTelegramChatRepository(TelegramChatRepository):
    """Persists TelegramChat entities in a SQLite telegram_chats table."""

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self._db_path)

    async def add_chat(self, chat: TelegramChat) -> None:
        conn = self._connect()
        try:
            conn.execute(
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
            conn.commit()
        finally:
            conn.close()

    async def get_chat(self, chat_id: int) -> TelegramChat | None:
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT chat_id, user_id, registered_at, notifications_enabled "
                "FROM telegram_chats WHERE chat_id = ?",
                (chat_id,),
            ).fetchone()
            if row is None:
                return None
            return _to_domain(row)
        finally:
            conn.close()

    async def list_chats(self) -> list[TelegramChat]:
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT chat_id, user_id, registered_at, notifications_enabled "
                "FROM telegram_chats ORDER BY registered_at DESC"
            ).fetchall()
            return [_to_domain(r) for r in rows]
        finally:
            conn.close()

    async def remove_chat(self, chat_id: int) -> None:
        conn = self._connect()
        try:
            conn.execute(
                "DELETE FROM telegram_chats WHERE chat_id = ?", (chat_id,)
            )
            conn.commit()
        finally:
            conn.close()

    async def set_notifications(self, chat_id: int, enabled: bool) -> None:
        conn = self._connect()
        try:
            conn.execute(
                "UPDATE telegram_chats SET notifications_enabled = ? "
                "WHERE chat_id = ?",
                (1 if enabled else 0, chat_id),
            )
            conn.commit()
        finally:
            conn.close()


def _to_domain(row: tuple) -> TelegramChat:
    """Map a database row to a TelegramChat domain entity."""
    return TelegramChat(
        chat_id=int(row[0]),
        user_id=int(row[1]),
        registered_at=datetime.fromisoformat(row[2]),
        notifications_enabled=bool(row[3]),
    )
