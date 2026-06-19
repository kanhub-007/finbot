"""Composition root for Finbot services.

The runtime factory lives in ``runtime_factory.py`` (S10 split);
it is re-exported here for backwards-compatible imports.
"""

from finbot.config.settings import Settings
from finbot.core.application.dto.run_bot_request import RunBotRequest
from finbot.core.application.use_cases.replay_strategy import (
    ReplayStrategyUseCase,
)
from finbot.core.application.use_cases.run_bot import RunBotUseCase
from finbot.core.application.use_cases.validate_strategy_definition import (
    ValidateStrategyUseCase,
)
from finbot.core.domain.entities.bot_config import BotConfig
from finbot.core.domain.entities.trading_mode import TradingMode
from finbot.core.domain.interfaces.exchange_gateway import ExchangeGateway
from finbot.infrastructure.adapters.dry_run_exchange_gateway import (
    DryRunExchangeGateway,
)
from finbot.infrastructure.adapters.hyperliquid_exchange_gateway import (
    HyperliquidExchangeGateway,
)
from finbot.infrastructure.adapters.in_memory_market_data_stream import (
    InMemoryMarketDataStream,
)
from finbot.infrastructure.repositories.in_memory_bot_state_repository import (
    InMemoryBotStateRepository,
)
from finbot.infrastructure.strategy.csv_bar_loader import CsvBarLoader
from finbot.infrastructure.strategy.yaml_strategy_definition_loader import (
    YamlStrategyDefinitionLoader,
)

# Hyperliquid REST endpoints — single source of truth for URL selection.
_MAINNET_URL = "https://api.hyperliquid.xyz"
_TESTNET_URL = "https://api.hyperliquid-testnet.xyz"


def hyperliquid_base_url(settings: Settings) -> str:
    """Return the Hyperliquid REST URL for the configured environment."""
    return _TESTNET_URL if settings.hyperliquid_testnet else _MAINNET_URL


def create_bot_config(settings: Settings) -> BotConfig:
    """Create a domain bot configuration from environment settings."""
    from finbot.core.domain.entities.private_key import PrivateKey

    return BotConfig(
        mode=TradingMode(settings.mode),
        live_trading_ack=settings.live_trading_ack,
        max_position_usd=settings.max_position_usd,
        max_daily_loss_usd=settings.max_daily_loss_usd,
        max_open_orders=settings.max_open_orders,
        stale_data_seconds=settings.stale_data_seconds,
        private_key=PrivateKey(settings.hyperliquid_private_key.get_secret_value()),
        db_path=settings.database_path,
    )


def _build_exchange_gateway(settings: Settings, mode: TradingMode) -> ExchangeGateway:
    """Create the correct exchange gateway for the given mode.

    Dry-run uses a no-op gateway; testnet/live use the real Hyperliquid
    gateway wired with credentials and the environment-appropriate URL.
    """
    if mode == TradingMode.DRY_RUN:
        return DryRunExchangeGateway()
    return HyperliquidExchangeGateway(
        private_key=settings.hyperliquid_private_key.get_secret_value(),
        base_url=hyperliquid_base_url(settings),
        account_address=settings.hyperliquid_account_address,
        vault_address=settings.hyperliquid_vault_address,
    )


def create_exchange_gateway(settings: Settings) -> ExchangeGateway:
    """Create a Hyperliquid exchange gateway from settings.

    Used by kill-switch / panic commands that need the gateway directly.
    """
    return _build_exchange_gateway(settings, TradingMode(settings.mode))


def create_run_bot_use_case(
    settings: Settings,
    strategy_path: str,
    symbol: str = "",
    interval: str = "",
    live_data: bool = False,
) -> RunBotUseCase:
    """Create a fully wired run-bot use case.

    When ``live_data`` is True the Hyperliquid websocket stream is used
    instead of the in-memory stub (dry-run only — no orders placed).
    """
    mode = TradingMode(settings.mode)
    if live_data:
        from finbot.infrastructure.adapters.hyperliquid_market_data_stream import (
            HyperliquidMarketDataStream,
        )

        stream = HyperliquidMarketDataStream(
            base_url=hyperliquid_base_url(settings),
            stale_data_seconds=settings.stale_data_seconds,
        )
    else:
        stream = InMemoryMarketDataStream()
    return RunBotUseCase(
        exchange_gateway=_build_exchange_gateway(settings, mode),
        market_data_stream=stream,
        strategy_evaluator=_build_strategy_evaluator(strategy_path, symbol, interval),
        state_repository=InMemoryBotStateRepository(),
    )


def _build_strategy_evaluator(strategy_path: str, symbol: str, interval: str):
    """Load a strategy file and wrap its package strategy in a Finbot adapter.

    Used by legacy validate-and-exit wiring; the live runtime builds its
    own evaluator via the shared factory.
    """
    from finbot.core.domain.interfaces.strategy_evaluator import StrategyEvaluator
    from finbot.infrastructure.adapters import (
        shared_runtime_strategy_evaluator_factory as _eval_factory_mod,
    )
    from finbot.startup.runtime_factory import _hash_strategy_file

    loader = YamlStrategyDefinitionLoader()
    definition = loader.load_from_file(strategy_path)
    strategy_hash = _hash_strategy_file(strategy_path)
    evaluator: (
        StrategyEvaluator
    ) = _eval_factory_mod.SharedRuntimeStrategyEvaluatorFactory().create(
        definition=definition,
        symbol=symbol,
        interval=interval,
        strategy_hash=strategy_hash,
    )
    return evaluator


def create_run_bot_request(
    settings: Settings,
    strategy_path: str,
    symbol: str,
    interval: str,
) -> RunBotRequest:
    """Create a run-bot request DTO from CLI and environment values."""
    return RunBotRequest(
        strategy_path=strategy_path,
        symbol=symbol,
        interval=interval,
        config=create_bot_config(settings),
    )


def create_validate_strategy_use_case() -> ValidateStrategyUseCase:
    """Create a fully wired validate-strategy use case."""
    import finbar_strategy_runtime as _runtime

    from finbot.infrastructure.adapters.package_capability_provider import (
        supported_indicator_types,
        supported_stop_loss_types,
    )

    return ValidateStrategyUseCase(
        loader=YamlStrategyDefinitionLoader(),
        supported_indicators=supported_indicator_types(),
        supported_risk_types=supported_stop_loss_types(),
        runtime_package_version=_runtime.__version__,
    )


def create_replay_strategy_use_case(
    warmup_min_bars: int = 0,
) -> ReplayStrategyUseCase:
    """Create a fully wired replay-strategy use case.

    When ``warmup_min_bars`` is > 0 a :class:`WarmupWindow` is wired in
    so signals are suppressed until the minimum bar count is reached.
    """
    from finbot.core.domain.services.warmup_window import WarmupWindow

    warmup = None
    if warmup_min_bars:
        warmup = WarmupWindow(min_bars=warmup_min_bars)

    from finbot.infrastructure.adapters import (
        shared_runtime_strategy_evaluator_factory as _eval_factory_mod,
    )

    return ReplayStrategyUseCase(
        loader=YamlStrategyDefinitionLoader(),
        bar_loader=CsvBarLoader(),
        evaluator_factory=_eval_factory_mod.SharedRuntimeStrategyEvaluatorFactory(),
        warmup=warmup,
    )


def db_path_from_settings() -> str:
    return Settings().database_path or "data/finbot.db"


def create_bot_state_repository(*, migrate: bool = True):
    """Create the default SQLite bot state repository.

    Parameters
    ----------
    migrate:
        When ``True`` (default), pending schema migrations are applied
        before the repository is returned.  Set to ``False`` for
        read-only commands like ``status`` that should never trigger
        DDL.
    """
    from finbot.infrastructure.repositories.sqlite_bot_state_repository import (
        SqliteBotStateRepository,
    )

    db_path = db_path_from_settings()
    if migrate:
        from finbot.infrastructure.repositories.sqlite_migrator import (
            SqliteMigrator,
        )

        SqliteMigrator(db_path).migrate()
    return SqliteBotStateRepository(db_path)


def create_in_memory_repository():
    """Create an in-memory repository for tests/dry-runs."""
    from finbot.infrastructure.repositories.in_memory_bot_state_repository import (
        InMemoryBotStateRepository,
    )

    return InMemoryBotStateRepository()


def create_status_use_case():
    """Create a fully wired status use case (read-only — no migrations)."""
    from finbot.core.application.use_cases.status import StatusUseCase

    return StatusUseCase(repo=create_bot_state_repository(migrate=False))


def create_bot_loop(
    settings: Settings,
    gateway: ExchangeGateway | None = None,
    *,
    account: bool = False,
):
    """Create the market-data (and optional account) event loop.

    Parameters
    ----------
    settings:
        Runtime settings (stale-data threshold, testnet flag, credentials).
    gateway:
        Exchange gateway whose SDK ``Exchange`` backs the account stream.
        Required when ``account=True``.
    account:
        When ``True`` (testnet/live), subscribe to user fills and order
        updates so lifecycle/fill handling is fed by real exchange events.
    """
    from finbot.infrastructure.adapters.bot_event_loop import BotEventLoop
    from finbot.infrastructure.adapters.hyperliquid_market_data_stream import (
        HyperliquidMarketDataStream,
    )
    from finbot.infrastructure.adapters.thread_safe_event_queue import (
        ThreadSafeEventQueue,
    )

    queue = ThreadSafeEventQueue()
    stream = HyperliquidMarketDataStream(
        base_url=hyperliquid_base_url(settings),
        stale_data_seconds=settings.stale_data_seconds,
    )
    account_stream = None
    if account:
        if gateway is None:
            raise ValueError("account=True requires an exchange gateway")
        from finbot.infrastructure.adapters.hyperliquid_account_data_stream import (
            HyperliquidAccountDataStream,
        )
        from finbot.infrastructure.adapters.hyperliquid_exchange_gateway import (
            HyperliquidExchangeGateway,
        )

        if not isinstance(gateway, HyperliquidExchangeGateway):
            raise ValueError("account stream requires a HyperliquidExchangeGateway")
        account_stream = HyperliquidAccountDataStream(
            exchange=gateway.get_exchange(),
            queue=queue,
            user_address=settings.hyperliquid_account_address,
            account_cache=gateway.account_cache(),
        )
    return BotEventLoop(queue, stream, account_stream=account_stream)


# Re-export the runtime factory at the bottom (S10) to avoid a circular
# import: runtime_factory imports helpers from this module, so this must
# run after they are defined.
from finbot.startup.runtime_factory import (  # noqa: E402, F401
    create_live_trading_runtime_use_case,
)
