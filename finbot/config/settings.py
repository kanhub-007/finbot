"""Application settings loaded from environment variables."""

from decimal import Decimal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration for Finbot.

    Values are read from environment variables prefixed with `FINBOT_` and may
    be supplied through a local `.env` file.

    Private key values use pydantic.SecretStr to prevent accidental exposure
    in logs, repr, or tracebacks.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="FINBOT_",
        extra="ignore",
    )

    mode: str = Field(default="dry_run")
    live_trading_ack: bool = Field(default=False)
    hyperliquid_testnet: bool = Field(default=True)
    hyperliquid_private_key: SecretStr = Field(
        default=SecretStr(""),
    )
    hyperliquid_account_address: str = Field(default="")
    hyperliquid_vault_address: str = Field(default="")
    database_url: str = Field(default="sqlite:///data/finbot.db")
    max_position_usd: Decimal = Field(default=Decimal("100"))
    max_daily_loss_usd: Decimal = Field(default=Decimal("25"))
    max_open_orders: int = Field(default=3)
    max_leverage: int = Field(default=20)
    stale_data_seconds: int = Field(default=120)
    telegram_bot_token: SecretStr = Field(default=SecretStr(""))
    telegram_allowed_users: str = Field(default="")
    telegram_enabled: bool = Field(default=False)
    telegram_strategies_dir: str = Field(default="strategies")

    @property
    def database_path(self) -> str:
        """Extract the filesystem path from the database URL."""
        url = self.database_url
        if url.startswith("sqlite:///"):
            return url[len("sqlite:///") :]
        return url

    @property
    def telegram_allowed_user_ids(self) -> frozenset[int]:
        """Parse the comma-separated allowed user IDs.

        Non-numeric entries are silently skipped so a single typo
        does not break the entire allowlist.
        """
        if not self.telegram_allowed_users.strip():
            return frozenset()
        ids: set[int] = set()
        for uid in self.telegram_allowed_users.split(","):
            uid = uid.strip()
            if not uid:
                continue
            try:
                ids.add(int(uid))
            except ValueError:
                pass
        return frozenset(ids)

    @property
    def telegram_control_configured(self) -> bool:
        """Check if Telegram control is configured with allowed users."""
        return bool(self.telegram_allowed_user_ids)
