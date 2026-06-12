"""Request DTO for starting a bot run."""

from dataclasses import dataclass

from finbot.core.domain.entities.bot_config import BotConfig


@dataclass(frozen=True)
class RunBotRequest:
    """Input data required to start a bot runner."""

    strategy_path: str
    symbol: str
    interval: str
    config: BotConfig
