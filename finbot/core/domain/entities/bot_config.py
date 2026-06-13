"""Bot runtime configuration entity."""

from dataclasses import dataclass
from decimal import Decimal

from finbot.core.domain.entities.trading_mode import TradingMode


@dataclass(frozen=True)
class BotConfig:
    """Validated domain-level configuration for a bot run."""

    mode: TradingMode = TradingMode.DRY_RUN
    live_trading_ack: bool = False
    max_position_usd: Decimal = Decimal("100")
    max_daily_loss_usd: Decimal = Decimal("25")
    max_open_orders: int = 3
    stale_data_seconds: int = 120
    private_key: str = ""
    db_path: str = ""
