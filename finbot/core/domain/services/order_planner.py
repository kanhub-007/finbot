"""Order planner — converts strategy signals into exchange-ready order intents.

Pure domain service.  Runs a chain of :class:`RiskGate` instances
against each signal and produces an :class:`OrderPlanResult`.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from finbot.core.domain.dto.order_plan_result import OrderPlanResult
from finbot.core.domain.entities.order_intent import OrderIntent
from finbot.core.domain.entities.order_side import OrderSide
from finbot.core.domain.entities.order_type import OrderType
from finbot.core.domain.entities.signal_action import SignalAction
from finbot.core.domain.entities.signal_decision import SignalDecision
from finbot.core.domain.interfaces.order_planner import (
    OrderPlanner as OrderPlannerInterface,
)
from finbot.core.domain.interfaces.risk_gate import RiskGate


class OrderPlanner(OrderPlannerInterface):
    """Plan an order from a strategy signal.

    Parameters
    ----------
    gates:
        Risk gates evaluated in order (first rejection stops the chain).
    default_size:
        Base position size in base units when the signal doesn't
        specify one.
    """

    def __init__(
        self,
        gates: list[RiskGate],
        default_size: Decimal = Decimal("0.001"),
    ) -> None:
        self._gates = gates
        self._default_size = default_size

    def plan(
        self, signal: SignalDecision, context: dict[str, Any] | None = None
    ) -> OrderPlanResult:
        """Evaluate the signal through all risk gates and produce an intent.

        Parameters
        ----------
        signal:
            Strategy signal to evaluate.
        context:
            Extra data available to gates (bar dict, position state,
            open order count, daily loss, etc.).
        """
        ctx: dict[str, Any] = dict(context or {})

        # Build the proposed intent first so gates can inspect it.
        intent = self._build_intent(signal, ctx)
        if intent is not None:
            ctx["proposed_size"] = intent.size
            ctx["reduce_only"] = intent.reduce_only

        for gate in self._gates:
            decision = gate.check(signal, ctx)
            if not decision.accepted:
                return OrderPlanResult(
                    accepted=False,
                    reason=decision.reason,
                    gate_name=decision.gate_name,
                    signal_key=signal.signal_key,
                )

        return OrderPlanResult(
            accepted=True,
            intent=intent,
            signal_key=signal.signal_key,
        )

    # -- internal -----------------------------------------------------------

    def _build_intent(
        self, signal: SignalDecision, ctx: dict[str, Any]
    ) -> OrderIntent | None:
        action = signal.action

        if action == SignalAction.HOLD:
            return None

        side, reduce_only = _action_to_side(action)
        if side is None:
            return None

        bar = ctx.get("bar", {})
        close_raw = bar.get("close", 0)
        close = Decimal(str(close_raw))
        size = ctx.get("proposed_size", self._default_size)

        # Fall back to MARKET when no valid close price is available.
        if close <= 0:
            return OrderIntent(
                symbol=ctx.get("symbol", ""),
                side=side,
                size=size,
                order_type=OrderType.MARKET,
                signal_key=signal.signal_key,
                reduce_only=reduce_only,
                stop_price=signal.stop_price,
                target_price=signal.target_price,
            )

        return OrderIntent(
            symbol=ctx.get("symbol", ""),
            side=side,
            size=size,
            order_type=OrderType.LIMIT,
            signal_key=signal.signal_key,
            reduce_only=reduce_only,
            limit_price=close,
            stop_price=signal.stop_price,
            target_price=signal.target_price,
        )


def _action_to_side(action: SignalAction) -> tuple[OrderSide | None, bool]:
    """Map signal action to order side and reduce_only flag."""
    mapping: dict[SignalAction, tuple[OrderSide, bool]] = {
        SignalAction.LONG_ENTRY: (OrderSide.BUY, False),
        SignalAction.SHORT_ENTRY: (OrderSide.SELL, False),
        SignalAction.LONG_EXIT: (OrderSide.SELL, True),
        SignalAction.SHORT_EXIT: (OrderSide.BUY, True),
    }
    return mapping.get(action, (None, False))
