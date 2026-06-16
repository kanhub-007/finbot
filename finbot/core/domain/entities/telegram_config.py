"""TelegramConfig — Telegram bot configuration value object."""

from dataclasses import dataclass


@dataclass(frozen=True)
class TelegramConfig:
    """Telegram bot configuration loaded from environment variables.

    Authorization fails closed: when enabled=True but allowed_user_ids is
    empty, only /whoami is permitted. All control commands are denied.
    """

    bot_token: str
    allowed_user_ids: frozenset[int]
    enabled: bool = True
    strategies_dir: str = "strategies"
    default_symbols: tuple[str, ...] = ("BTC", "ETH", "SOL", "ARB", "DOGE")

    def __post_init__(self) -> None:
        if self.enabled and not self.bot_token:
            raise ValueError("bot_token is required when Telegram is enabled")
