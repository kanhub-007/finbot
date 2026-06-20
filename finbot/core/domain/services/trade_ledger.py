"""Trade ledger — aggregates fills into Trade lifecycle records.

The accountant that decides, for each incoming fill, whether it opens,
accumulates, or closes a Trade, then persists via the repo inside the
caller's transaction.
"""

from __future__ import annotations

from collections import OrderedDict
from datetime import date
from decimal import Decimal
from uuid import uuid4

from finbot.core.domain.dto.fill_outcome import FillOutcome
from finbot.core.domain.entities.fill_record import FillRecord
from finbot.core.domain.entities.position_direction import PositionDirection
from finbot.core.domain.entities.position_snapshot import PositionSnapshot
from finbot.core.domain.entities.trade import Trade
from finbot.core.domain.interfaces.bot_state_repository import (
    BotStateRepository,
)
from finbot.core.domain.services.trade_lifecycle import (
    apply_entry_fill,
    apply_exit_fill,
    open_from_fill,
)

# Maximum number of recent fill IDs to track in memory for O(1) dedup.
# Beyond this the repo DB check (has_fill) provides the safety net.
_MAX_CACHED_FILL_IDS = 10_000


class TradeLedger:
    """Aggregates fills into Trade lifecycle records.

    Parameters
    ----------
    repo:
        Bot state repository used for trade persistence.
    """

    def __init__(self, repo: BotStateRepository, strategy_hash: str = "") -> None:
        self._repo = repo
        self._strategy_hash = strategy_hash
        # Bounded LRU cache of applied fill IDs for O(1) intra-session dedup.
        # The repo ``has_fill`` check is the cross-session safety net;
        # this cache avoids a DB round-trip for every fill on the hot path.
        self._applied_fill_ids: OrderedDict[str, None] = OrderedDict()
        # Cache of realized daily loss per UTC day. The daily-loss gate reads
        # this on every non-HOLD signal; the value only changes when a trade
        # closes on that day, so we compute once and invalidate on close.
        self._daily_loss_cache: dict[date, Decimal] = {}

    def apply_fill(self, fill: FillRecord) -> FillOutcome:
        """Classify and apply a fill to the Trade book.

        - Duplicate fill_id → skipped (idempotent).
        - No open trade → opens a new Trade.
        - Open trade, opposing direction → exits (partial or full).
        - Open trade, same direction → accumulates entry.

        Persists via the repository (caller owns the transaction).
        """
        # Idempotency: skip fills we've already seen this session.
        if fill.fill_id in self._applied_fill_ids:
            return FillOutcome(status="duplicate")

        # Cross-session idempotency: if no open trade exists for this
        # symbol and the fill was already persisted (from a prior session),
        # it's a replay of a fill that already opened+closed a trade.
        existing = self._repo.get_open_trade(fill.symbol)
        if existing is None and self._repo.has_fill(fill.fill_id):
            return FillOutcome(status="duplicate")

        self._applied_fill_ids[fill.fill_id] = None
        # Evict oldest entry when the bounded LRU cache exceeds capacity.
        while len(self._applied_fill_ids) > _MAX_CACHED_FILL_IDS:
            self._applied_fill_ids.popitem(last=False)

        # Reuse the open trade already fetched for the idempotency check —
        # nothing between the two reads can change it, so a second indexed
        # lookup is pure waste.
        open_trade = existing

        if open_trade is None:
            # No open trade → this fill opens a new Trade.
            trade = open_from_fill(
                fill,
                position_id=uuid4().hex,
                strategy_hash=self._strategy_hash,
            )
            self._repo.open_trade(trade)
            return FillOutcome(
                status="opened",
                position_id=trade.position_id,
            )

        # We have an open trade — classify by direction.
        fill_is_buy = fill.side == "buy"
        trade_is_long = open_trade.side == PositionDirection.LONG

        if fill_is_buy == trade_is_long:
            # Same direction → accumulate entry.
            trade = apply_entry_fill(open_trade, fill)
            self._repo.update_trade(trade)
            return FillOutcome(
                status="accumulated",
                position_id=trade.position_id,
            )

        # Opposing direction → exit (partial or full).
        trade = apply_exit_fill(open_trade, fill)
        self._repo.update_trade(trade)
        if trade.status == "closed":
            # A close changes the realized daily-loss sum; drop the cache so
            # the next signal recomputes from authoritative state.
            self._daily_loss_cache.clear()
            return FillOutcome(
                status="closed",
                position_id=trade.position_id,
                realized_pnl=trade.realized_pnl,
            )
        return FillOutcome(
            status="partial",
            position_id=trade.position_id,
            realized_pnl=trade.realized_pnl,
        )

    def open_trade_for(self, symbol: str) -> Trade | None:
        """Read-only: the current open Trade for a symbol."""
        return self._repo.get_open_trade(symbol)

    def realized_loss_on(self, day: date) -> Decimal:
        """Sum of negative realized PnL from trades closed on *day* (UTC).

        Positive results contribute 0 — a loss gate counts losses only.
        Cached per day; invalidated when a trade closes (see apply_fill).
        """
        cached = self._daily_loss_cache.get(day)
        if cached is not None:
            return cached
        total = self._repo.realized_loss_on(day)
        self._daily_loss_cache[day] = total
        return total

    def reconstruct_open(
        self,
        position: PositionSnapshot,
        *,
        bot_run_id: str,
        strategy_hash: str = "",
    ) -> Trade:
        """Build an open Trade from an exchange position with no fill history.

        Used at startup reconciliation when the exchange reports an open
        position but the DB has no Trade for it.
        """
        from datetime import UTC, datetime

        side = position.direction
        if side == PositionDirection.FLAT:
            raise ValueError("cannot reconstruct a Trade from a FLAT position")
        return Trade(
            position_id=uuid4().hex,
            bot_run_id=bot_run_id,
            symbol=position.symbol,
            side=side,
            size=abs(position.size),
            entry_price=None,  # type: ignore[arg-type] — unknown without fills
            opened_at=datetime.now(UTC),
            status="open",
            realized_pnl=Decimal("0"),
            total_fee=Decimal("0"),
            strategy_hash=strategy_hash,
        )
