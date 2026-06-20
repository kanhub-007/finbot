"""Order helpers — shared normalisation routines for exchange order fields.

Pure functions with no I/O dependencies.  Used by the trading runtime
(reconciliation) and the account event handler (fill classification).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any


def normalize_order_side(raw: Any) -> str:
    """Normalize an exchange order ``side`` field to a lifecycle side.

    The exchange uses "B"/"A"/"S" (and occasionally "buy"/"sell");
    lifecycles store the lowercase word.  Falls back to ``"unknown"``
    so an unexpected payload never crashes reconciliation.
    """
    s = str(raw).strip().lower()
    if s in ("b", "buy", "long"):
        return "buy"
    if s in ("s", "sell", "short"):
        return "sell"
    if s in ("a", "ask"):
        return "sell"
    return "unknown"


def parse_decimal(value: Any) -> Decimal:
    """Parse an exchange numeric field into a Decimal (0 on failure).

    Used for ``sz`` fields in open-order payloads. Never raises — a
    malformed size shouldn't abort reconciliation.
    """
    try:
        return Decimal(str(value))
    except Exception:
        return Decimal("0")
