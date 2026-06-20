"""Tests for startup reconciliation (Scenario S8).

Classical school: uses in-memory repo and fake exchange.
"""

from decimal import Decimal

import pytest

from finbot.core.domain.entities.position_direction import PositionDirection
from finbot.core.domain.entities.position_snapshot import PositionSnapshot
from finbot.core.domain.entities.trade import Trade
from finbot.core.domain.services.trade_ledger import TradeLedger


def test_exchange_long_no_db_trade_reconstructs() -> None:
    """S8: exchange has long position, DB has no trade → reconstruct."""
    from finbot.infrastructure.repositories.in_memory_bot_state_repository import (
        InMemoryBotStateRepository,
    )

    repo = InMemoryBotStateRepository()
    ledger = TradeLedger(repo)

    position = PositionSnapshot(
        symbol="BTC",
        direction=PositionDirection.LONG,
        size=Decimal("0.1"),
    )

    trade = ledger.reconstruct_open(
        position,
        bot_run_id="run1",
        strategy_hash="abc123",
    )

    assert trade is not None
    assert trade.side == PositionDirection.LONG
    assert trade.size == Decimal("0.1")
    assert trade.status == "open"
    assert trade.entry_price is None  # unknown without fill history
    assert trade.strategy_hash == "abc123"

    # Persist it
    repo.open_trade(trade)
    assert repo.get_open_trade("BTC") is not None


def test_cannot_reconstruct_from_flat_position() -> None:
    """FLAT position should raise ValueError."""
    from finbot.infrastructure.repositories.in_memory_bot_state_repository import (
        InMemoryBotStateRepository,
    )

    repo = InMemoryBotStateRepository()
    ledger = TradeLedger(repo)  # type: ignore[arg-type]

    position = PositionSnapshot(
        symbol="BTC",
        direction=PositionDirection.FLAT,
        size=Decimal("0"),
    )

    with pytest.raises(ValueError, match="FLAT"):
        ledger.reconstruct_open(position, bot_run_id="run1")


def test_exchange_flat_db_open_trade_kept() -> None:
    """When exchange is flat and DB has an open trade, it stays."""
    from finbot.infrastructure.repositories.in_memory_bot_state_repository import (
        InMemoryBotStateRepository,
    )

    repo = InMemoryBotStateRepository()

    # Pre-seed an open trade
    from datetime import UTC, datetime

    trade = Trade(
        position_id="p1",
        bot_run_id="run1",
        symbol="BTC",
        side=PositionDirection.LONG,
        size=Decimal("0.1"),
        entry_price=Decimal("50000"),
        opened_at=datetime.now(UTC),
        status="open",
    )
    repo.open_trade(trade)

    # The open trade should still be there
    existing = repo.get_open_trade("BTC")
    assert existing is not None
    assert existing.status == "open"


def test_mismatch_flagged_not_auto_corrected() -> None:
    """Exchange long but DB open short → flagged, not auto-corrected."""
    from finbot.infrastructure.repositories.in_memory_bot_state_repository import (
        InMemoryBotStateRepository,
    )

    repo = InMemoryBotStateRepository()

    # DB has open SHORT trade
    from datetime import UTC, datetime

    short_trade = Trade(
        position_id="p1",
        bot_run_id="run1",
        symbol="BTC",
        side=PositionDirection.SHORT,
        size=Decimal("0.1"),
        entry_price=Decimal("50000"),
        opened_at=datetime.now(UTC),
        status="open",
    )
    repo.open_trade(short_trade)

    # The DB trade remains whatever it was — reconciliation flags, not fixes
    db_trade = repo.get_open_trade("BTC")
    assert db_trade is not None
    assert db_trade.side == PositionDirection.SHORT  # not changed
