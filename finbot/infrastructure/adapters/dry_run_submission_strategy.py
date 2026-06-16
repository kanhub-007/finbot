"""DryRunSubmissionStrategy — synthesizes fills without exchange calls."""

from __future__ import annotations

from datetime import UTC, datetime as _dt
from decimal import Decimal
from typing import Any

from finbot.core.domain.entities.fill_record import FillRecord
from finbot.core.domain.interfaces.bot_state_repository import (
    BotStateRepository,
)
from finbot.core.domain.interfaces.order_submission_strategy import (
    OrderSubmissionStrategy,
)
from finbot.core.domain.services.trade_ledger import TradeLedger


class DryRunSubmissionStrategy(OrderSubmissionStrategy):
    """Synthesize fills locally instead of submitting to the exchange.

    Records the order intent, creates a synthetic FillRecord from the
    latest bar's close price, and applies it to the TradeLedger.
    """

    def __init__(
        self,
        repo: BotStateRepository,
        trade_ledger: TradeLedger,
    ) -> None:
        self._repo = repo
        self._trade_ledger = trade_ledger

    def submit(
        self,
        intent: object,
        bot_run_id: str,
        latest_bar: dict[str, Any] | None,
    ) -> tuple[str, bool]:
        """Record intent and synthesize a fill from the latest bar."""
        intent_id = self._repo.record_order_intent(intent)

        fill = self._synthesize_fill(intent, intent_id, bot_run_id, latest_bar)
        if fill is not None:
            self._trade_ledger.apply_fill(fill)
        return intent_id, False

    @staticmethod
    def _synthesize_fill(
        intent, intent_id: str, bot_run_id: str,
        latest_bar: dict[str, Any] | None,
    ) -> FillRecord | None:
        """Build a synthetic FillRecord from an OrderIntent."""
        if latest_bar is None:
            return None
        ref_price = Decimal(str(latest_bar.get("close", "0")))
        if ref_price <= 0:
            return None
        return FillRecord(
            bot_run_id=bot_run_id,
            order_id=intent_id,
            symbol=intent.symbol,
            side=intent.side.value,
            size=intent.size,
            price=ref_price,
            fee=Decimal("0"),
            fill_id=f"dry:{intent_id}",
            filled_at=_dt.now(UTC),
        )
