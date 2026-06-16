"""Tests for the Trade domain entity."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from finbot.core.domain.entities.position_direction import PositionDirection
from finbot.core.domain.entities.trade import Trade


def _make_trade(**overrides) -> Trade:
    """Build a Trade with sensible defaults, overridable by kwarg."""
    defaults: dict = {
        "position_id": "p1",
        "bot_run_id": "run1",
        "symbol": "BTC",
        "side": PositionDirection.LONG,
        "size": Decimal("0.1"),
        "entry_price": Decimal("50000"),
        "opened_at": datetime.now(UTC),
    }
    defaults.update(overrides)
    return Trade(**defaults)


class TestTradeDefaults:
    def test_default_status_is_open(self) -> None:
        trade = _make_trade()
        assert trade.status == "open"

    def test_default_realized_pnl_is_zero(self) -> None:
        trade = _make_trade()
        assert trade.realized_pnl == Decimal("0")
        assert trade.total_fee == Decimal("0")

    def test_default_closed_at_and_close_price_are_none(self) -> None:
        trade = _make_trade()
        assert trade.closed_at is None
        assert trade.close_price is None

    def test_default_audit_fields_are_empty(self) -> None:
        trade = _make_trade()
        assert trade.strategy_hash == ""
        assert trade.entry_signal_key == ""


class TestTradeIsFrozen:
    def test_cannot_mutate_status(self) -> None:
        trade = _make_trade()
        with pytest.raises(Exception):  # dataclasses.FrozenInstanceError
            trade.status = "closed"  # type: ignore[misc]

    def test_cannot_mutate_realized_pnl(self) -> None:
        trade = _make_trade()
        with pytest.raises(Exception):
            trade.realized_pnl = Decimal("100")  # type: ignore[misc]


class TestTradeFieldTypes:
    def test_side_is_position_direction_not_flat(self) -> None:
        long_trade = _make_trade(side=PositionDirection.LONG)
        assert long_trade.side == PositionDirection.LONG

        short_trade = _make_trade(side=PositionDirection.SHORT)
        assert short_trade.side == PositionDirection.SHORT

    def test_position_id_is_a_string(self) -> None:
        trade = _make_trade()
        assert isinstance(trade.position_id, str)

    def test_entry_price_can_be_none_for_reconstructed_trades(self) -> None:
        """Reconstructed trades (no fill history) may have entry_price=None."""
        trade = _make_trade(entry_price=None)
        assert trade.entry_price is None
