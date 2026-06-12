"""Shared test factories for Finbot.

These helpers avoid duplicating composition logic across test modules.
"""

from finbot.core.application.use_cases.run_bot import RunBotUseCase
from finbot.core.domain.entities.bot_config import BotConfig
from finbot.core.domain.entities.trading_mode import TradingMode
from finbot.infrastructure.adapters.dry_run_exchange_gateway import (
    DryRunExchangeGateway,
)
from finbot.infrastructure.adapters.finbar_strategy_evaluator import (
    FinbarStrategyEvaluator,
)
from finbot.infrastructure.adapters.in_memory_market_data_stream import (
    InMemoryMarketDataStream,
)
from finbot.infrastructure.repositories.in_memory_bot_state_repository import (
    InMemoryBotStateRepository,
)


def create_dry_run_use_case(strategy_path: str = "strategy.yaml") -> RunBotUseCase:
    """Return a use case wired with all in-memory/fake adapters."""
    return RunBotUseCase(
        exchange_gateway=DryRunExchangeGateway(),
        market_data_stream=InMemoryMarketDataStream(),
        strategy_evaluator=FinbarStrategyEvaluator(strategy_path),
        state_repository=InMemoryBotStateRepository(),
    )


def create_dry_run_config(**overrides: object) -> BotConfig:
    """Return a BotConfig defaulting to dry-run, overridable by kwargs."""
    defaults: dict[str, object] = {
        "mode": TradingMode.DRY_RUN,
        "live_trading_ack": False,
    }
    defaults.update(overrides)
    return BotConfig(**defaults)  # type: ignore[arg-type]
