"""Tests for the run-bot use case."""

from decimal import Decimal

from finbot.core.application.dto.run_bot_request import RunBotRequest
from finbot.core.domain.entities.bot_config import BotConfig
from finbot.core.domain.entities.trading_mode import TradingMode
from tests.conftest import create_dry_run_config, create_dry_run_use_case


def test_dry_run_startup_is_ready() -> None:
    """Dry-run mode should pass startup reconciliation without live execution."""
    use_case = create_dry_run_use_case()
    request = RunBotRequest(
        strategy_path="strategy.yaml",
        symbol="BTC",
        interval="1h",
        config=create_dry_run_config(),
    )

    result = use_case.execute(request)

    assert result.status == "ready"
    assert "mode=dry_run" in result.message


def test_live_mode_requires_acknowledgment() -> None:
    """Live mode must be rejected unless explicitly acknowledged."""
    use_case = create_dry_run_use_case()
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


def test_negative_max_position_is_rejected() -> None:
    use_case = create_dry_run_use_case()
    request = RunBotRequest(
        strategy_path="s.yaml",
        symbol="BTC",
        interval="1h",
        config=BotConfig(
            mode=TradingMode.DRY_RUN,
            max_position_usd=Decimal("-50"),
        ),
    )
    result = use_case.execute(request)
    assert result.status == "rejected"
    assert "max_position_usd" in result.message


def test_negative_daily_loss_is_rejected() -> None:
    use_case = create_dry_run_use_case()
    request = RunBotRequest(
        strategy_path="s.yaml",
        symbol="BTC",
        interval="1h",
        config=BotConfig(
            mode=TradingMode.DRY_RUN,
            max_daily_loss_usd=Decimal("-10"),
        ),
    )
    result = use_case.execute(request)
    assert result.status == "rejected"
    assert "max_daily_loss_usd" in result.message
