"""Tests for Phase 11.5 — observability and audit event standard."""

from finbot.core.application.dto.signal_event import SignalEvent
from finbot.core.domain.entities.order_intent import OrderIntent
from finbot.core.domain.entities.order_side import OrderSide
from finbot.core.domain.entities.order_type import OrderType
from finbot.core.domain.entities.signal_action import SignalAction


class TestSignalEventCorrelationFields:
    def test_signal_event_contains_correlation_fields(self) -> None:
        sig = SignalEvent(
            action=SignalAction.LONG_ENTRY,
            symbol="BTC",
            strategy_name="amt_dip",
            strategy_hash="abc123",
            bot_run_id="run1",
            interval="1h",
            candle_timestamp="2025-01-01T09:00:00",
            signal_key="BTC::1h::1735686000::amt_dip::long_entry",
            mode="dry_run",
        )
        assert sig.bot_run_id == "run1"
        assert sig.strategy_name == "amt_dip"
        assert sig.strategy_hash == "abc123"
        assert sig.interval == "1h"
        assert sig.mode == "dry_run"
        assert sig.signal_key != ""
        assert sig.candle_timestamp == "2025-01-01T09:00:00"

    def test_signal_event_defaults_are_empty_strings(self) -> None:
        sig = SignalEvent(action=SignalAction.HOLD)
        assert sig.bot_run_id == ""
        assert sig.strategy_name == ""
        assert sig.signal_key == ""


class TestOrderIntentCloid:
    def test_order_intent_accepts_cloid(self) -> None:
        intent = OrderIntent(
            symbol="BTC",
            side=OrderSide.BUY,
            size=1,
            order_type=OrderType.LIMIT,
            cloid="custom-cloid-123",
        )
        assert intent.cloid == "custom-cloid-123"

    def test_order_intent_cloid_defaults_to_none(self) -> None:
        intent = OrderIntent(
            symbol="BTC",
            side=OrderSide.BUY,
            size=1,
            order_type=OrderType.LIMIT,
        )
        assert intent.cloid is None
