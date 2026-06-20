"""Pure domain service: resolve a user-facing size string (USD / %)
into a token amount using current price and leverage.

Used by Telegram and MCP manual order entry so the conversion logic
is single-sourced.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation


@dataclass(frozen=True)
class ResolvedSize:
    """Result of resolving a user size input to a token amount."""

    token_size: Decimal
    """Size in base units (ready for OrderIntent)."""
    raw_usd: Decimal
    """USD notional before leverage (for risk gate checks)."""
    sz_decimals: int
    """Rounded to this many decimal places."""


def resolve_order_size(
    raw: str,
    price: Decimal,
    leverage: int,
    *,
    available_balance: Decimal | None = None,
    sz_decimals: int = 5,
) -> ResolvedSize | str:
    """Convert a user size input to a token amount.

    *raw* is a USD notional (``"100"``) or percentage (``"25%"``).
    *price* is the current price of the symbol.
    *leverage* is the active symbol's leverage.
    *available_balance* is the total free balance for percentage mode.
    *sz_decimals* is the symbol's size precision (default 5 = BTC).

    Returns a ``ResolvedSize`` on success or a human-readable error
    string on failure.  No I/O — the caller provides all data.
    """
    is_pct = raw.strip().endswith("%")
    try:
        usd = Decimal(raw.strip().rstrip("%"))
    except (InvalidOperation, ValueError):
        return "Invalid size. Use a number (e.g. 100) or percentage (e.g. 25%)."
    if usd <= 0:
        return "Size must be positive."

    if is_pct:
        total = available_balance or Decimal("0")
        if total <= 0:
            return "No available balance to compute percentage."
        usd = total * (usd / Decimal("100"))

    raw_usd = usd
    if price <= 0:
        return "Price unavailable."

    leverage_d = Decimal(str(leverage)) if leverage > 0 else Decimal("1")
    token_size = (usd * leverage_d) / price
    token_size = token_size.quantize(Decimal(10) ** -sz_decimals)
    if token_size <= 0:
        return "Resulting token size is zero."

    return ResolvedSize(
        token_size=token_size,
        raw_usd=raw_usd,
        sz_decimals=sz_decimals,
    )
