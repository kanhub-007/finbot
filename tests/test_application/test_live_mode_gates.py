"""Tests for Slice 5 — live mode safety gates."""

from decimal import Decimal

from finbot.core.domain.entities.bot_config import BotConfig
from finbot.core.domain.entities.trading_mode import TradingMode
from finbot.core.domain.services.enrichment_validator import (
    EnrichmentValidator,
)
from tests.fakes import (
    FakeStrategyEvaluator,
    InMemoryBarFrameConverter,
    InMemoryExchangeGateway,
    InMemoryIndicatorEngine,
    StubBotStateRepository,
    closed_warmup_bars,
    indicator_bar,
    make_dry_run_submission_strategy,
    make_event_emitter,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_runtime(**overrides):
    from finbot.core.application.use_cases.live_trading_runtime import (
        LiveTradingRuntimeUseCase,
    )

    repo = overrides.get("state_repository") or StubBotStateRepository()
    exchange = overrides.get("exchange_gateway") or InMemoryExchangeGateway()
    kwargs = dict(
        exchange_gateway=exchange,
        strategy_evaluator=FakeStrategyEvaluator(),
        state_repository=repo,
        indicator_calculator=InMemoryIndicatorEngine(
            latest_bar=indicator_bar(atr=1200.0)
        ),
        enrichment_validator=EnrichmentValidator(),
        bar_frame_converter=InMemoryBarFrameConverter(),
        mode=TradingMode.DRY_RUN,
        submission_strategy=make_dry_run_submission_strategy(repo, exchange=exchange),
        event_emitter=make_event_emitter(),
        warmup_bars=closed_warmup_bars(100),
        required_columns={"atr"},
    )
    kwargs.update(overrides)
    return LiveTradingRuntimeUseCase(**kwargs)


def _make_validator():
    """Return a real ValidateStrategyUseCase for compatibility checks."""
    from finbot.core.application.use_cases.validate_strategy_definition import (
        ValidateStrategyUseCase,
    )
    from finbot.infrastructure.strategy.yaml_strategy_definition_loader import (
        YamlStrategyDefinitionLoader,
    )

    return ValidateStrategyUseCase(YamlStrategyDefinitionLoader())


def _live_config(**overrides) -> BotConfig:
    defaults = dict(
        mode=TradingMode.LIVE,
        live_trading_ack=True,
        max_position_usd=Decimal("100"),
        max_daily_loss_usd=Decimal("25"),
        private_key="0x" + "ab" * 32,
        db_path="data/finbot_live.db",
    )
    defaults.update(overrides)
    return BotConfig(**defaults)


# ---------------------------------------------------------------------------
# Scenario: Live mode starts only after all safety gates pass
# ---------------------------------------------------------------------------


def test_live_mode_rejected_without_ack() -> None:
    """Live mode must be rejected without explicit acknowledgment."""
    runtime = _make_runtime(mode=TradingMode.LIVE)

    result = runtime.start_live(
        strategy_path="tests/fixtures/strategies/amt_dip_buyer_final.yaml",
        symbol="BTC",
        interval="1h",
        config=_live_config(live_trading_ack=False),
    )

    assert result.status == "rejected"
    assert "FINBOT_LIVE_TRADING_ACK" in result.message


def test_live_mode_rejected_without_private_key() -> None:
    """Live mode must be rejected without a private key."""
    runtime = _make_runtime(mode=TradingMode.LIVE)

    result = runtime.start_live(
        strategy_path="tests/fixtures/strategies/amt_dip_buyer_final.yaml",
        symbol="BTC",
        interval="1h",
        config=_live_config(private_key=""),
    )

    assert result.status == "rejected"
    assert "private" in result.message.lower()


def test_live_mode_rejected_without_durable_storage() -> None:
    """Live mode must reject in-memory database."""
    runtime = _make_runtime(mode=TradingMode.LIVE)

    result = runtime.start_live(
        strategy_path="tests/fixtures/strategies/amt_dip_buyer_final.yaml",
        symbol="BTC",
        interval="1h",
        config=_live_config(db_path=":memory:"),
    )

    assert result.status == "rejected"
    assert (
        "persistence" in result.message.lower() or "database" in result.message.lower()
    )


def test_live_mode_rejected_with_zero_max_position() -> None:
    """Live mode must reject zero or negative max_position_usd."""
    runtime = _make_runtime(mode=TradingMode.LIVE)

    result = runtime.start_live(
        strategy_path="tests/fixtures/strategies/amt_dip_buyer_final.yaml",
        symbol="BTC",
        interval="1h",
        config=_live_config(max_position_usd=Decimal("0")),
    )

    assert result.status == "rejected"
    assert "max_position" in result.message.lower()


def test_live_mode_rejected_when_mode_is_not_live() -> None:
    """Mainnet access with mode != live is rejected."""
    runtime = _make_runtime(mode=TradingMode.TESTNET)

    result = runtime.start_live(
        strategy_path="tests/fixtures/strategies/amt_dip_buyer_final.yaml",
        symbol="BTC",
        interval="1h",
        config=_live_config(mode=TradingMode.TESTNET),
    )

    assert result.status == "rejected"
    assert "live" in result.message.lower()


def test_live_mode_multiple_blockers_reported_together() -> None:
    """All blockers are reported together, not one at a time."""
    runtime = _make_runtime(mode=TradingMode.LIVE)

    result = runtime.start_live(
        strategy_path="tests/fixtures/strategies/amt_dip_buyer_final.yaml",
        symbol="BTC",
        interval="1h",
        config=_live_config(
            live_trading_ack=False,
            private_key="",
            max_position_usd=Decimal("0"),
            db_path=":memory:",
        ),
    )

    assert result.status == "rejected"
    assert "FINBOT_LIVE_TRADING_ACK" in result.message
    assert "private" in result.message.lower()
    assert "max_position" in result.message.lower()


def test_live_mode_accepts_with_all_gates_met() -> None:
    """Live mode starts when all gates pass."""
    runtime = _make_runtime(mode=TradingMode.LIVE)

    result = runtime.start_live(
        strategy_path="tests/fixtures/strategies/amt_dip_buyer_final.yaml",
        symbol="BTC",
        interval="1h",
        config=_live_config(),
    )

    assert result.status == "running"


def test_live_mode_rejects_when_strategy_file_missing() -> None:
    """A missing strategy file fails closed in live mode (not silently allowed)."""
    runtime = _make_runtime(
        mode=TradingMode.LIVE,
        strategy_validator=_make_validator(),
    )

    result = runtime.start_live(
        strategy_path="tests/fixtures/strategies/does_not_exist.yaml",
        symbol="BTC",
        interval="1h",
        config=_live_config(),
    )

    assert result.status == "rejected"
    assert "compatibility" in result.message.lower() or "read" in result.message.lower()
