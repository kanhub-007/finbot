"""Order normalizer — rounds order sizes/prices to exchange precision.

Pure domain service with no I/O dependencies.  Uses
:class:`MarketMetadata` to enforce exchange-specific constraints.
"""

from __future__ import annotations

from decimal import ROUND_DOWN, Decimal

from finbot.core.domain.entities.market_metadata import MarketMetadata
from finbot.core.domain.entities.order_intent import OrderIntent
from finbot.core.domain.entities.order_side import OrderSide
from finbot.core.domain.entities.order_type import OrderType


class OrderNormalizationError(ValueError):
    """Raised when an order cannot be normalized to exchange requirements."""


class OrderNormalizer:
    """Adjust order sizes and prices to meet exchange precision rules.

    Parameters
    ----------
    metadata:
        Per-symbol constraints from the exchange.
    max_slippage:
        For market (IOC-limit) orders the limit price is offset by
        this fraction relative to the reference price.
        E.g. 0.01 = 1% slippage allowance.  Default 1%.
    """

    def __init__(
        self,
        metadata: MarketMetadata,
        max_slippage: Decimal = Decimal("0.01"),
    ) -> None:
        self._meta = metadata
        self._max_slippage = max_slippage

    # -- public API --------------------------------------------------------

    def normalize(self, intent: OrderIntent, reference_price: Decimal) -> OrderIntent:
        """Return a new :class:`OrderIntent` with exchange-safe precision.

        Parameters
        ----------
        intent:
            Raw intent from strategy evaluation.
        reference_price:
            Current market price used for slippage calculations
            (market orders only).

        Raises
        ------
        OrderNormalizationError
            When the order would be too small after rounding.
        """
        sz_decimals = self._meta.sz_decimals
        size = _round_down(intent.size, sz_decimals)
        if size <= 0 or (self._meta.min_size > 0 and size < self._meta.min_size):
            raise OrderNormalizationError(
                f"Order size {size} is below minimum "
                f"{self._meta.min_size} for {self._meta.symbol}"
            )

        limit_price = intent.limit_price
        if limit_price is not None:
            limit_price = _round_price(limit_price, self._meta.price_tick)

        stop_price = intent.stop_price
        if stop_price is not None:
            stop_price = _round_price(stop_price, self._meta.price_tick)

        target_price = intent.target_price
        if target_price is not None:
            target_price = _round_price(target_price, self._meta.price_tick)

        # Market-as-IOC-limit: apply slippage to the limit price.
        if intent.order_type == OrderType.MARKET and limit_price is None:
            if intent.side == OrderSide.BUY:
                limit_price = _round_price(
                    reference_price * (1 + self._max_slippage),
                    self._meta.price_tick,
                )
            else:
                limit_price = _round_price(
                    reference_price * (1 - self._max_slippage),
                    self._meta.price_tick,
                )

        return OrderIntent(
            symbol=intent.symbol,
            side=intent.side,
            size=size,
            order_type=intent.order_type,
            signal_key=intent.signal_key,
            reduce_only=intent.reduce_only,
            limit_price=limit_price,
            stop_price=stop_price,
            target_price=target_price,
            cloid=intent.cloid,
        )


# -- helpers --------------------------------------------------------------


def _round_down(value: Decimal, decimals: int) -> Decimal:
    quant = Decimal("1").scaleb(-decimals) if decimals >= 0 else Decimal("1")
    return value.quantize(quant, rounding=ROUND_DOWN)


def _round_price(value: Decimal, tick: Decimal) -> Decimal:
    if tick <= 0:
        return value
    return (value / tick).quantize(Decimal("1"), rounding=ROUND_DOWN) * tick
