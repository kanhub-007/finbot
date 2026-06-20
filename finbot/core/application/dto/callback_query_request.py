"""CallbackQueryRequest — DTO for a Telegram inline-keyboard callback query."""

from dataclasses import dataclass


@dataclass(frozen=True)
class CallbackQueryRequest:
    """Request DTO carrying a parsed Telegram callback query.

    The presentation layer converts PTB CallbackQuery objects
    into this DTO before calling HandleTelegramCommand.handle_callback().
    """

    callback_data: str
    chat_id: int
    user_id: int
    message_id: int
    callback_query_id: str
