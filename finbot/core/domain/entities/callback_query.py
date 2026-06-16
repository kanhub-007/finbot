"""CallbackQuery — immutable parsed callback query value object."""

from dataclasses import dataclass


@dataclass(frozen=True)
class CallbackQuery:
    """Immutable parsed callback query from a Telegram inline keyboard press.

    callback_data carries compact action+payload (e.g. "run:a1:strat:0").
    Full flow state is loaded from TelegramRunFlowSession.
    """

    callback_data: str
    chat_id: int
    user_id: int
    message_id: int
    callback_query_id: str
