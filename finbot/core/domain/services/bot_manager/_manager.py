"""BotManager — facade delegating to focused collaborator services (S7).

Decomposed from the former ``BotManager`` + ``TradingControlMixin``
(~1300 lines) into six collaborators, each with a single responsibility:

* :class:`BotLifecycleService`  — start/stop/status, runtime thread
* :class:`ManualOrderService`   — manual orders, cancel, clear, close
* :class:`SymbolSessionService` — active symbol, leverage, price, position
* :class:`RuntimeConfigService` — runtime config, profiles, default size
* :class:`RiskOrderService`     — SL/TP attach/clear
* :class:`BotQueryService`      — read-only history queries

BotManager is a thin facade that constructs the collaborators from a
shared :class:`BotManagerState` + :class:`BotManagerLock` and forwards
every public method. It preserves the original public API so all
existing callers (MCP tools, Telegram handler, tests) work unchanged.
"""

from __future__ import annotations

from typing import Any, Protocol

from finbot.core.domain.entities.bot_config import BotConfig
from finbot.core.domain.entities.wallet_balance import WalletBalance
from finbot.core.domain.interfaces.bot_state_repository import (
    BotStateRepository,
)
from finbot.core.domain.interfaces.config_writer_port import ConfigWriterPort
from finbot.core.domain.interfaces.exchange_gateway import ExchangeGateway
from finbot.core.domain.interfaces.market_metadata_provider import (
    MarketMetadataProvider,
)
from finbot.core.domain.services.bot_manager.bot_lifecycle_service import (
    BotLifecycleService,
    RuntimeFactory,
)
from finbot.core.domain.services.bot_manager.bot_manager_lock import (
    BotManagerLock,
)
from finbot.core.domain.services.bot_manager.bot_manager_state import (
    BotManagerState,
)
from finbot.core.domain.services.bot_manager.bot_query_service import (
    BotQueryService,
)
from finbot.core.domain.services.bot_manager.manual_order_service import (
    ManualOrderService,
)
from finbot.core.domain.services.bot_manager.risk_order_service import (
    RiskOrderService,
)
from finbot.core.domain.services.bot_manager.runtime_config_service import (
    RuntimeConfigService,
)
from finbot.core.domain.services.bot_manager.symbol_session_service import (
    SymbolSessionService,
)


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


_ATTR_MAP: dict[str, str] = {
    "max_position": "max_position_usd",
    "daily_loss": "max_daily_loss_usd",
    "max_orders": "max_open_orders",
    "stale_data": "stale_data_seconds",
}

# Validate at import time: every key in RuntimeBotConfig.AVAILABLE_KEYS
# must have an entry in _ATTR_MAP, and the mapped setting attribute must be
# usable by getattr().
def _validate_attr_map() -> None:
    from finbot.core.domain.entities.runtime_bot_config import RuntimeBotConfig

    missing = [k for k in RuntimeBotConfig.AVAILABLE_KEYS if k not in _ATTR_MAP]
    if missing:
        raise AssertionError(
            f"_ATTR_MAP missing entries for: {missing}. "
            f"Add them to keep runtime-config seeding correct."
        )


_validate_attr_map()


class BotManager:
    """Facade for the six bot-management collaborators.

    Constructed by the composition root (``startup/mcp.py``). All public
    methods forward to the relevant collaborator.
    """

    def __init__(
        self,
        *,
        runtime_factory: RuntimeFactory,
        repository: BotStateRepository,
        exchange: ExchangeGateway | None = None,
        settings: SettingsLike | None = None,
        create_bot_config: CreateBotConfigCallable | None = None,
        startup_time: float | None = None,
        metadata_provider: MarketMetadataProvider | None = None,
        config_writer: ConfigWriterPort | None = None,
    ) -> None:
        self._lock = BotManagerLock()
        self._state = BotManagerState()
        self._state.runtime_config = _seed_runtime_config(settings)
        self._state.active_symbol = _restore_active_symbol(repository)
        self._lifecycle = BotLifecycleService(
            self._state,
            self._lock,
            repository,
            exchange,
            runtime_factory,
            settings,
            create_bot_config,
            startup_time,
        )
        self._queries = BotQueryService(repository)
        self._symbol = SymbolSessionService(
            self._state, self._lock, exchange, metadata_provider, repository
        )
        self._config = RuntimeConfigService(self._state, self._lock, config_writer)
        self._risk_orders = RiskOrderService(
            self._state, self._lock, exchange, repository
        )
        self._manual = ManualOrderService(
            self._state,
            self._lock,
            exchange,
            self._risk_orders,
            repository=repository,
            metadata_provider=metadata_provider,
            mode=getattr(settings, "mode", "dry_run") if settings else "dry_run",
            live_trading_ack=(
                getattr(settings, "live_trading_ack", False) if settings else False
            ),
        )
        self._lifecycle._set_leverage_fn = self._symbol.set_leverage  # noqa: SLF001

    @property
    def live_state(self):
        """The live status snapshot (for MCP tools)."""
        return self._lifecycle.live_state

    @property
    def has_exchange(self) -> bool:
        return self._symbol.has_exchange

    @property
    def _metadata_provider(self):
        """Forward to symbol-session + manual-order collaborators (test compat)."""
        return self._symbol._metadata_provider  # noqa: SLF001

    @_metadata_provider.setter
    def _metadata_provider(self, value):
        self._symbol._metadata_provider = value  # noqa: SLF001
        self._manual._metadata_provider = value  # noqa: SLF001

    @property
    def _runtime_factory(self):
        """Forward to lifecycle collaborator (test compat)."""
        return self._lifecycle._runtime_factory  # noqa: SLF001

    # -- lifecycle ----------------------------------------------------------

    def start(
        self,
        strategy_path: str,
        symbol: str,
        interval: str,
        mode: str,
        warmup_bars: int = 100,
        live_trading_ack: bool = False,
        execution_config: Any | None = None,
    ) -> dict[str, str]:
        """Start a bot in a background thread.  Delegates to BotLifecycleService."""
        return self._lifecycle.start(
            strategy_path,
            symbol,
            interval,
            mode,
            warmup_bars,
            live_trading_ack,
            execution_config,
        )

    def stop(self) -> dict[str, str]:
        """Stop the running bot and join its thread."""
        return self._lifecycle.stop()

    def get_status(self) -> dict[str, object]:
        """Return a live status snapshot (dict, not typed DTO)."""
        return self._lifecycle.get_status()

    def is_running(self) -> bool:
        """Return True if a bot is currently running."""
        return self._lifecycle.is_running()

    # -- symbol session -----------------------------------------------------

    def get_active_symbol(self):
        """Return the active symbol state, or None if idle."""
        return self._symbol.get_active_symbol()

    def activate_symbol(self, symbol: str):
        """Activate a trading symbol, reading leverage from the exchange."""
        return self._symbol.activate_symbol(symbol)

    def get_active_price(self):
        """Return the current price for the active symbol, or None if idle."""
        return self._symbol.get_active_price()

    def get_active_position(self):
        """Return the exchange position for the active symbol, or None."""
        return self._symbol.get_active_position()

    def list_active_orders(self):
        """Return open orders for the active symbol, or None if idle."""
        return self._symbol.list_active_orders()

    def get_balance(self) -> WalletBalance | None:
        """Return the wallet balance, or None if no exchange is wired."""
        return self._symbol.get_balance()

    def set_leverage(self, leverage: int, margin_mode: str = "isolated"):
        """Set leverage on the active symbol; validates against symbol max."""
        return self._symbol.set_leverage(leverage, margin_mode)

    # -- config -------------------------------------------------------------

    def get_bot_config(self):
        """Return the current RuntimeBotConfig snapshot."""
        return self._config.get_bot_config()

    def update_bot_config(self, key: str, value: str):
        """Set a runtime config value by short key (e.g. 'max_position')."""
        return self._config.update_bot_config(key, value)

    def save_config_to_env(self):
        """Persist the current runtime config back to .env."""
        return self._config.save_config_to_env()

    def set_default_size(self, size):
        """Set the default order size for manual orders."""
        return self._config.set_default_size(size)

    def get_default_size(self):
        """Return the default order size, or None."""
        return self._config.get_default_size()

    def clear_default_size(self) -> None:
        """Clear the default order size."""
        return self._config.clear_default_size()

    def save_config_profile(self, name: str):
        """Save a named config profile to .env."""
        return self._config.save_config_profile(name)

    def load_config_profile(self, name: str):
        """Load a named config profile from .env."""
        return self._config.load_config_profile(name)

    def list_config_profiles(self):
        """Return available config profile names from .env."""
        return self._config.list_config_profiles()

    # -- manual orders ------------------------------------------------------

    def submit_manual_order(self, side, size=None, limit_px=None, usd_notional=None):
        """Submit a manual market or limit order on the active symbol."""
        return self._manual.submit_manual_order(
            side, size, limit_px=limit_px, usd_notional=usd_notional
        )

    def submit_manual_order_with_brackets(
        self, side, size, sl_price=None, tp_price=None, limit_px=None, usd_notional=None
    ):
        """Submit a manual entry then attach SL/TP triggers in one call."""
        return self._manual.submit_manual_order_with_brackets(
            side, size, sl_price, tp_price, limit_px=limit_px, usd_notional=usd_notional
        )

    def cancel_order(self, order_id: str):
        """Cancel a single order on the active symbol by exchange oid."""
        return self._manual.cancel_order(order_id)

    def cancel_all_orders(self, symbol: str):
        """Cancel all open orders for a symbol via the exchange."""
        return self._manual.cancel_all_orders(symbol)

    def close_position(self, symbol: str):
        """Market-close the position for a symbol; clears SL/TP."""
        return self._manual.close_position(symbol)

    def close_active_position(self):
        """Reduce-only market close on the active symbol; clears SL/TP."""
        return self._manual.close_active_position()

    def clear_all(self):
        """Cancel all orders and close all positions on the active symbol."""
        return self._manual.clear_all()

    # -- risk orders --------------------------------------------------------

    def attach_stop_loss(self, price):
        """Attach or update a stop-loss trigger order."""
        return self._risk_orders.attach_stop_loss(price)

    def attach_take_profit(self, price):
        """Attach or update a take-profit trigger order."""
        return self._risk_orders.attach_take_profit(price)

    def clear_risk_order(self, kind: str):
        """Clear a stop-loss or take-profit trigger order."""
        return self._risk_orders.clear_risk_order(kind)

    # -- queries ------------------------------------------------------------

    def get_bot_run(self, run_id: str):
        """Return a single bot run by its run_id, or None."""
        return self._queries.get_bot_run(run_id)

    def list_bot_runs(self, limit: int = 20, mode_filter: str | None = None):
        """Return recent bot runs ordered by started_at DESC."""
        return self._queries.list_bot_runs(limit, mode_filter)

    def get_signals_for_run(self, run_id: str):
        """Return all signals for a specific bot run."""
        return self._queries.get_signals_for_run(run_id)

    def get_orders_for_run(self, run_id: str):
        """Return all order responses for a specific bot run."""
        return self._queries.get_orders_for_run(run_id)

    def get_fills_for_run(self, run_id: str):
        """Return all fills for a specific bot run."""
        return self._queries.get_fills_for_run(run_id)

    def get_run_counts(self, run_ids: list[str]):
        """Return per-run signal/order/fill counts via GROUP BY."""
        return self._queries.get_run_counts(run_ids)

    def get_risk_events_for_run(self, run_id: str):
        """Return all risk events for a specific bot run."""
        return self._queries.get_risk_events_for_run(run_id)

    def get_audit_log(self, limit: int = 50, event_type: str | None = None):
        """Return recent audit log entries."""
        return self._queries.get_audit_log(limit, event_type)


def _seed_runtime_config(settings: Any):
    """Build a RuntimeBotConfig from settings (.env defaults)."""
    from finbot.core.domain.entities.runtime_bot_config import RuntimeBotConfig

    cfg = RuntimeBotConfig()
    if settings is None:
        return cfg
    for key in RuntimeBotConfig.AVAILABLE_KEYS:
        attr = _ATTR_MAP.get(key)
        if attr is None:
            continue
        val = getattr(settings, attr, None)
        if val is not None:
            try:
                cfg.set(key, str(val))
            except (KeyError, ValueError):
                pass
    return cfg


def _restore_active_symbol(repo: BotStateRepository):
    """Load persisted active symbol on startup (best-effort)."""
    import logging

    logger = logging.getLogger(__name__)
    try:
        return repo.load_active_symbol()
    except Exception:
        logger.warning("Could not restore active symbol state")
        return None
