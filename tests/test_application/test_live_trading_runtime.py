"""Tests for LiveTradingRuntimeUseCase — Scenario 4: enrichment validation gate."""

from decimal import Decimal

import pytest

from finbot.core.domain.dto.candle_processing_result import CandleProcessingResult
from finbot.core.domain.entities.position_direction import PositionDirection
from finbot.core.domain.entities.position_snapshot import PositionSnapshot
from finbot.core.domain.entities.signal_action import SignalAction
from finbot.core.domain.entities.signal_decision import SignalDecision
from finbot.core.domain.entities.trading_mode import TradingMode
from finbot.core.domain.interfaces.bot_state_repository import BotStateRepository
from finbot.core.domain.interfaces.exchange_gateway import ExchangeGateway
from finbot.core.domain.interfaces.indicator_calculator import (
    IndicatorCalculator,
)
from finbot.core.domain.interfaces.market_data_stream import MarketDataStream
from finbot.core.domain.interfaces.strategy_evaluator import StrategyEvaluator
from finbot.core.domain.services.enrichment_validator import EnrichmentValidator


# ---------------------------------------------------------------------------
# Test fakes
# ---------------------------------------------------------------------------


class FakeMarketDataStream(MarketDataStream):
    """Market data stream fake for tests — emits closed candles on demand."""

    def __init__(self) -> None:
        self._callback: object = None
        self._subscription_count: int = 0

    def subscribe_candles(self, symbol: str, interval: str, callback: object) -> int:
        self._callback = callback
        self._subscription_count += 1
        return self._subscription_count

    def stop(self) -> None:
        self._callback = None

    def emit_closed_candle(self, candle: dict) -> None:
        if self._callback is not None:
            self._callback(candle)  # type: ignore[misc]

    @property
    def subscription_count(self) -> int:
        return self._subscription_count


class InMemoryExchangeGateway(ExchangeGateway):
    """Exchange fake for tests — tracks submissions without I/O."""

    def __init__(self) -> None:
        self.submitted_order_count: int = 0
        self._position: PositionSnapshot = PositionSnapshot(
            symbol="DEFAULT", direction=PositionDirection.FLAT, size=Decimal("0")
        )

    def get_position(self, symbol: str) -> PositionSnapshot:
        return self._position

    def list_open_orders(self, symbol: str) -> list[dict]:
        return []

    def submit_order(self, intent) -> dict:
        self.submitted_order_count += 1
        return {"status": "fake_submitted"}

    def cancel_all(self, symbol: str) -> dict:
        return {"status": "fake_cancelled"}

    def cancel_by_cloid(self, symbol: str, cloid: str) -> dict:
        return {"status": "fake_cancelled"}


class InMemoryIndicatorEngine(IndicatorCalculator):
    """Indicator calculator fake — returns a pre-configured latest bar."""

    def __init__(self, latest_bar: dict | None = None) -> None:
        self._latest_bar = latest_bar or {}

    def calculate(self, df, indicators: list[str]):
        """Return the pre-configured latest bar wrapped as needed."""
        return type(df)([self._latest_bar])


class FakeStrategyEvaluator(StrategyEvaluator):
    """Strategy evaluator fake — returns a pre-configured signal."""

    def __init__(
        self,
        signal: SignalDecision | None = None,
    ) -> None:
        self._signal = signal or SignalDecision(
            action=SignalAction.HOLD,
            symbol="BTC",
            interval="1h",
            candle_timestamp=0,
            strategy_hash="test-hash",
        )
        self.evaluate_calls: list[dict] = []

    def evaluate(self, enriched_bar: dict, position: PositionSnapshot) -> SignalDecision:
        self.evaluate_calls.append({"bar": enriched_bar, "position": position})
        return SignalDecision(
            action=self._signal.action,
            symbol=self._signal.symbol,
            interval=self._signal.interval,
            candle_timestamp=enriched_bar.get("timestamp", 0),
            strategy_hash=self._signal.strategy_hash,
            confidence=self._signal.confidence,
            stop_price=self._signal.stop_price,
            target_price=self._signal.target_price,
        )


class StubBotStateRepository(BotStateRepository):
    """Minimal state repository stub for enrichment-only tests."""

    def __init__(self) -> None:
        self._bot_runs: list = []
        self._processed: set[str] = set()
        self._processed_signals: list = []
        self._risk_events: list = []
        self._audit_entries: list = []
        self._intents: list = []

    def create_bot_run(self, bot_run) -> None:
        self._bot_runs.append(bot_run)

    def end_bot_run(self, run_id: str) -> None:
        pass

    def store_strategy_snapshot(self, snapshot) -> None:
        pass

    def has_processed_signal(self, signal_key: str) -> bool:
        return signal_key in self._processed

    def mark_signal_processed(self, signal) -> None:
        self._processed.add(signal.signal_key)
        self._processed_signals.append(signal)

    def record_order_intent(self, intent) -> str:
        self._intents.append(intent)
        return "test-intent-1"

    def record_order_response(self, response) -> None:
        pass

    def record_fill(self, fill) -> None:
        pass

    def record_reconciliation(self, rec) -> None:
        pass

    def record_risk_event(self, event) -> None:
        self._risk_events.append(event)

    def append_audit_log(self, entry) -> None:
        self._audit_entries.append(entry)

    def get_latest_bot_run(self):
        return self._bot_runs[-1] if self._bot_runs else None

    def get_last_signal(self):
        return self._processed_signals[-1] if self._processed_signals else None

    def get_last_order_response(self):
        return None

    def count_signals(self) -> int:
        return len(self._processed)

    def count_orders(self) -> int:
        return len(self._intents)

    def count_fills(self) -> int:
        return 0

    @property
    def signal_count(self) -> int:
        return len(self._processed)

    @property
    def order_intent_count(self) -> int:
        return len(self._intents)

    @property
    def last_risk_event(self):
        return self._risk_events[-1] if self._risk_events else None

    def last_audit_event(self):
        return self._audit_entries[-1] if self._audit_entries else None


# ---------------------------------------------------------------------------
# Scenario 4: Invalid enriched candle is blocked before strategy evaluation
# ---------------------------------------------------------------------------


def _closed_warmup_bars(count: int = 100) -> list[dict]:
    """Generate synthetic closed warmup bars."""
    base_ts = 1735689600
    return [
        {
            "timestamp": base_ts + i * 3600,
            "open": 50000.0 + i * 10,
            "high": 50200.0 + i * 10,
            "low": 49800.0 + i * 10,
            "close": 50100.0 + i * 10,
            "volume": 100.0,
        }
        for i in range(count)
    ]


def test_invalid_enriched_candle_blocked_before_evaluation() -> None:
    """Scenario 4: missing/non-finite enriched columns block strategy evaluation."""
    from finbot.core.application.use_cases.live_trading_runtime import (
        LiveTradingRuntimeUseCase,
    )

    repo = StubBotStateRepository()
    fake_exchange = InMemoryExchangeGateway()
    fake_indicator_engine = InMemoryIndicatorEngine(
        latest_bar={
            "timestamp": 1735689600,
            "open": 50000.0,
            "high": 51000.0,
            "low": 49000.0,
            "close": 50500.0,
            "atr": float("nan"),
            # vp_vah intentionally missing — the strategy requires it
        }
    )
    fake_evaluator = FakeStrategyEvaluator(
        signal=SignalDecision(
            action=SignalAction.LONG_ENTRY,
            symbol="BTC",
            interval="1h",
            candle_timestamp=0,
            strategy_hash="test-hash",
        )
    )

    runtime = LiveTradingRuntimeUseCase(
        exchange_gateway=fake_exchange,
        market_data_stream=FakeMarketDataStream(),
        strategy_evaluator=fake_evaluator,
        state_repository=repo,
        indicator_calculator=fake_indicator_engine,
        enrichment_validator=EnrichmentValidator(),
        mode=TradingMode.DRY_RUN,
        warmup_bars=_closed_warmup_bars(100),
        required_columns={"atr", "vp_vah"},
    )
    runtime._start_session("test-strategy", "test-hash", "BTC", "1h")

    new_candle = {
        "timestamp": 1735689600 + 100 * 3600,
        "open": 51000.0,
        "high": 51100.0,
        "low": 50900.0,
        "close": 51050.0,
        "volume": 50.0,
    }

    result = runtime.process_closed_candle(new_candle)

    assert result.enrichment_valid is False
    assert "atr" in result.enrichment_errors
    assert "vp_vah" in result.enrichment_errors
    assert repo.signal_count == 0
    assert repo.order_intent_count == 0
    assert fake_exchange.submitted_order_count == 0
    assert len(fake_evaluator.evaluate_calls) == 0


def test_optional_nan_does_not_block_evaluation() -> None:
    """Optional/non-required NaN column does not block evaluation."""
    from finbot.core.application.use_cases.live_trading_runtime import (
        LiveTradingRuntimeUseCase,
    )

    repo = StubBotStateRepository()
    fake_exchange = InMemoryExchangeGateway()
    fake_indicator_engine = InMemoryIndicatorEngine(
        latest_bar={
            "timestamp": 1735689600,
            "open": 50000.0,
            "high": 51000.0,
            "low": 49000.0,
            "close": 50500.0,
            "atr": 1200.0,
            "vp_vah": 52000.0,
            "rsi_14": float("nan"),  # optional — not in required set
        }
    )
    fake_evaluator = FakeStrategyEvaluator(
        signal=SignalDecision(
            action=SignalAction.HOLD,
            symbol="BTC",
            interval="1h",
            candle_timestamp=0,
            strategy_hash="test-hash",
        )
    )

    runtime = LiveTradingRuntimeUseCase(
        exchange_gateway=fake_exchange,
        market_data_stream=FakeMarketDataStream(),
        strategy_evaluator=fake_evaluator,
        state_repository=repo,
        indicator_calculator=fake_indicator_engine,
        enrichment_validator=EnrichmentValidator(),
        mode=TradingMode.DRY_RUN,
        warmup_bars=_closed_warmup_bars(100),
        required_columns={"atr", "vp_vah"},
    )
    runtime._start_session("test-strategy", "test-hash", "BTC", "1h")

    new_candle = {
        "timestamp": 1735689600 + 100 * 3600,
        "open": 51000.0,
        "high": 51100.0,
        "low": 50900.0,
        "close": 51050.0,
        "volume": 50.0,
    }

    result = runtime.process_closed_candle(new_candle)

    assert result.enrichment_valid is True
    assert result.enrichment_errors == []


def test_validation_rejection_persisted_as_risk_event() -> None:
    """Validation rejection is persisted as an audit/risk event with timestamp."""
    from finbot.core.application.use_cases.live_trading_runtime import (
        LiveTradingRuntimeUseCase,
    )

    repo = StubBotStateRepository()
    fake_exchange = InMemoryExchangeGateway()
    fake_indicator_engine = InMemoryIndicatorEngine(
        latest_bar={
            "timestamp": 1735689600,
            "open": 50000.0,
            "high": 51000.0,
            "low": 49000.0,
            "close": 50500.0,
            "atr": None,
            "vp_vah": float("inf"),
        }
    )
    fake_evaluator = FakeStrategyEvaluator()

    runtime = LiveTradingRuntimeUseCase(
        exchange_gateway=fake_exchange,
        market_data_stream=FakeMarketDataStream(),
        strategy_evaluator=fake_evaluator,
        state_repository=repo,
        indicator_calculator=fake_indicator_engine,
        enrichment_validator=EnrichmentValidator(),
        mode=TradingMode.DRY_RUN,
        warmup_bars=_closed_warmup_bars(100),
        required_columns={"atr", "vp_vah"},
    )
    runtime._start_session("test-strategy", "test-hash", "BTC", "1h")

    new_candle = {
        "timestamp": 1735689600 + 100 * 3600,
        "open": 51000.0,
        "high": 51100.0,
        "low": 50900.0,
        "close": 51050.0,
        "volume": 50.0,
    }

    result = runtime.process_closed_candle(new_candle)

    assert result.enrichment_valid is False
    risk_event = repo.last_risk_event
    assert risk_event is not None
    assert "enrichment" in risk_event.event_type.lower()
    assert risk_event.decision == "rejected"
