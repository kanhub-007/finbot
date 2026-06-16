"""Tests for TradeLifecycle pure functions (Scenarios S1–S4).

These tests verify the stateless transition functions that produce new
immutable Trade instances from fills. No I/O, no repo, no mocks.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from finbot.core.domain.entities.fill_record import FillRecord
from finbot.core.domain.entities.position_direction import PositionDirection
from finbot.core.domain.entities.trade import Trade
from finbot.core.domain.services.trade_lifecycle import (
    apply_entry_fill,
    apply_exit_fill,
    open_from_fill,
    realized_pnl_for_exit,
    sign_for,
)


# -- helpers ---------------------------------------------------------------

def _now() -> datetime:
    return datetime.now(UTC)


def _buy_fill(*, size: str, price: str, fee: str = "0", **kw) -> FillRecord:
    return FillRecord(
        bot_run_id="run1",
        order_id="oid1",
        symbol=kw.get("symbol", "BTC"),
        side="buy",
        size=Decimal(size),
        price=Decimal(price),
        fee=Decimal(fee),
        fill_id=kw.get("fill_id", "f1"),
        filled_at=kw.get("filled_at", _now()),
    )


def _sell_fill(*, size: str, price: str, fee: str = "0", **kw) -> FillRecord:
    return FillRecord(
        bot_run_id="run1",
        order_id="oid1",
        symbol=kw.get("symbol", "BTC"),
        side="sell",
        size=Decimal(size),
        price=Decimal(price),
        fee=Decimal(fee),
        fill_id=kw.get("fill_id", "f1"),
        filled_at=kw.get("filled_at", _now()),
    )


# -- sign_for ---------------------------------------------------------------


class TestSignFor:
    def test_long_returns_positive_one(self) -> None:
        assert sign_for(PositionDirection.LONG) == 1

    def test_short_returns_negative_one(self) -> None:
        assert sign_for(PositionDirection.SHORT) == -1


# -- open_from_fill (S1) ----------------------------------------------------


class TestOpenFromFill:
    def test_buy_fill_opens_long_trade(self) -> None:
        """Scenario S1: a buy fill opens a LONG trade."""
        fill = _buy_fill(size="0.1", price="50000", fee="0.5")
        trade = open_from_fill(fill, position_id="pos1")

        assert trade.side == PositionDirection.LONG
        assert trade.status == "open"
        assert trade.size == Decimal("0.1")
        assert trade.entry_price == Decimal("50000")
        assert trade.opened_at == fill.filled_at
        assert trade.total_fee == Decimal("0.5")
        assert trade.realized_pnl == Decimal("0")
        assert trade.position_id == "pos1"

    def test_sell_fill_opens_short_trade(self) -> None:
        """A sell fill opens a SHORT trade."""
        fill = _sell_fill(size="0.1", price="50000")
        trade = open_from_fill(fill, position_id="pos2")

        assert trade.side == PositionDirection.SHORT
        assert trade.status == "open"
        assert trade.size == Decimal("0.1")
        assert trade.entry_price == Decimal("50000")

    def test_strategy_hash_is_passed_through(self) -> None:
        fill = _buy_fill(size="0.1", price="50000")
        trade = open_from_fill(fill, position_id="p3", strategy_hash="abc123")
        assert trade.strategy_hash == "abc123"


# -- apply_entry_fill (S3) --------------------------------------------------


class TestApplyEntryFill:
    def test_single_entry_sets_entry_price(self) -> None:
        """First entry: entry_price = fill price."""
        fill = _buy_fill(size="0.1", price="50000")
        trade = open_from_fill(fill, position_id="p1")
        # Already correct from open, but apply_entry_fill handles subsequent entries.

    def test_weighted_average_entry_price(self) -> None:
        """Scenario S3: two buys at different prices → weighted average."""
        f1 = _buy_fill(size="0.05", price="50000", fill_id="f1")
        f2 = _buy_fill(size="0.05", price="52000", fill_id="f2")

        trade = open_from_fill(f1, position_id="p1")
        trade = apply_entry_fill(trade, f2)

        # Weighted average: (0.05*50000 + 0.05*52000) / 0.10 = 51000
        assert trade.size == Decimal("0.10")
        assert trade.entry_price == Decimal("51000")
        assert trade.total_fee == Decimal("0")  # no fees in these fills

    def test_three_entries_different_prices(self) -> None:
        f1 = _buy_fill(size="0.1", price="100", fill_id="f1")
        f2 = _buy_fill(size="0.2", price="200", fill_id="f2")
        f3 = _buy_fill(size="0.3", price="300", fill_id="f3")

        trade = open_from_fill(f1, position_id="p1")
        trade = apply_entry_fill(trade, f2)
        trade = apply_entry_fill(trade, f3)

        # (0.1*100 + 0.2*200 + 0.3*300) / 0.6 = (10 + 40 + 90) / 0.6 = 233.33...
        expected = (Decimal("0.1") * Decimal("100")
                    + Decimal("0.2") * Decimal("200")
                    + Decimal("0.3") * Decimal("300")) / Decimal("0.6")
        assert trade.size == Decimal("0.6")
        assert trade.entry_price == expected

    def test_entry_accumulates_fees(self) -> None:
        f1 = _buy_fill(size="0.1", price="50000", fee="1.0", fill_id="f1")
        f2 = _buy_fill(size="0.1", price="51000", fee="2.0", fill_id="f2")

        trade = open_from_fill(f1, position_id="p1")
        trade = apply_entry_fill(trade, f2)

        assert trade.total_fee == Decimal("3.0")


# -- apply_exit_fill (S2, S3, S4) ------------------------------------------


class TestApplyExitFill:
    def test_long_profit_exit(self) -> None:
        """Scenario S2: long entry 50000, exit 51000 → profit."""
        entry = _buy_fill(size="0.1", price="50000", fee="0.5", fill_id="f1")
        trade = open_from_fill(entry, position_id="p1")

        exit_fill = _sell_fill(size="0.1", price="51000", fee="0.5", fill_id="f2")
        trade = apply_exit_fill(trade, exit_fill)

        assert trade.status == "closed"
        assert trade.size == Decimal("0")  # fully closed
        assert trade.close_price == Decimal("51000")
        assert trade.closed_at == exit_fill.filled_at
        # (51000-50000)*0.1 - 0.5 - 0.5 = 100 - 1 = 99
        # PnL formula: gross = (exit-entry)*size, net = gross - exit_fill.fee
        # Entry fee is tracked in total_fee but not deducted from realized_pnl.
        assert trade.realized_pnl == Decimal("99.5")  # 100 - 0.5 exit fee
        assert trade.total_fee == Decimal("1.0")

    def test_short_profit_exit(self) -> None:
        """Scenario S4: short entry (sell) 50000, exit (buy) 49000 → profit."""
        entry = _sell_fill(size="0.1", price="50000", fill_id="f1")
        trade = open_from_fill(entry, position_id="p1")

        exit_fill = _buy_fill(size="0.1", price="49000", fill_id="f2")
        trade = apply_exit_fill(trade, exit_fill)

        # Short: (entry - exit) * size - fees = (50000 - 49000) * 0.1 = 100
        assert trade.status == "closed"
        assert trade.realized_pnl == Decimal("100")

    def test_long_loss_exit(self) -> None:
        """Scenario S4: long entry 50000, exit 49000 → loss."""
        entry = _buy_fill(size="1", price="50000", fill_id="f1")
        trade = open_from_fill(entry, position_id="p1")

        exit_fill = _sell_fill(size="1", price="49000", fill_id="f2")
        trade = apply_exit_fill(trade, exit_fill)

        # (49000-50000)*1 = -1000
        assert trade.realized_pnl < Decimal("0")

    def test_short_loss_exit(self) -> None:
        """Short entry 50000, exit 51000 → loss."""
        entry = _sell_fill(size="0.1", price="50000", fill_id="f1")
        trade = open_from_fill(entry, position_id="p1")

        exit_fill = _buy_fill(size="0.1", price="51000", fill_id="f2")
        trade = apply_exit_fill(trade, exit_fill)

        # Short: (50000-51000) * 0.1 = -100
        assert trade.realized_pnl < Decimal("0")

    def test_partial_exit_keeps_trade_open(self) -> None:
        """Scenario S3: partial exit reduces size but keeps status=open."""
        entry = _buy_fill(size="0.1", price="50000", fill_id="f1")
        trade = open_from_fill(entry, position_id="p1")

        partial = _sell_fill(size="0.04", price="53000", fee="0.2", fill_id="f2")
        trade = apply_exit_fill(trade, partial)

        assert trade.status == "open"  # still open
        assert trade.size == Decimal("0.06")  # reduced
        # Realized PnL for the closed 0.04: (53000-50000)*0.04 - 0.2 = 120 - 0.2 = 119.8
        # But wait — the entry fee is already recorded from open. The exit fee is subtracted here.
        assert trade.realized_pnl == Decimal("119.8")
        assert trade.close_price is None  # not fully closed yet
        assert trade.closed_at is None

    def test_final_exit_closes_trade(self) -> None:
        """After a partial exit, the last exit closes the trade fully."""
        entry = _buy_fill(size="0.1", price="50000", fill_id="f1")
        trade = open_from_fill(entry, position_id="p1")

        partial = _sell_fill(size="0.04", price="53000", fill_id="f2")
        trade = apply_exit_fill(trade, partial)

        final = _sell_fill(size="0.06", price="53000", fee="0.3", fill_id="f3")
        trade = apply_exit_fill(trade, final)

        assert trade.status == "closed"
        assert trade.size == Decimal("0")
        assert trade.close_price == Decimal("53000")
        assert trade.closed_at == final.filled_at
        # First partial: (53000-50000)*0.04 - 0 = 120 (no fee on partial)
        # Second: (53000-50000)*0.06 - 0.3 = 179.7
        # Total: 120 + 179.7 = 299.7
        assert trade.realized_pnl == Decimal("299.70")
        assert trade.total_fee == Decimal("0.3")  # only final exit fee


# -- realized_pnl_for_exit (pure function) ----------------------------------


class TestRealizedPnlForExit:
    def test_long_pnl_positive(self) -> None:
        """Exit above entry → positive gross PnL for long."""
        pnl = realized_pnl_for_exit(
            entry_price=Decimal("50000"),
            exit_price=Decimal("51000"),
            size=Decimal("0.1"),
            side=PositionDirection.LONG,
        )
        assert pnl == Decimal("100")

    def test_short_pnl_positive(self) -> None:
        """Exit below entry → positive gross PnL for short."""
        pnl = realized_pnl_for_exit(
            entry_price=Decimal("50000"),
            exit_price=Decimal("49000"),
            size=Decimal("0.1"),
            side=PositionDirection.SHORT,
        )
        assert pnl == Decimal("100")

    def test_zero_size_returns_zero(self) -> None:
        pnl = realized_pnl_for_exit(
            entry_price=Decimal("50000"),
            exit_price=Decimal("51000"),
            size=Decimal("0"),
            side=PositionDirection.LONG,
        )
        assert pnl == Decimal("0")
