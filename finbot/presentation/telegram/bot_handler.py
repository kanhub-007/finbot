"""Telegram bot handler — presentation layer connecting PTB to application."""

from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import Application, CallbackQueryHandler, CommandHandler

from finbot.core.application.dto.callback_query_request import (
    CallbackQueryRequest,
)
from finbot.core.application.dto.telegram_command_request import (
    TelegramCommandRequest,
)
from finbot.core.application.use_cases.handle_telegram_command import (
    HandleTelegramCommand,
)
from finbot.core.domain.interfaces.telegram_bot_port import TelegramBotPort

logger = logging.getLogger(__name__)

_HANDLED_COMMANDS = [
    "start",
    "whoami",
    "stop",
    "status",
    "run",
    "history",
    "panic",
    "help",
    "list",
    "mute",
    "unmute",
    # trading-control spec
    "symbol",
    "price",
    "balance",
    "leverage",
    "position",
    "mode",
    "long",
    "short",
    "close",
    "clear",
    "sl",
    "tp",
    "config",
    "size",
    "orders",
    "cancel",
    "log",
]


class TelegramBotHandler:
    """Wires PTB Application handlers to the HandleTelegramCommand use case.

    Converts PTB Update objects to DTOs, calls the use case, then converts
    the resulting DTOs back to PTB send/edit calls. Contains zero domain logic.
    """

    def __init__(
        self,
        bot_token: str,
        command_use_case: HandleTelegramCommand,
        bot_port: TelegramBotPort,
    ) -> None:
        self._use_case = command_use_case
        self._bot_port = bot_port
        self._app = Application.builder().token(bot_token).build()

        for cmd in _HANDLED_COMMANDS:
            self._app.add_handler(CommandHandler(cmd, self._handle_command))
        self._app.add_handler(CallbackQueryHandler(self._handle_callback))

    async def start_polling(self) -> None:
        """Initialize the PTB application and start long-polling."""
        await self._app.initialize()
        await self._app.start()
        await self._app.updater.start_polling()

    async def stop(self) -> None:
        """Stop polling and shut down the PTB application."""
        if self._app.updater:
            await self._app.updater.stop()
        await self._app.stop()
        await self._app.shutdown()

    # -- PTB handlers --------------------------------------------------------

    async def _handle_command(self, update: Update, context: object) -> None:
        """Convert a PTB command to DTO, execute, send/edit result."""
        if update.message is None or update.effective_user is None:
            return

        try:
            request = TelegramCommandRequest(
                command=(
                    f"/{update.message.text.split()[0].strip('/').split('@')[0]}"
                    if update.message.text
                    else "/start"
                ),
                args=(
                    update.message.text.split(maxsplit=1)[1]
                    if update.message.text and " " in update.message.text
                    else ""
                ),
                chat_id=update.effective_chat.id,
                user_id=update.effective_user.id,
                message_id=update.message.message_id,
            )

            result = await self._use_case.execute(request)
            send_result = await self._send_result(
                chat_id=request.chat_id,
                message_id=request.message_id,
                result=result,
            )
            if not send_result.success:
                logger.error(
                    "Failed to send command response for %s: %s",
                    request.command,
                    send_result.error,
                )
        except Exception:
            logger.exception("Unhandled error in command handler")

    async def _handle_callback(self, update: Update, context: object) -> None:
        """Convert a PTB callback query to DTO, execute, edit result."""
        query = update.callback_query
        if query is None or update.effective_user is None:
            return

        await self._bot_port.answer_callback_query(query.id)

        try:
            request = CallbackQueryRequest(
                callback_data=query.data or "",
                chat_id=update.effective_chat.id,
                user_id=update.effective_user.id,
                message_id=query.message.message_id if query.message else 0,
                callback_query_id=query.id,
            )

            result = await self._use_case.handle_callback(request)
            if query.message:
                send_result = await self._send_result(
                    chat_id=request.chat_id,
                    message_id=query.message.message_id,
                    result=result,
                )
                if not send_result.success:
                    logger.error(
                        "Failed to send callback response for %s: %s",
                        request.callback_data,
                        send_result.error,
                    )
        except Exception:
            logger.exception("Unhandled error in callback handler")

    async def _send_result(
        self,
        chat_id: int,
        message_id: int,
        result: object,
    ):
        """Send or edit a message based on the use-case result DTO.

        Returns the SendResult so callers can check for delivery errors.
        """
        from finbot.core.application.dto.telegram_command_result import (
            TelegramCommandResult,
        )

        r: TelegramCommandResult = result  # type: ignore[assignment]

        if r.edit_message_id is not None:
            return await self._bot_port.edit_message_text(
                chat_id=chat_id,
                message_id=r.edit_message_id,
                text=r.text,
                parse_mode=r.parse_mode,
                reply_markup=r.reply_markup,
            )
        else:
            return await self._bot_port.send_message(
                chat_id=chat_id,
                text=r.text,
                parse_mode=r.parse_mode,
                reply_markup=r.reply_markup,
            )
