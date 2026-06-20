"""PythonTelegramBotAdapter — wraps python-telegram-bot's Bot as a TelegramBotPort."""

from __future__ import annotations

from typing import Any

from telegram import Bot
from telegram.error import TelegramError

from finbot.core.domain.entities.send_result import SendResult
from finbot.core.domain.interfaces.telegram_bot_port import TelegramBotPort

# PTB error types considered transient (may succeed on retry)
_TRANSIENT_ERROR_TYPES: frozenset[str] = frozenset(
    {
        "TimedOut",
        "NetworkError",
        "RetryAfter",
    }
)


class PythonTelegramBotAdapter(TelegramBotPort):
    """Adapter wrapping ``telegram.Bot`` to implement ``TelegramBotPort``.

    Catches ``TelegramError`` and returns ``SendResult`` instead of raising.
    Classifies errors as transient (network/timeout) or permanent (chat not
    found, bot blocked, etc.) so callers can decide on retry behavior.
    """

    def __init__(
        self,
        bot_token: str | None = None,
        *,
        bot: Bot | None = None,
    ) -> None:
        if bot is not None:
            self._bot = bot
        elif bot_token:
            self._bot = Bot(token=bot_token)
        else:
            raise ValueError("bot_token is required")

    async def send_message(
        self,
        chat_id: int,
        text: str,
        parse_mode: str | None = None,
        reply_markup: dict | None = None,
    ) -> SendResult:
        try:
            msg = await self._bot.send_message(
                chat_id=chat_id,
                text=text,
                parse_mode=parse_mode,
                reply_markup=_to_ptb_markup(reply_markup),
            )
            return SendResult(success=True, message_id=msg.message_id)
        except TelegramError as e:
            return SendResult(
                success=False,
                error=str(e),
                transient=_is_transient(e),
            )

    async def edit_message_text(
        self,
        chat_id: int,
        message_id: int,
        text: str,
        parse_mode: str | None = None,
        reply_markup: dict | None = None,
    ) -> SendResult:
        try:
            msg = await self._bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=text,
                parse_mode=parse_mode,
                reply_markup=_to_ptb_markup(reply_markup),
            )
            return SendResult(
                success=True,
                message_id=msg.message_id,
            )
        except TelegramError as e:
            return SendResult(
                success=False,
                error=str(e),
                transient=_is_transient(e),
            )

    async def answer_callback_query(
        self,
        callback_query_id: str,
        text: str | None = None,
    ) -> bool:
        try:
            await self._bot.answer_callback_query(
                callback_query_id=callback_query_id,
                text=text,
            )
            return True
        except TelegramError:
            return False

    async def edit_message_reply_markup(
        self,
        chat_id: int,
        message_id: int,
        reply_markup: dict | None = None,
    ) -> bool:
        try:
            await self._bot.edit_message_reply_markup(
                chat_id=chat_id,
                message_id=message_id,
                reply_markup=_to_ptb_markup(reply_markup),
            )
            return True
        except TelegramError:
            return False


def _is_transient(error: TelegramError) -> bool:
    """Determine if a TelegramError is likely transient."""
    error_type = type(error).__name__
    if error_type in _TRANSIENT_ERROR_TYPES:
        return True
    message = str(error).lower()
    transient_phrases = ("timed out", "timeout", "too many requests", "retry")
    return any(phrase in message for phrase in transient_phrases)


def _to_ptb_markup(reply_markup: dict | None) -> Any | None:
    """Convert a dict inline keyboard to a PTB InlineKeyboardMarkup."""
    if reply_markup is None:
        return None
    try:
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup

        keyboard = []
        for row in reply_markup.get("inline_keyboard", []):
            keyboard_row = []
            for btn in row:
                keyboard_row.append(
                    InlineKeyboardButton(
                        text=btn["text"],
                        callback_data=btn.get("callback_data", ""),
                    )
                )
            keyboard.append(keyboard_row)
        return InlineKeyboardMarkup(keyboard)
    except Exception:
        return None
