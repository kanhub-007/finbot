"""Tests for Trade history query and PnL summary (Scenario S11).

Classical school: in-memory repo with real Trade instances.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal


def _trade(position_id: str, realized_pnl: str, closed_minutes_ago: int = 0) -> None:
    """Helper to build a closed Trade but not used directly — see below."""


def test_closed_trades_returned_newest_first() -> None:
    """S11: list_closed_trades returns trades newest-first by closed_at."""
    from finbot.core.domain.entities.position_direction import PositionDirection
    from finbot.core.domain.entities.trade import Trade
    from finbot.infrastructure.repositories.in_memory_bot_state_repository import (
        InMemoryBotStateRepository,
    )

    repo = InMemoryBotStateRepository()
    now = datetime.now(UTC)

    # Open three trades and close them at different times
    t1 = Trade(
        position_id="p1",
        bot_run_id="run1",
        symbol="BTC",
        side=PositionDirection.LONG,
        size=Decimal("0"),
        entry_price=Decimal("50000"),
        opened_at=now - timedelta(hours=3),
        status="closed",
        realized_pnl=Decimal("100"),
        closed_at=now - timedelta(minutes=30),
        close_price=Decimal("51000"),
    )
    t2 = Trade(
        position_id="p2",
        bot_run_id="run1",
        symbol="ETH",
        side=PositionDirection.SHORT,
        size=Decimal("0"),
        entry_price=Decimal("3000"),
        opened_at=now - timedelta(hours=2),
        status="closed",
        realized_pnl=Decimal("-50"),
        closed_at=now - timedelta(minutes=10),
        close_price=Decimal("2950"),
    )
    t3 = Trade(
        position_id="p3",
        bot_run_id="run1",
        symbol="SOL",
        side=PositionDirection.LONG,
        size=Decimal("0"),
        entry_price=Decimal("100"),
        opened_at=now - timedelta(hours=1),
        status="closed",
        realized_pnl=Decimal("200"),
        closed_at=now,
        close_price=Decimal("120"),
    )

    repo.open_trade(t1)
    repo.open_trade(t2)
    repo.open_trade(t3)

    closed = repo.list_closed_trades()
    assert len(closed) == 3

    # Newest first
    assert closed[0].position_id == "p3"  # closed just now
    assert closed[1].position_id == "p2"  # 10 min ago
    assert closed[2].position_id == "p1"  # 30 min ago


def test_closed_trades_filtered_by_bot_run() -> None:
    """list_closed_trades with bot_run_id filter returns only that run's trades."""
    from finbot.core.domain.entities.position_direction import PositionDirection
    from finbot.core.domain.entities.trade import Trade
    from finbot.infrastructure.repositories.in_memory_bot_state_repository import (
        InMemoryBotStateRepository,
    )

    repo = InMemoryBotStateRepository()
    now = datetime.now(UTC)

    t1 = Trade(
        position_id="p1",
        bot_run_id="run1",
        symbol="BTC",
        side=PositionDirection.LONG,
        size=Decimal("0"),
        entry_price=Decimal("50000"),
        opened_at=now,
        status="closed",
        realized_pnl=Decimal("100"),
        closed_at=now,
        close_price=Decimal("51000"),
    )
    t2 = Trade(
        position_id="p2",
        bot_run_id="run2",
        symbol="ETH",
        side=PositionDirection.SHORT,
        size=Decimal("0"),
        entry_price=Decimal("3000"),
        opened_at=now,
        status="closed",
        realized_pnl=Decimal("-50"),
        closed_at=now,
        close_price=Decimal("2950"),
    )

    repo.open_trade(t1)
    repo.open_trade(t2)

    run1_closed = repo.list_closed_trades(bot_run_id="run1")
    assert len(run1_closed) == 1
    assert run1_closed[0].position_id == "p1"

    run2_closed = repo.list_closed_trades(bot_run_id="run2")
    assert len(run2_closed) == 1
    assert run2_closed[0].position_id == "p2"


def test_total_realized_pnl_summary() -> None:
    """A summary total_realized_pnl can be computed from closed trades."""
    from finbot.core.domain.entities.position_direction import PositionDirection
    from finbot.core.domain.entities.trade import Trade
    from finbot.infrastructure.repositories.in_memory_bot_state_repository import (
        InMemoryBotStateRepository,
    )

    repo = InMemoryBotStateRepository()
    now = datetime.now(UTC)

    repo.open_trade(
        Trade(
            position_id="p1",
            bot_run_id="run1",
            symbol="BTC",
            side=PositionDirection.LONG,
            size=Decimal("0"),
            entry_price=Decimal("50000"),
            opened_at=now,
            status="closed",
            realized_pnl=Decimal("100"),
            closed_at=now,
            close_price=Decimal("51000"),
        )
    )
    repo.open_trade(
        Trade(
            position_id="p2",
            bot_run_id="run1",
            symbol="ETH",
            side=PositionDirection.SHORT,
            size=Decimal("0"),
            entry_price=Decimal("3000"),
            opened_at=now,
            status="closed",
            realized_pnl=Decimal("-50"),
            closed_at=now,
            close_price=Decimal("2950"),
        )
    )

    closed = repo.list_closed_trades(bot_run_id="run1")
    total_pnl = sum(t.realized_pnl for t in closed)
    assert total_pnl == Decimal("50")  # 100 + (-50)
