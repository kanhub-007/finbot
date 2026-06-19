"""Live mode guard — blocks live trading until all safety gates are met.

Returns a list of reasons when any precondition fails so the caller
can report ALL issues at once instead of failing one-at-a-time.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class LiveModeCheckResult:
    """Outcome of a live-mode eligibility check."""

    allowed: bool
    reasons: tuple[str, ...] = ()


def check_live_mode(
    *,
    mode: str,
    live_trading_ack: bool,
    private_key: str,
    max_position_usd: float,
    database_path: str,
) -> LiveModeCheckResult:
    """Return whether live trading is permitted and, if not, why.

    All parameters are read from :class:`Settings` by the caller.
    """
    if mode != "live":
        return LiveModeCheckResult(
            allowed=False,
            reasons=("FINBOT_MODE must be 'live'",),
        )

    reasons: list[str] = []

    if not live_trading_ack:
        reasons.append("FINBOT_LIVE_TRADING_ACK must be 'true'")

    if not private_key:
        reasons.append(
            "FINBOT_HYPERLIQUID_PRIVATE_KEY must be set "
            "(use an Agent Wallet key from app.hyperliquid.xyz/API, "
            "not your main wallet key)"
        )

    if max_position_usd <= 0:
        reasons.append("FINBOT_MAX_POSITION_USD must be > 0")

    if not database_path or database_path in (":memory:", "data/finbot.db"):
        reasons.append(
            "FINBOT_DATABASE_URL must be set to a durable path "
            "(not :memory: or default)"
        )

    if reasons:
        return LiveModeCheckResult(allowed=False, reasons=tuple(reasons))

    return LiveModeCheckResult(allowed=True)
