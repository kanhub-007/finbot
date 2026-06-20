"""WalletBalance — account value snapshot from the exchange."""

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class WalletBalance:
    """Account balance components in USD.

    Returned by :meth:`ExchangeGateway.get_balance`. Used by /balance and
    shown on /symbol activation.
    """

    wallet_value: Decimal
    """Perp margin account value (cash + unrealised PnL)."""
    margin_used: Decimal
    """Initial margin currently locked in positions."""
    available: Decimal
    """Withdrawable / available for new positions."""
    spot_usdc: Decimal = Decimal("0")
    """Spot USDC balance (not yet deposited into perp margin)."""
