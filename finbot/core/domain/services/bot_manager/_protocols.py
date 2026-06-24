"""Shared protocols used by both ``_manager`` and ``bot_lifecycle_service``.

Extracted to break the circular import between the two modules.
Both define Protocols consumed by the other — this file is the single
source of truth so neither module imports from the other at module level.
"""

from __future__ import annotations

from typing import Protocol

from finbot.core.domain.entities.bot_config import BotConfig


class SettingsLike(Protocol):
    """Minimal protocol for a settings object consumed by BotManager.

    The real ``Settings`` lives in ``finbot.config.settings`` (Pydantic),
    which is outside the domain layer.  This protocol keeps BotManager
    layer-clean.
    """

    mode: str
    live_trading_ack: bool
    max_position_usd: object
    max_daily_loss_usd: object
    max_open_orders: object
    stale_data_seconds: object
    hyperliquid_testnet: bool
    hyperliquid_private_key: object
    hyperliquid_account_address: str
    hyperliquid_vault_address: str
    database_path: str


class CreateBotConfigCallable(Protocol):
    """Callable that converts settings into a :class:`BotConfig`."""

    def __call__(self, settings: object) -> BotConfig: ...
