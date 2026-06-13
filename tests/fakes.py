"""Shared test fakes and helpers for live trading runtime tests.

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
from finbot.core.domain.interfaces.market_metadata_provider import (
    MarketMetadataProvider,
)
from finbot.core.domain.interfaces.strategy_evaluator import (
    StrategyEvaluator,
)

# ---------------------------------------------------------------------------
# Shared bar helpers
# ---------------------------------------------------------------------------


def closed_warmup_bars(count: int = 100) -> list[dict]:
    """Generate synthetic closed warmup bars at 1h intervals."""
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


def new_closed_candle(offset: int = 100) -> dict:
    """Build a closed candle at the given hourly offset from base."""
    return {
        "timestamp": 1735689600 + offset * 3600,
        "open": 51000.0,
        "high": 51100.0,
        "low": 50900.0,
        "close": 51050.0,
        "volume": 50.0,
    }


def indicator_bar(**extra) -> dict:
    """Build a minimal enriched bar with defaults, plus optional extras."""
    base = {
        "timestamp": 1735689600,
        "open": 50000.0,
        "high": 51000.0,
        "low": 49000.0,
        "close": 50500.0,
        "volume": 100.0,
    }
    base.update(extra)
    return base


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

    def latest_bar(self, frame) -> dict:
        import pandas as pd

        if isinstance(frame, pd.DataFrame):
            return frame.iloc[-1].to_dict()
        return frame[-1] if isinstance(frame, list) and frame else {}

    def is_empty(self, frame) -> bool:
        import pandas as pd

        if isinstance(frame, pd.DataFrame):
            return frame.empty
        return len(frame) == 0 if hasattr(frame, "__len__") else False


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
        self._intent_map: dict[str, object] = {}
        self._order_responses: list = []
        self._reconciliations: list = []
        self._fills: list = []
        self._fill_ids: set[str] = set()
        self._lifecycles: dict[str, object] = {}
        self._cloid_map: dict[str, str] = {}

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
        intent_id = f"intent-{len(self._intents)}"
        self._intent_map[intent_id] = intent
        return intent_id

    def record_order_response(self, response) -> None:
        self._order_responses.append(response)

    def record_fill(self, fill) -> None:
        if fill.fill_id in self._fill_ids:
            return  # idempotent
        self._fills.append(fill)
        self._fill_ids.add(fill.fill_id)

    def record_reconciliation(self, rec) -> None:
        self._reconciliations.append(rec)

    def record_risk_event(self, event) -> None:
        self._risk_events.append(event)

    def append_audit_log(self, entry) -> None:
        self._audit_entries.append(entry)

    def get_latest_bot_run(self):
        return self._bot_runs[-1] if self._bot_runs else None

    def get_last_signal(self):
        return self._processed_signals[-1] if self._processed_signals else None

    def get_last_order_response(self):
        return self._order_responses[-1] if self._order_responses else None

    def last_order_intent(self):
        return self._intents[-1] if self._intents else None

    def last_reconciliation(self):
        return self._reconciliations[-1] if self._reconciliations else None

    def has_fill(self, fill_id: str) -> bool:
        return fill_id in self._fill_ids

    def get_order_lifecycle(self, order_id: str):
        return self._lifecycles.get(order_id)

    def save_order_lifecycle(self, lifecycle) -> None:
        self._lifecycles[lifecycle.order_id] = lifecycle

    def count_signals(self) -> int:
        return len(self._processed)

    def count_orders(self) -> int:
        return len(self._intents)

    def count_fills(self) -> int:
        return len(self._fills)

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
# Market metadata provider fake
# ---------------------------------------------------------------------------


class InMemoryMarketMetadataProvider(MarketMetadataProvider):
    """Fake market metadata provider with pre-configured symbol info."""

    def __init__(self, metadata: dict | None = None) -> None:
        from finbot.core.domain.entities.market_metadata import MarketMetadata

        self._data: dict[str, MarketMetadata] = metadata or {}

    def get_metadata(self, symbol: str):
        return self._data.get(symbol)

    @classmethod
    def for_btc(cls) -> "InMemoryMarketMetadataProvider":
        from decimal import Decimal

        from finbot.core.domain.entities.market_metadata import MarketMetadata

        return cls(
            {
                "BTC": MarketMetadata(
                    symbol="BTC",
                    sz_decimals=5,
                    price_tick=Decimal("0.1"),
                    min_size=Decimal("0.00001"),
                    max_leverage=50,
                )
            }
        )


# ---------------------------------------------------------------------------
# Exchange gateway fake for testnet
# ---------------------------------------------------------------------------


class FakeExchangeGateway(InMemoryExchangeGateway):
    """Exchange fake for testnet — records submitted intents with responses."""

    def __init__(self) -> None:
        super().__init__()
        self.submitted_intents: list = []
        self.submitted_responses: list[dict] = []

    def submit_order(self, intent) -> dict:
        self.submitted_order_count += 1
        self.submitted_intents.append(intent)
        resp = {
            "status": "ok",
            "symbol": intent.symbol,
            "side": intent.side.value,
            "size": str(intent.size),
            "order_id": f"test-oid-{self.submitted_order_count}",
            "cloid": intent.cloid or "",
        }
        self.submitted_responses.append(resp)
        return resp
