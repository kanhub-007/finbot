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

from typing import Any

from finbot.core.domain.entities.wallet_balance import WalletBalance
from finbot.core.domain.interfaces.bot_state_repository import (
    BotStateRepository,
)
from finbot.core.domain.services.bot_manager.bot_lifecycle_service import (
    BotLifecycleService,
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

_ATTR_MAP = {
    "max_position": "max_position_usd",
    "daily_loss": "max_daily_loss_usd",
    "max_orders": "max_open_orders",
    "stale_data": "stale_data_seconds",
}


class BotManager:
    """Facade for the six bot-management collaborators.

    Constructed by the composition root (``startup/mcp.py``). All public
    methods forward to the relevant collaborator.
    """

    def __init__(
        self,
        *,
        runtime_factory: Any,
        repository: BotStateRepository,
        exchange: Any | None = None,
        settings: Any | None = None,
        create_bot_config: Any | None = None,
        startup_time: float | None = None,
        metadata_provider: Any | None = None,
        config_writer: Any | None = None,
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
        self._risk_orders = RiskOrderService(self._state, self._lock, exchange)
        self._manual = ManualOrderService(
            self._state,
            self._lock,
            exchange,
            self._risk_orders,
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
        return self._lifecycle.stop()

    def get_status(self) -> dict[str, object]:
        return self._lifecycle.get_status()

    def is_running(self) -> bool:
        return self._lifecycle.is_running()

    # -- symbol session -----------------------------------------------------
    def get_active_symbol(self):
        return self._symbol.get_active_symbol()

    def activate_symbol(self, symbol: str):
        return self._symbol.activate_symbol(symbol)

    def get_active_price(self):
        return self._symbol.get_active_price()

    def get_active_position(self):
        return self._symbol.get_active_position()

    def list_active_orders(self):
        return self._symbol.list_active_orders()

    def get_balance(self) -> WalletBalance | None:
        return self._symbol.get_balance()

    def set_leverage(self, leverage: int, margin_mode: str = "isolated"):
        return self._symbol.set_leverage(leverage, margin_mode)

    # -- config -------------------------------------------------------------
    def get_bot_config(self):
        return self._config.get_bot_config()

    def update_bot_config(self, key: str, value: str):
        return self._config.update_bot_config(key, value)

    def save_config_to_env(self):
        return self._config.save_config_to_env()

    def set_default_size(self, size):
        return self._config.set_default_size(size)

    def get_default_size(self):
        return self._config.get_default_size()

    def clear_default_size(self) -> None:
        return self._config.clear_default_size()

    def save_config_profile(self, name: str):
        return self._config.save_config_profile(name)

    def load_config_profile(self, name: str):
        return self._config.load_config_profile(name)

    def list_config_profiles(self):
        return self._config.list_config_profiles()

    # -- manual orders ------------------------------------------------------
    def submit_manual_order(self, side, size=None):
        return self._manual.submit_manual_order(side, size)

    def submit_manual_order_with_brackets(
        self, side, size, sl_price=None, tp_price=None
    ):
        return self._manual.submit_manual_order_with_brackets(
            side, size, sl_price, tp_price
        )

    def cancel_order(self, order_id: str):
        return self._manual.cancel_order(order_id)

    def cancel_all_orders(self, symbol: str):
        return self._manual.cancel_all_orders(symbol)

    def close_position(self, symbol: str):
        return self._manual.close_position(symbol)

    def close_active_position(self):
        return self._manual.close_active_position()

    def clear_all(self):
        return self._manual.clear_all()

    # -- risk orders --------------------------------------------------------
    def attach_stop_loss(self, price):
        return self._risk_orders.attach_stop_loss(price)

    def attach_take_profit(self, price):
        return self._risk_orders.attach_take_profit(price)

    def clear_risk_order(self, kind: str):
        return self._risk_orders.clear_risk_order(kind)

    # -- queries ------------------------------------------------------------
    def get_bot_run(self, run_id: str):
        return self._queries.get_bot_run(run_id)

    def list_bot_runs(self, limit: int = 20, mode_filter: str | None = None):
        return self._queries.list_bot_runs(limit, mode_filter)

    def get_signals_for_run(self, run_id: str):
        return self._queries.get_signals_for_run(run_id)

    def get_orders_for_run(self, run_id: str):
        return self._queries.get_orders_for_run(run_id)

    def get_fills_for_run(self, run_id: str):
        return self._queries.get_fills_for_run(run_id)

    def get_run_counts(self, run_ids: list[str]):
        return self._queries.get_run_counts(run_ids)

    def get_risk_events_for_run(self, run_id: str):
        return self._queries.get_risk_events_for_run(run_id)

    def get_audit_log(self, limit: int = 50, event_type: str | None = None):
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
