"""Tests for Trade persistence in SqliteBotStateRepository (Scenario S7)."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from finbot.core.domain.entities.bot_run import BotRun
from finbot.core.domain.entities.position_direction import PositionDirection
from finbot.core.domain.entities.trade import Trade
from finbot.core.domain.services.trade_ledger import TradeLedger
from finbot.infrastructure.repositories.sqlite_bot_state_repository import (
    SqliteBotStateRepository,
)
from finbot.infrastructure.repositories.sqlite_migrator import SqliteMigrator


def _db_path() -> str:
    import uuid

    return f"file:mem{uuid.uuid4().hex}?mode=memory&cache=shared"


@pytest.fixture
def repo():
    db_path = _db_path()
    SqliteMigrator(db_path).migrate()
    r = SqliteBotStateRepository(db_path)
    r.create_bot_run(
        BotRun(
            strategy_name="test",
            strategy_hash="abc",
            symbol="BTC",
            interval="1h",
            mode="dry_run",
            run_id="r1",
        )
    )
    yield r
    r.close()


class TestSqliteTradeRepository:
    """Persist and query Trade records through SQLite."""

    def _make_trade(self, **overrides) -> Trade:
        now = datetime.now(UTC)
        defaults = {
            "position_id": "p1",
            "bot_run_id": "r1",
            "symbol": "BTC",
            "side": PositionDirection.LONG,
            "size": Decimal("0.1"),
            "entry_price": Decimal("50000"),
            "opened_at": now,
            "status": "open",
        }
        defaults.update(overrides)
        return Trade(**defaults)

    def test_open_then_get_open_trade(self, repo) -> None:
        """Round-trip: open a trade, then retrieve it."""
        trade = self._make_trade(position_id="pos1")
        repo.open_trade(trade)

        result = repo.get_open_trade("BTC")
        assert result is not None
        assert result.position_id == "pos1"
        assert result.symbol == "BTC"
        assert result.side == PositionDirection.LONG
        assert result.entry_price == Decimal("50000")
        assert result.size == Decimal("0.1")
        assert result.status == "open"

    def test_update_trade_replaces_row(self, repo) -> None:
        """Update a trade (e.g. accumulate or partial close)."""
        trade = self._make_trade(position_id="pos1")
        repo.open_trade(trade)

        # Simulate partial close
        updated = Trade(
            position_id="pos1",
            bot_run_id="r1",
            symbol="BTC",
            side=PositionDirection.LONG,
            size=Decimal("0.06"),
            entry_price=Decimal("50000"),
            opened_at=trade.opened_at,
            status="open",
            realized_pnl=Decimal("120"),
            total_fee=Decimal("0.2"),
        )
        repo.update_trade(updated)

        result = repo.get_open_trade("BTC")
        assert result is not None
        assert result.size == Decimal("0.06")
        assert result.realized_pnl == Decimal("120")
        assert result.total_fee == Decimal("0.2")

    def test_list_open_trades_excludes_closed(self, repo) -> None:
        """Open trades list excludes closed ones."""
        now = datetime.now(UTC)

        t1 = self._make_trade(position_id="p1", status="open")
        t2 = self._make_trade(
            position_id="p2", symbol="ETH", status="closed",
            realized_pnl=Decimal("-10"), closed_at=now,
            close_price=Decimal("49000"),
        )

        repo.open_trade(t1)
        repo.open_trade(t2)

        open_trades = repo.list_open_trades()
        assert len(open_trades) == 1
        assert open_trades[0].position_id == "p1"

    def test_list_closed_trades_returns_newest_first(self, repo) -> None:
        """Closed trades come back newest-first by closed_at."""
        now = datetime.now(UTC)

        t1 = self._make_trade(
            position_id="p1", status="closed",
            realized_pnl=Decimal("100"), close_price=Decimal("51000"),
            closed_at=now - timedelta(minutes=30),
        )
        t2 = self._make_trade(
            position_id="p2", symbol="ETH", status="closed",
            realized_pnl=Decimal("-50"), close_price=Decimal("2950"),
            closed_at=now,
        )

        repo.open_trade(t1)
        repo.open_trade(t2)

        closed = repo.list_closed_trades()
        assert len(closed) == 2
        assert closed[0].position_id == "p2"  # newest first
        assert closed[1].position_id == "p1"

    def test_list_closed_trades_filtered_by_bot_run(self, repo) -> None:
        """Filter closed trades by bot_run_id."""
        now = datetime.now(UTC)
        repo.create_bot_run(
            BotRun(
                strategy_name="test2",
                strategy_hash="def",
                symbol="ETH",
                interval="1h",
                mode="dry_run",
                run_id="r2",
            )
        )

        t1 = self._make_trade(
            position_id="p1", bot_run_id="r1", status="closed",
            realized_pnl=Decimal("100"), close_price=Decimal("51000"),
            closed_at=now,
        )
        t2 = self._make_trade(
            position_id="p2", bot_run_id="r2", symbol="ETH",
            status="closed", realized_pnl=Decimal("-50"),
            close_price=Decimal("2950"), closed_at=now,
        )

        repo.open_trade(t1)
        repo.open_trade(t2)

        r1_closed = repo.list_closed_trades(bot_run_id="r1")
        assert len(r1_closed) == 1
        assert r1_closed[0].position_id == "p1"

        r2_closed = repo.list_closed_trades(bot_run_id="r2")
        assert len(r2_closed) == 1
        assert r2_closed[0].position_id == "p2"

    def test_realized_loss_on_sums_negative_pnl_for_day(self, repo) -> None:
        """Only negative PnL from closed trades on the given day is summed."""
        now = datetime.now(UTC)
        today = now.date()

        # Losing trade today
        t1 = self._make_trade(
            position_id="p1", status="closed",
            realized_pnl=Decimal("-30"), close_price=Decimal("47000"),
            closed_at=now,
        )
        # Another losing trade today
        t2 = self._make_trade(
            position_id="p2", symbol="ETH", status="closed",
            realized_pnl=Decimal("-20"), close_price=Decimal("2900"),
            closed_at=now,
        )
        # Profitable trade today — excluded from loss sum
        t3 = self._make_trade(
            position_id="p3", symbol="SOL", status="closed",
            realized_pnl=Decimal("40"), close_price=Decimal("110"),
            closed_at=now,
        )

        repo.open_trade(t1)
        repo.open_trade(t2)
        repo.open_trade(t3)

        loss = repo.realized_loss_on(today)
        # abs(-30 + -20) = 50
        assert loss == Decimal("50")

    def test_realized_loss_excludes_other_days(self, repo) -> None:
        """Losses from other days are not counted."""
        now = datetime.now(UTC)
        yesterday = now - timedelta(days=1)

        t_old = self._make_trade(
            position_id="p1", status="closed",
            realized_pnl=Decimal("-100"), close_price=Decimal("49000"),
            closed_at=yesterday,
        )
        repo.open_trade(t_old)

        loss_today = repo.realized_loss_on(now.date())
        assert loss_today == Decimal("0")

    def test_open_trade_visible_across_repo_reopen(self, repo) -> None:
        """S7: open trade survives a repo close/reopen cycle."""
        trade = self._make_trade(position_id="persist1")
        repo.open_trade(trade)

        # Reopen the same DB
        db_path = repo._db_path
        repo.close()

        repo2 = SqliteBotStateRepository(db_path)
        try:
            result = repo2.get_open_trade("BTC")
            assert result is not None
            assert result.position_id == "persist1"
            assert result.symbol == "BTC"
            assert result.entry_price == Decimal("50000")

            closed = repo2.list_closed_trades()
            assert len(closed) >= 0  # at minimum doesn't crash
        finally:
            repo2.close()

    def test_entry_price_null_round_trips(self, repo) -> None:
        """Reconstructed trades with entry_price=None survive round-trip."""
        now = datetime.now(UTC)
        trade = self._make_trade(
            position_id="recon1",
            entry_price=None,  # reconstructed without fill history
            opened_at=now,
        )
        repo.open_trade(trade)

        result = repo.get_open_trade("BTC")
        assert result is not None
        assert result.entry_price is None


class TestSqliteTradeLedgerIntegration:
    """TradeLedger works end-to-end with the SQLite repo."""

    def test_ledger_opens_and_closes_trade(self, repo) -> None:
        """TradeLedger.apply_fill → SQLite repo → queryable trade."""
        from finbot.core.domain.entities.fill_record import FillRecord

        ledger = TradeLedger(repo)
        now = datetime.now(UTC)

        # Entry
        ledger.apply_fill(
            FillRecord(
                bot_run_id="r1",
                order_id="oid1",
                symbol="BTC",
                side="buy",
                size=Decimal("0.1"),
                price=Decimal("50000"),
                fee=Decimal("0.5"),
                fill_id="f-sql-1",
                filled_at=now,
            )
        )

        trade = repo.get_open_trade("BTC")
        assert trade is not None
        assert trade.status == "open"
        assert trade.size == Decimal("0.1")

        # Exit
        ledger.apply_fill(
            FillRecord(
                bot_run_id="r1",
                order_id="oid2",
                symbol="BTC",
                side="sell",
                size=Decimal("0.1"),
                price=Decimal("51000"),
                fee=Decimal("0.5"),
                fill_id="f-sql-2",
                filled_at=now,
            )
        )

        assert repo.get_open_trade("BTC") is None
        closed = repo.list_closed_trades()
        assert len(closed) == 1
        assert closed[0].realized_pnl > Decimal("0")

    def test_ledger_idempotency_through_sqlite(self, repo) -> None:
        """Duplicate fills are skipped in SQLite path too."""
        from finbot.core.domain.entities.fill_record import FillRecord

        ledger = TradeLedger(repo)
        now = datetime.now(UTC)

        fill = FillRecord(
            bot_run_id="r1",
            order_id="oid1",
            symbol="BTC",
            side="buy",
            size=Decimal("0.1"),
            price=Decimal("50000"),
            fee=Decimal("0"),
            fill_id="f-dup-1",
            filled_at=now,
        )

        ledger.apply_fill(fill)
        outcome = ledger.apply_fill(fill)

        assert outcome.status == "duplicate"
        trades = repo.list_open_trades()
        assert len(trades) == 1
        assert trades[0].size == Decimal("0.1")
