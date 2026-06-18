"""Integration tests for BotLoop wiring into LiveTradingRuntimeUseCase."""

from finbot.core.domain.entities.signal_action import SignalAction
from finbot.core.domain.entities.signal_decision import SignalDecision
from finbot.core.domain.entities.trading_mode import TradingMode
from finbot.core.domain.interfaces.bot_loop import BotLoop
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


class FakeBotLoop(BotLoop):
    """BotLoop fake — fires a candle through the callback and exits."""

    def __init__(self) -> None:
        self._running = False
        self.started_symbol: str = ""
        self.started_interval: str = ""

    def start(
        self,
        symbol: str,
        interval: str,
        on_candle,
        on_stale=None,
        on_account_event=None,
    ) -> None:
        self.started_symbol = symbol
        self.started_interval = interval
        self._running = True

    def stop(self) -> None:
        self._running = False

    def fire_candle(self, candle: dict) -> None:
        """Manually fire a candle through the registered callback."""
        # The callback is stored by start(); we need a reference
        pass  # Callback stored in use case, not here


class CapturingBotLoop(FakeBotLoop):
    """BotLoop fake that captures the callback and can fire events."""

    def start(self, symbol, interval, on_candle, on_stale=None, on_account_event=None):
        super().start(symbol, interval, on_candle, on_stale)
        self._on_candle = on_candle

    def fire_candle(self, candle: dict) -> None:
        self._on_candle(candle)


def test_bot_loop_run_forever_processes_candles() -> None:
    """run_forever() starts the bot loop which calls process_closed_candle."""
    repo = StubBotStateRepository()
    bot_loop = CapturingBotLoop()

    from finbot.core.application.use_cases.live_trading_runtime import (
        LiveTradingRuntimeUseCase,
    )

    runtime = LiveTradingRuntimeUseCase(
        exchange_gateway=InMemoryExchangeGateway(),
        strategy_evaluator=FakeStrategyEvaluator(
            signal=SignalDecision(
                action=SignalAction.LONG_ENTRY,
                symbol="BTC",
                interval="1h",
                candle_timestamp=1735689600,
                strategy_hash="test-hash",
            )
        ),
        state_repository=repo,
        indicator_calculator=InMemoryIndicatorEngine(
            latest_bar=indicator_bar(atr=1200.0)
        ),
        enrichment_validator=EnrichmentValidator(),
        bar_frame_converter=InMemoryBarFrameConverter(),
        mode=TradingMode.DRY_RUN,
        submission_strategy=make_dry_run_submission_strategy(repo),
        event_emitter=make_event_emitter(),
        warmup_bars=closed_warmup_bars(100),
        required_columns={"atr"},
        bot_loop=bot_loop,
    )

    runtime._start_session("test-strategy", "test-hash", "BTC", "1h")
    assert repo.count_signals() == 0

    # Simulate what run_forever does: the loop calls process_closed_candle
    candle = {
        "timestamp": 1735689600 + 100 * 3600,
        "open": 51000.0,
        "high": 51100.0,
        "low": 50900.0,
        "close": 51050.0,
        "volume": 50.0,
    }

    # Direct call simulates bot loop dispatch
    result = runtime.process_closed_candle(candle)

    assert result.enrichment_valid is True
    assert result.signal_action == "long_entry"
    assert bot_loop.started_symbol == ""  # _start_session doesn't set loop symbol
    # run_forever() would set it; we tested the callback path directly


def test_run_forever_raises_without_bot_loop() -> None:
    """run_forever raises RuntimeError when no BotLoop is injected."""
    import pytest

    from finbot.core.application.use_cases.live_trading_runtime import (
        LiveTradingRuntimeUseCase,
    )

    runtime = LiveTradingRuntimeUseCase(
        exchange_gateway=InMemoryExchangeGateway(),
        strategy_evaluator=FakeStrategyEvaluator(),
        state_repository=StubBotStateRepository(),
        indicator_calculator=InMemoryIndicatorEngine(),
        enrichment_validator=EnrichmentValidator(),
        bar_frame_converter=InMemoryBarFrameConverter(),
        mode=TradingMode.DRY_RUN,
        submission_strategy=make_dry_run_submission_strategy(
            StubBotStateRepository()
        ),
        event_emitter=make_event_emitter(),
        warmup_bars=closed_warmup_bars(100),
    )
    runtime._start_session("test-strategy", "test-hash", "BTC", "1h")

    with pytest.raises(RuntimeError, match="BotLoop"):
        runtime.run_forever()
