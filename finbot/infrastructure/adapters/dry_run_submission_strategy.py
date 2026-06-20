"""DryRunSubmissionStrategy — synthesizes fills without real exchange calls.

Records the order intent, optionally delegates to the exchange's
``submit_order`` (so dry-run exchange fakes can track position state — the
real :class:`DryRunExchangeGateway` treats it as a no-op), then synthesizes a
fill from the latest bar and applies it to the :class:`TradeLedger`.
"""

from __future__ import annotations

from datetime import UTC
from datetime import datetime as _dt
from decimal import Decimal
from typing import Any

from finbot.core.domain.entities.fill_record import FillRecord
from finbot.core.domain.entities.order_intent import OrderIntent
from finbot.core.domain.interfaces.bot_state_repository import (
    BotStateRepository,
)
from finbot.core.domain.interfaces.exchange_gateway import ExchangeGateway
from finbot.core.domain.interfaces.order_submission_strategy import (
    OrderSubmissionStrategy,
)
from finbot.core.domain.services.trade_ledger import TradeLedger


class DryRunSubmissionStrategy(OrderSubmissionStrategy):
    """Synthesize fills locally instead of submitting real exchange orders.

    When an ``exchange`` is wired, ``submit_order`` is called on it so that
    dry-run exchange fakes (e.g. ``TrackingDryRunExchange`` in tests) can
    update their internal position state. The production
    :class:`DryRunExchangeGateway` no-ops this call, so live funds are never
    at risk.
    """

    def __init__(
        self,
        repo: BotStateRepository,
        trade_ledger: TradeLedger,
        exchange: ExchangeGateway | None = None,
    ) -> None:
        self._repo = repo
        self._trade_ledger = trade_ledger
        self._exchange = exchange

    def submit(
        self,
        intent: OrderIntent,
        bot_run_id: str,
        latest_bar: dict[str, Any] | None,
    ) -> tuple[str, bool]:
        """Record intent, optionally notify exchange, synthesize fill."""
        intent_id = self._repo.record_order_intent(intent)

        # Let the exchange fake track position (no-op on DryRunExchangeGateway).
        if self._exchange is not None:
            try:
                self._exchange.submit_order(intent)
            except Exception:
                pass

        fill = self._synthesize_fill(intent, intent_id, bot_run_id, latest_bar)
        if fill is not None:
            self._trade_ledger.apply_fill(fill)
        return intent_id, False

    @staticmethod
    def _synthesize_fill(
        intent: OrderIntent,
        intent_id: str,
        bot_run_id: str,
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
