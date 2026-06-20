"""Account event handler — dispatches exchange account websocket events.

Processes order-update and fill events: it advances order lifecycle state
through the :class:`OrderStateMachine` and persists fill records with
idempotent deduplication.  Extracted from
:class:`LiveTradingRuntimeUseCase` so the candle pipeline stays a thin
orchestrator with a single responsibility.
"""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any

from finbot.core.domain.dto.fill_outcome import FillOutcome
from finbot.core.domain.entities.fill_record import FillRecord
from finbot.core.domain.entities.order_lifecycle import OrderLifecycle
from finbot.core.domain.entities.order_state import OrderState
from finbot.core.domain.interfaces.bot_notification_sender import (
    BotNotificationSender,
)
from finbot.core.domain.interfaces.bot_state_repository import (
    BotStateRepository,
)
from finbot.core.domain.services.order_state_machine import (
    OrderStateMachine,
)
from finbot.core.domain.services.trade_ledger import TradeLedger
from finbot.core.domain.services.transactional import transactional

logger = logging.getLogger(__name__)

# Maps Hyperliquid order-update status strings to lifecycle target states.
_STATUS_TO_STATE: dict[str, OrderState] = {
    "accepted": OrderState.ACCEPTED,
    "open": OrderState.OPEN,
    "cancelled": OrderState.CANCELLED,
    "rejected": OrderState.REJECTED,
    "expired": OrderState.EXPIRED,
}


class AccountEventHandler:
    """Dispatch account websocket events and persist their effects.

    Parameters
    ----------
    repo:
        Bot state repository used for lifecycle persistence and fill
        deduplication.
    """

    def __init__(
        self,
        repo: BotStateRepository,
        trade_ledger: TradeLedger | None = None,
        notification_sender: BotNotificationSender | None = None,
    ) -> None:
        self._repo = repo
        self._trade_ledger = trade_ledger or TradeLedger(repo)
        self._notification_sender = notification_sender

    def handle(
        self,
        event: dict[str, Any],
        *,
        bot_run_id: str,
        symbol: str,
    ) -> dict[str, Any]:
        """Dispatch one account event by ``type``.

        Returns a status dict describing how the event was processed.
        """
        event_type = event.get("type", "")
        order_id = str(event.get("order_id", event.get("cloid", "")))

        if not order_id:
            return {"status": "skipped", "reason": "no order_id or cloid"}

        if event_type == "order_update":
            return self._handle_order_update(order_id, event)
        if event_type == "fill":
            return self._handle_fill(
                order_id, event, bot_run_id=bot_run_id, symbol=symbol
            )
        return {"status": "skipped", "reason": f"unknown event type: {event_type}"}

    # -- order updates ------------------------------------------------------

    def _handle_order_update(
        self, order_id: str, event: dict[str, Any]
    ) -> dict[str, Any]:
        status = str(event.get("status", "")).lower()
        lifecycle = self._get_or_create_lifecycle(order_id)

        target = _STATUS_TO_STATE.get(status)
        if target is None:
            # Unknown status — escalate to reconciliation required.
            try:
                OrderStateMachine.transition(
                    lifecycle,
                    OrderState.UNKNOWN_RECONCILE_REQUIRED,
                    f"unknown order status: {status}",
                )
            except Exception as e:  # noqa: BLE001 - log and continue
                logger.warning(
                    "Unknown status transition failed for %s: %s", order_id, e
                )
            self._repo.save_order_lifecycle(lifecycle)
            return {"status": "unknown_status", "reason": str(status)}

        try:
            OrderStateMachine.transition(lifecycle, target, f"order_update: {status}")
        except Exception as e:  # noqa: BLE001 - reported to caller
            return {"status": "transition_rejected", "reason": str(e)}
        self._repo.save_order_lifecycle(lifecycle)
        return {"status": "processed"}

    # -- fills --------------------------------------------------------------

    def _handle_fill(
        self,
        order_id: str,
        event: dict[str, Any],
        *,
        bot_run_id: str,
        symbol: str,
    ) -> dict[str, Any]:
        fill_id = str(event.get("fill_id", ""))
        if not fill_id:
            return {"status": "skipped", "reason": "no fill_id"}
        # Idempotency is handled by TradeLedger.apply_fill (in-memory LRU
        # cache + cross-session DB check) — no duplicate guard needed here.
        size = Decimal(str(event.get("size", "0")))
        fill = self._build_fill_record(
            order_id, event, bot_run_id, symbol, fill_id, size
        )
        result = self._apply_fill_within_tx(order_id, fill, size)
        if result["status"] == "processed":
            self._notify_fill(fill, result.get("outcome"))
        return result

    def _apply_fill_within_tx(
        self, order_id: str, fill: FillRecord, size: Decimal
    ) -> dict[str, Any]:
        """Apply transition + ledger + fill record (M13 de-dup).

        Uses a repo transaction if available; otherwise applies directly.
        Both paths share the same three operations via _apply_fill_effects.
        """
        return transactional(
            self._repo, lambda: self._apply_fill_effects(order_id, fill, size)
        )

    def _apply_fill_effects(
        self, order_id: str, fill: FillRecord, size: Decimal
    ) -> dict[str, Any]:
        """Transition + ledger + record (shared by txn/non-txn paths).

        Returns the :class:`FillOutcome` from the trade ledger so the
        caller can extract PnL for notifications without re-querying.
        """
        if not self._apply_fill_transition(order_id, size):
            return {"status": "transition_rejected", "outcome": None}
        outcome = self._trade_ledger.apply_fill(fill)
        self._repo.record_fill(fill)
        return {"status": "processed", "outcome": outcome}

    def _apply_fill_transition(self, order_id: str, size: Decimal) -> bool:
        """Advance the lifecycle for a fill; return False on transition failure."""
        lifecycle = self._get_or_create_lifecycle(order_id)
        new_filled = lifecycle.filled_size + size
        # Only mark FILLED when we know the original size; a stub (original_size
        # == 0) is an unknown order, so a fill can't be proven complete.
        target = (
            OrderState.FILLED
            if lifecycle.original_size > 0 and new_filled >= lifecycle.original_size
            else OrderState.PARTIALLY_FILLED
        )
        try:
            OrderStateMachine.transition(
                lifecycle, target, f"fill {size}", fill_size=size
            )
        except Exception as e:  # noqa: BLE001 - log and continue
            logger.warning("Fill transition failed for %s: %s", order_id, e)
            return False
        self._repo.save_order_lifecycle(lifecycle)
        return True

    def _build_fill_record(
        self,
        order_id: str,
        event: dict[str, Any],
        bot_run_id: str,
        symbol: str,
        fill_id: str,
        size: Decimal,
    ) -> FillRecord:
        side = self._fill_side(event, order_id)
        return FillRecord(
            bot_run_id=bot_run_id,
            order_id=order_id,
            symbol=symbol or "DEFAULT",
            side=side,
            size=size,
            price=Decimal(str(event.get("price", "0"))),
            fee=Decimal(str(event.get("fee", "0"))),
            fill_id=fill_id,
        )

    def _fill_side(self, event: dict[str, Any], order_id: str) -> str:
        """Derive the fill side from the event, falling back to the lifecycle."""
        lifecycle = self._repo.get_order_lifecycle(order_id)
        fallback = lifecycle.side if lifecycle and lifecycle.side != "unknown" else ""
        return str(event.get("side", fallback))

    # -- notifications -----------------------------------------------------

    def _notify_fill(
        self, fill: FillRecord, outcome: FillOutcome | None = None
    ) -> None:
        """Send a trade notification if a sender is configured.

        Uses the *outcome* from :meth:`TradeLedger.apply_fill` to extract
        PnL for closing fills.  When *outcome* is ``None`` (transition
        rejected), no notification is sent.
        """
        if self._notification_sender is None or outcome is None:
            return
        try:
            pnl_str: str | None = None
            if outcome.status == "closed" and outcome.realized_pnl is not None:
                pnl_str = str(outcome.realized_pnl)

            from datetime import UTC, datetime

            from finbot.core.domain.events.trade_executed import TradeExecuted

            event = TradeExecuted(
                run_id=fill.bot_run_id,
                symbol=fill.symbol,
                side=fill.side,
                size=str(fill.size),
                price=str(fill.price),
                pnl=pnl_str,
                order_id=fill.order_id,
                timestamp=datetime.now(UTC),
            )
            self._notification_sender.notify_trade(event)
        except Exception:
            logger.warning("Failed to send trade notification", exc_info=True)

    # -- lifecycle access ---------------------------------------------------

    def _get_or_create_lifecycle(self, order_id: str) -> OrderLifecycle:
        """Return the existing lifecycle, or create a stub for reconciliation."""
        lifecycle = self._repo.get_order_lifecycle(order_id)
        if lifecycle is not None:
            return lifecycle
        lifecycle = OrderLifecycle(
            order_id=order_id,
            symbol="",
            side="unknown",
            original_size=Decimal("0"),
            state=OrderState.SUBMITTED,
        )
        self._repo.save_order_lifecycle(lifecycle)
        return lifecycle
