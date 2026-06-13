"""Mode gate — blocks order planning when the run mode is not permissioned."""

from typing import Any

from finbot.core.domain.entities.risk_decision import RiskDecision
from finbot.core.domain.entities.signal_decision import SignalDecision
from finbot.core.domain.interfaces.risk_gate import RiskGate


class ModeGate(RiskGate):
    """Reject signals unless the configured mode allows trading.

    This is the per-order counterpart of the startup
    :func:`~finbot.core.domain.services.live_mode_guard.check_live_mode` guard:
    it refuses to plan an order in ``live`` mode unless the explicit
    ``live_trading_ack`` was supplied.  ``dry_run`` and ``testnet`` are
    allowed (real submission is gated by the gateway and normalizer), so
    the default ``ModeGate()`` accepts every signal — preserving dry-run
    simulation semantics.
    """

    def __init__(
        self,
        mode: str = "dry_run",
        live_trading_ack: bool = False,
    ) -> None:
        self._mode = mode
        self._ack = live_trading_ack

    def check(self, signal: SignalDecision, context: dict[str, Any]) -> RiskDecision:
        _ = signal, context
        if self._mode == "live" and not self._ack:
            return RiskDecision(
                accepted=False,
                reason="live mode requires live_trading_ack=true",
                gate_name="mode",
            )
        return RiskDecision(accepted=True, gate_name="mode")
