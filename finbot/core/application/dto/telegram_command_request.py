"""TelegramCommandRequest — DTO for a Telegram slash command entering the use case."""

from dataclasses import dataclass


@dataclass(frozen=True)
class TelegramCommandRequest:
    """Request DTO carrying a parsed Telegram command.

    The presentation layer (TelegramBotHandler) converts PTB Update
    objects into this DTO before calling HandleTelegramCommand.execute().
    """

    command: str
    args: str
    chat_id: int
    user_id: int
    message_id: int
