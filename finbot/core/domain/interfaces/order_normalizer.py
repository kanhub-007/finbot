"""Order normalizer interface — rounds sizes/prices to exchange precision."""

from abc import ABC, abstractmethod
from decimal import Decimal

from finbot.core.domain.entities.order_intent import OrderIntent


class OrderNormalizer(ABC):
    """Adjust order sizes and prices to meet exchange precision rules."""

    @abstractmethod
    def normalize(self, intent: OrderIntent, reference_price: Decimal) -> OrderIntent:
        """Return a new ``OrderIntent`` with exchange-safe precision.

        Args:
            intent: Raw intent from strategy evaluation.
            reference_price: Current market price for slippage calculations.

        Raises:
            OrderNormalizationError: When the order cannot be normalized.
        """
