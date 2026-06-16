"""Trade lifecycle — pure transition functions for the Trade entity.

Stateless functions that produce new immutable Trade instances from fills.
No I/O, no repo — trivially unit-testable.
"""

from datetime import datetime
from decimal import Decimal

from finbot.core.domain.entities.fill_record import FillRecord
from finbot.core.domain.entities.position_direction import PositionDirection
from finbot.core.domain.entities.trade import Trade


def sign_for(side: PositionDirection) -> int:
    """Return +1 for LONG, -1 for SHORT."""
    return 1 if side == PositionDirection.LONG else -1


def open_from_fill(
    fill: FillRecord,
    position_id: str,
    strategy_hash: str = "",
) -> Trade:
    """Create a new open Trade from an entry fill.

    The fill's side determines the Trade direction: buy → LONG, sell → SHORT.
    The fill's fee is recorded as the initial total_fee.
    """
    side = (
        PositionDirection.LONG
        if fill.side == "buy"
        else PositionDirection.SHORT
    )
    return Trade(
        position_id=position_id,
        bot_run_id=fill.bot_run_id,
        symbol=fill.symbol,
        side=side,
        size=fill.size,
        entry_price=fill.price,
        opened_at=fill.filled_at,
        status="open",
        realized_pnl=Decimal("0"),
        total_fee=fill.fee,
        strategy_hash=strategy_hash,
    )


def apply_entry_fill(trade: Trade, fill: FillRecord) -> Trade:
    """Accumulate an entry fill into an existing open Trade.

    Increases size, recomputes volume-weighted average entry price,
    and adds the fill's fee.
    """
    total_notional = trade.entry_price * trade.size + fill.price * fill.size
    new_size = trade.size + fill.size
    new_entry_price = total_notional / new_size if new_size > 0 else trade.entry_price
    return Trade(
        position_id=trade.position_id,
        bot_run_id=trade.bot_run_id,
        symbol=trade.symbol,
        side=trade.side,
        size=new_size,
        entry_price=new_entry_price,
        opened_at=trade.opened_at,
        status=trade.status,
        realized_pnl=trade.realized_pnl,
        total_fee=trade.total_fee + fill.fee,
        strategy_hash=trade.strategy_hash,
        entry_signal_key=trade.entry_signal_key,
    )


def apply_exit_fill(trade: Trade, fill: FillRecord) -> Trade:
    """Apply a reduce fill (exit) to an open Trade.

    Decrements size, accrues realized PnL for the closed portion (net of
    fees), and sets close_price/closed_at when size reaches zero.

    Returns a new Trade (frozen) with updated fields.
    """
    filled_size = min(fill.size, trade.size)

    # When entry_price is unknown (reconstructed without fill history),
    # PnL is indeterminate — use 0 as a safe default.
    if trade.entry_price is None:
        gross_pnl = Decimal("0")
    else:
        gross_pnl = realized_pnl_for_exit(
            entry_price=trade.entry_price,
            exit_price=fill.price,
            size=filled_size,
            side=trade.side,
        )
    net_pnl = gross_pnl - fill.fee

    new_size = trade.size - filled_size
    is_closed = new_size == Decimal("0")

    return Trade(
        position_id=trade.position_id,
        bot_run_id=trade.bot_run_id,
        symbol=trade.symbol,
        side=trade.side,
        size=new_size,
        entry_price=trade.entry_price,
        opened_at=trade.opened_at,
        status="closed" if is_closed else "open",
        realized_pnl=trade.realized_pnl + net_pnl,
        total_fee=trade.total_fee + fill.fee,
        closed_at=fill.filled_at if is_closed else None,
        close_price=fill.price if is_closed else None,
        strategy_hash=trade.strategy_hash,
        entry_signal_key=trade.entry_signal_key,
    )


def realized_pnl_for_exit(
    entry_price: Decimal | None,
    exit_price: Decimal,
    size: Decimal,
    side: PositionDirection,
) -> Decimal:
    """Gross PnL for closing *size* units at *exit_price*, before fees.

    Long:  (exit - entry) * size
    Short: (entry - exit) * size

    Returns 0 when entry_price is None (unknown — reconstructed trade).
    """
    if size == Decimal("0") or entry_price is None:
        return Decimal("0")
    return (exit_price - entry_price) * size * sign_for(side)
