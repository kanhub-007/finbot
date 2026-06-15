"""Shared test factories for Finbot.

These helpers avoid duplicating composition logic across test modules.
"""

from typing import Any

from finbot.core.application.use_cases.run_bot import RunBotUseCase
from finbot.core.domain.entities.bot_config import BotConfig
from finbot.core.domain.entities.trading_mode import TradingMode
from finbot.infrastructure.adapters.dry_run_exchange_gateway import (
    DryRunExchangeGateway,
)
from finbot.infrastructure.adapters.in_memory_market_data_stream import (
    InMemoryMarketDataStream,
)
from finbot.infrastructure.repositories.in_memory_bot_state_repository import (
    InMemoryBotStateRepository,
)

_DEFAULT_FIXTURE_STRATEGY = "tests/fixtures/strategies/amt_dip_buyer_final.yaml"


def _load_evaluator(strategy_path: str):
    """Load a strategy and wrap its package strategy in a Finbot evaluator."""
    from finbot.infrastructure.adapters.shared_runtime_strategy_evaluator_factory import (
        SharedRuntimeStrategyEvaluatorFactory,
    )
    from finbot.infrastructure.strategy.yaml_strategy_definition_loader import (
        YamlStrategyDefinitionLoader,
    )

    loader = YamlStrategyDefinitionLoader()
    definition = loader.load_from_file(strategy_path)
    return SharedRuntimeStrategyEvaluatorFactory().create(
        definition=definition,
        symbol="",
        interval="",
        strategy_hash="test",
    )


def create_dry_run_use_case(
    strategy_path: str = _DEFAULT_FIXTURE_STRATEGY,
) -> RunBotUseCase:
    """Return a use case wired with all in-memory/fake adapters."""
    return RunBotUseCase(
        exchange_gateway=DryRunExchangeGateway(),
        market_data_stream=InMemoryMarketDataStream(),
        strategy_evaluator=_load_evaluator(strategy_path),
        state_repository=InMemoryBotStateRepository(),
    )


def create_dry_run_config(**overrides: Any) -> BotConfig:
    """Return a BotConfig defaulting to dry-run, overridable by kwargs."""
    kwargs: dict[str, Any] = {
        "mode": TradingMode.DRY_RUN,
        "live_trading_ack": False,
    }
    kwargs.update(overrides)
    return BotConfig(**kwargs)


def make_bar(**fields: object) -> dict:
    """Build a synthetic enriched bar dict for tests."""
    return dict(fields)
