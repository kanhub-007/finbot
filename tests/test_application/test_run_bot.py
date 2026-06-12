"""Tests for the run-bot use case."""

from decimal import Decimal

from finbot.core.application.dto.run_bot_request import RunBotRequest
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


def test_dry_run_startup_is_ready() -> None:
    """Dry-run mode should pass startup reconciliation without live execution."""
    use_case = _create_use_case()
    request = RunBotRequest(
        strategy_path="strategy.yaml",
        symbol="BTC",
        interval="1h",
        config=BotConfig(mode=TradingMode.DRY_RUN),
    )

    result = use_case.execute(request)

    assert result.status == "ready"
    assert "mode=dry_run" in result.message


def test_live_mode_requires_acknowledgment() -> None:
    """Live mode must be rejected unless explicitly acknowledged."""
    use_case = _create_use_case()
    request = RunBotRequest(
        strategy_path="strategy.yaml",
        symbol="BTC",
        interval="1h",
        config=BotConfig(
            mode=TradingMode.LIVE,
            live_trading_ack=False,
            max_position_usd=Decimal("10"),
        ),
    )

    result = use_case.execute(request)

    assert result.status == "rejected"
    assert "live mode requires" in result.message


def _create_use_case() -> RunBotUseCase:
    return RunBotUseCase(
        exchange_gateway=DryRunExchangeGateway(),
        market_data_stream=InMemoryMarketDataStream(),
        strategy_evaluator=FinbarStrategyEvaluator("strategy.yaml"),
        state_repository=InMemoryBotStateRepository(),
    )
