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
    stale_data_seconds: int = Field(default=120)
