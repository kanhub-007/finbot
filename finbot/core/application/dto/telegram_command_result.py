"""TelegramCommandResult — DTO returned by HandleTelegramCommand for presentation."""

from dataclasses import dataclass


@dataclass(frozen=True)
class TelegramCommandResult:
    """Response DTO returned by the command use case.

    The use case populates text and optional reply_markup. The presentation
    layer converts this into actual Telegram send/edit calls. The use case
    never calls TelegramBotPort directly.
    """

    text: str
    parse_mode: str = "MarkdownV2"
    reply_markup: dict | None = None
    edit_message_id: int | None = None
