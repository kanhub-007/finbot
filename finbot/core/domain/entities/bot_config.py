"""Bot runtime configuration entity."""

from dataclasses import dataclass, field
from decimal import Decimal

from finbot.core.domain.entities.private_key import PrivateKey
from finbot.core.domain.entities.trading_mode import TradingMode


@dataclass(frozen=True)
class BotConfig:
    """Validated domain-level configuration for a bot run.

    ``private_key`` is a :class:`PrivateKey` value object so the raw key is
    never exposed via ``repr`` (M5). For backward compatibility a raw
    ``str`` passed at construction is coerced to ``PrivateKey``.
    """

    mode: TradingMode = TradingMode.DRY_RUN
    live_trading_ack: bool = False
    max_position_usd: Decimal = Decimal("100")
    max_daily_loss_usd: Decimal = Decimal("25")
    max_open_orders: int = 3
    stale_data_seconds: int = 120
    private_key: PrivateKey = field(default_factory=PrivateKey)
    db_path: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.private_key, PrivateKey):
            object.__setattr__(
                self, "private_key", PrivateKey._coerce(self.private_key)
            )
