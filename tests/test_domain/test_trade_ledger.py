"""Tests for TradeLedger — the fill-to-Trade accountant (Scenarios S1–S3, S6, S9).

Classical school: uses real TradeLedger against InMemoryBotStateRepository.
No mocks of domain objects.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from finbot.core.domain.entities.fill_record import FillRecord
from finbot.core.domain.services.trade_ledger import TradeLedger
from finbot.infrastructure.repositories.in_memory_bot_state_repository import (
    InMemoryBotStateRepository,
)


# -- helpers ---------------------------------------------------------------

def _now() -> datetime:
    return datetime.now(UTC)


def _buy(*, size: str, price: str, fee: str = "0", symbol: str = "BTC", **kw) -> FillRecord:
    return FillRecord(
        bot_run_id=kw.get("bot_run_id", "run1"),
        order_id=kw.get("order_id", "oid1"),
        symbol=symbol,
        side="buy",
        size=Decimal(size),
        price=Decimal(price),
        fee=Decimal(fee),
        fill_id=kw.get("fill_id", uuid4().hex),
        filled_at=kw.get("filled_at", _now()),
    )


def _sell(*, size: str, price: str, fee: str = "0", symbol: str = "BTC", **kw) -> FillRecord:
    return FillRecord(
        bot_run_id=kw.get("bot_run_id", "run1"),
        order_id=kw.get("order_id", "oid1"),
        symbol=symbol,
        side="sell",
        size=Decimal(size),
        price=Decimal(price),
        fee=Decimal(fee),
        fill_id=kw.get("fill_id", uuid4().hex),
        filled_at=kw.get("filled_at", _now()),
    )


def _entry(symbol: str = "BTC", direction: str = "long", **kw) -> FillRecord:
    """Shorthand for entry fill in the given direction."""
    if direction == "long":
        return _buy(symbol=symbol, **kw)
    return _sell(symbol=symbol, **kw)


def _exit(direction: str = "long", **kw) -> FillRecord:
    """Shorthand for exit fill opposing the given direction."""
    if direction == "long":
        return _sell(**kw)
    return _buy(**kw)


# -- Scenario S1: Entry fill opens a Trade ---------------------------------


class TestEntryFillOpensTrade:
    def test_buy_fill_opens_long_trade(self) -> None:
        """S1: buy fill with no open trade → opens LONG."""
        repo = InMemoryBotStateRepository()
        ledger = TradeLedger(repo)

        outcome = ledger.apply_fill(
            _buy(size="0.1", price="50000", fee="0.5", fill_id="f1")
        )

        assert outcome.status == "opened"
        assert outcome.position_id != ""

        trade = repo.get_open_trade("BTC")
        assert trade is not None
        assert trade.side.value == "long"
        assert trade.status == "open"
        assert trade.entry_price == Decimal("50000")
        assert trade.size == Decimal("0.1")

    def test_sell_fill_opens_short_trade(self) -> None:
        """A sell fill with no open trade → opens SHORT."""
        repo = InMemoryBotStateRepository()
        ledger = TradeLedger(repo)

        ledger.apply_fill(
            _sell(size="0.1", price="50000", fill_id="f1")
        )

        trade = repo.get_open_trade("BTC")
        assert trade is not None
        assert trade.side.value == "short"
        assert trade.size == Decimal("0.1")


# -- Scenario S2: Exit fill closes a Trade ---------------------------------


class TestExitFillClosesTrade:
    def test_long_exit_profit(self) -> None:
        """S2: long entry 50000, exit 51000 → closed with realized PnL."""
        repo = InMemoryBotStateRepository()
        ledger = TradeLedger(repo)

        ledger.apply_fill(_buy(size="0.1", price="50000", fee="0.5", fill_id="f1"))
        outcome = ledger.apply_fill(
            _sell(size="0.1", price="51000", fee="0.5", fill_id="f2")
        )

        assert outcome.status == "closed"
        closed = repo.list_closed_trades()
        assert len(closed) == 1
        t = closed[0]
        assert t.status == "closed"
        assert t.close_price == Decimal("51000")
        # (51000-50000)*0.1 - 0.5 = 99.5 (exit fee only)
        assert t.realized_pnl == Decimal("99.5")
        assert repo.get_open_trade("BTC") is None

    def test_short_exit_profit(self) -> None:
        """Short entry (sell) 50000, exit (buy) 49000 → profit."""
        repo = InMemoryBotStateRepository()
        ledger = TradeLedger(repo)

        ledger.apply_fill(_sell(size="1", price="50000", fill_id="f1"))
        ledger.apply_fill(_buy(size="1", price="49000", fill_id="f2"))

        closed = repo.list_closed_trades()
        assert len(closed) == 1
        assert closed[0].realized_pnl > Decimal("0")

    def test_long_exit_loss(self) -> None:
        """S4: long entry 50000, exit 49000 → negative realized PnL."""
        repo = InMemoryBotStateRepository()
        ledger = TradeLedger(repo)

        ledger.apply_fill(_buy(size="1", price="50000", fill_id="f1"))
        ledger.apply_fill(_sell(size="1", price="49000", fill_id="f2"))

        closed = repo.list_closed_trades()
        assert len(closed) == 1
        assert closed[0].realized_pnl < Decimal("0")


# -- Scenario S3: Partial fills --------------------------------------------


class TestPartialFills:
    def test_two_entries_accumulate(self) -> None:
        """Two buy fills → one Trade with accumulated size and weighted avg price."""
        repo = InMemoryBotStateRepository()
        ledger = TradeLedger(repo)

        ledger.apply_fill(_buy(size="0.05", price="50000", fill_id="f1"))
        ledger.apply_fill(_buy(size="0.05", price="52000", fill_id="f2"))

        t = repo.get_open_trade("BTC")
        assert t is not None
        assert t.size == Decimal("0.10")
        # Weighted avg: (0.05*50000 + 0.05*52000) / 0.10 = 51000
        assert t.entry_price == Decimal("51000")

    def test_partial_exit_keeps_trade_open(self) -> None:
        """Partial exit reduces size, stays open, accrues partial PnL."""
        repo = InMemoryBotStateRepository()
        ledger = TradeLedger(repo)

        ledger.apply_fill(_buy(size="0.1", price="50000", fill_id="f1"))
        outcome = ledger.apply_fill(
            _sell(size="0.04", price="53000", fee="0.2", fill_id="f2")
        )

        assert outcome.status == "partial"
        t = repo.get_open_trade("BTC")
        assert t is not None
        assert t.status == "open"
        assert t.size == Decimal("0.06")
        assert t.realized_pnl > Decimal("0")  # accrued

    def test_final_exit_closes_after_partial(self) -> None:
        """The last exit closes a partially-closed Trade."""
        repo = InMemoryBotStateRepository()
        ledger = TradeLedger(repo)

        ledger.apply_fill(_buy(size="0.1", price="50000", fill_id="f1"))
        ledger.apply_fill(_sell(size="0.04", price="53000", fill_id="f2"))
        outcome = ledger.apply_fill(
            _sell(size="0.06", price="53000", fill_id="f3")
        )

        assert outcome.status == "closed"
        assert repo.get_open_trade("BTC") is None
        closed = repo.list_closed_trades()
        assert len(closed) == 1
        assert closed[0].size == Decimal("0")


# -- Scenario S9: Fill idempotency -----------------------------------------


class TestFillIdempotency:
    def test_duplicate_fill_id_skipped(self) -> None:
        """S9: Applying the same fill_id twice → duplicate, not double-counted."""
        repo = InMemoryBotStateRepository()
        ledger = TradeLedger(repo)

        fill = _buy(size="0.1", price="50000", fill_id="f1")
        ledger.apply_fill(fill)
        outcome = ledger.apply_fill(fill)

        assert outcome.status == "duplicate"
        trades = repo.list_open_trades()
        assert len(trades) == 1
        assert trades[0].size == Decimal("0.1")

    def test_replayed_exit_not_double_realized(self) -> None:
        """Replaying an exit fill doesn't double-count realized PnL."""
        repo = InMemoryBotStateRepository()
        ledger = TradeLedger(repo)

        ledger.apply_fill(_buy(size="0.1", price="50000", fill_id="f1"))
        exit_fill = _sell(size="0.1", price="51000", fill_id="f2")
        ledger.apply_fill(exit_fill)

        first_realized = repo.list_closed_trades()[0].realized_pnl
        ledger.apply_fill(exit_fill)  # replay

        assert repo.list_closed_trades()[0].realized_pnl == first_realized


# -- Scenario S6: realized_loss_on -----------------------------------------


class TestRealizedLossOn:
    def test_sums_todays_losses_only(self) -> None:
        """S6: Only losses closed today count toward daily loss."""
        repo = InMemoryBotStateRepository()
        ledger = TradeLedger(repo)

        today = _now().date()
        # Closed today at a loss
        ledger.apply_fill(
            _buy(size="1", price="50000", fee="1", fill_id="f1",
                 filled_at=_now())
        )
        ledger.apply_fill(
            _sell(size="1", price="49000", fee="1", fill_id="f2",
                  filled_at=_now())
        )

        loss_today = ledger.realized_loss_on(today)
        # (49000-50000)*1 - 1 = -1001 → abs = 1001
        assert loss_today > Decimal("0")
        assert loss_today == Decimal("1001")

    def test_excludes_yesterday(self) -> None:
        """S6: Losses from previous days are excluded."""
        repo = InMemoryBotStateRepository()
        ledger = TradeLedger(repo)

        yesterday = _now() - timedelta(days=1)
        today = _now().date()

        ledger.apply_fill(
            _buy(size="1", price="50000", fill_id="f1",
                 filled_at=yesterday)
        )
        ledger.apply_fill(
            _sell(size="1", price="49000", fill_id="f2",
                  filled_at=yesterday)
        )

        loss_today = ledger.realized_loss_on(today)
        assert loss_today == Decimal("0")

    def test_positive_pnl_contributes_zero(self) -> None:
        """Profitable trades contribute 0 to loss (not negative offset)."""
        repo = InMemoryBotStateRepository()
        ledger = TradeLedger(repo)

        ledger.apply_fill(_buy(size="1", price="50000", fill_id="f1",
                               filled_at=_now()))
        ledger.apply_fill(_sell(size="1", price="51000", fill_id="f2",
                                filled_at=_now()))

        loss = ledger.realized_loss_on(_now().date())
        assert loss == Decimal("0")  # profit doesn't offset losses


# -- Edge cases ------------------------------------------------------------


class TestLedgerEdgeCases:
    def test_no_trades_returns_zero_loss(self) -> None:
        repo = InMemoryBotStateRepository()
        ledger = TradeLedger(repo)
        assert ledger.realized_loss_on(_now().date()) == Decimal("0")

    def test_open_trade_for_returns_none_when_no_trade(self) -> None:
        repo = InMemoryBotStateRepository()
        ledger = TradeLedger(repo)
        assert ledger.open_trade_for("BTC") is None

    def test_open_trade_for_returns_open_trade(self) -> None:
        repo = InMemoryBotStateRepository()
        ledger = TradeLedger(repo)
        ledger.apply_fill(_buy(size="0.1", price="50000", fill_id="f1"))
        t = ledger.open_trade_for("BTC")
        assert t is not None
        assert t.symbol == "BTC"
        assert t.status == "open"
