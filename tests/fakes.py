"""Shared test fakes for live trading runtime tests.

Classical-school fakes: in-memory implementations with no mocks,
suitable for outcome-based assertions.
"""

from decimal import Decimal
from typing import Any

from finbot.core.domain.entities.position_direction import PositionDirection
from finbot.core.domain.entities.position_snapshot import PositionSnapshot
from finbot.core.domain.entities.signal_action import SignalAction
from finbot.core.domain.entities.signal_decision import SignalDecision
from finbot.core.domain.interfaces.bar_frame_converter import (
    BarFrameConverter,
)
from finbot.core.domain.interfaces.bot_state_repository import (
    BotStateRepository,
)
from finbot.core.domain.interfaces.exchange_gateway import ExchangeGateway
from finbot.core.domain.interfaces.indicator_calculator import (
    IndicatorCalculator,
)
from finbot.core.domain.interfaces.market_data_stream import MarketDataStream
from finbot.core.domain.interfaces.strategy_evaluator import (
    StrategyEvaluator,
)


# ---------------------------------------------------------------------------
# Market data stream fake
# ---------------------------------------------------------------------------


class FakeMarketDataStream(MarketDataStream):
    """Market data stream fake — emits closed candles on demand."""

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


# ---------------------------------------------------------------------------
# Exchange gateway fake
# ---------------------------------------------------------------------------


class InMemoryExchangeGateway(ExchangeGateway):
    """Exchange fake — tracks submissions without I/O."""

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


# ---------------------------------------------------------------------------
# Indicator calculator fake
# ---------------------------------------------------------------------------


class InMemoryIndicatorEngine(IndicatorCalculator):
    """Indicator calculator fake — returns a pre-configured latest bar."""

    def __init__(self, latest_bar: dict | None = None) -> None:
        self._latest_bar = latest_bar or {}

    def calculate(self, df, indicators: list[str]):
        """Return the pre-configured latest bar, preserving DataFrame type."""
        import pandas as pd

        if isinstance(df, pd.DataFrame) and self._latest_bar:
            return pd.DataFrame([self._latest_bar])
        return type(df)([self._latest_bar])


# ---------------------------------------------------------------------------
# Bar frame converter fake
# ---------------------------------------------------------------------------


class InMemoryBarFrameConverter(BarFrameConverter):
    """Bar frame converter fake — converts dict bars to/from list form."""

    def bars_to_frame(self, bars: list[dict]) -> Any:
        import pandas as pd
        return pd.DataFrame(bars)

    def frame_to_bars(self, frame) -> list[dict]:
        return frame.to_dict(orient="records")


# ---------------------------------------------------------------------------
# Strategy evaluator fake
# ---------------------------------------------------------------------------


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

    def evaluate(
        self, enriched_bar: dict, position: PositionSnapshot
    ) -> SignalDecision:
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


# ---------------------------------------------------------------------------
# Bot state repository stub
# ---------------------------------------------------------------------------


class StubBotStateRepository(BotStateRepository):
    """Minimal state repository stub — tracks state without persistence."""

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
