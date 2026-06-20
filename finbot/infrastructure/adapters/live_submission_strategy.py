"""LiveSubmissionStrategy — submits real orders via the exchange gateway."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from finbot.core.domain.entities.order_intent import OrderIntent
from finbot.core.domain.interfaces.bot_state_repository import (
    BotStateRepository,
)
from finbot.core.domain.interfaces.exchange_gateway import ExchangeGateway
from finbot.core.domain.interfaces.order_normalizer import OrderNormalizer
from finbot.core.domain.interfaces.order_submission_strategy import (
    OrderSubmissionStrategy,
)
from finbot.infrastructure.adapters.live_order_executor import LiveOrderExecutor


class LiveSubmissionStrategy(OrderSubmissionStrategy):
    """Submit real orders to the exchange gateway for testnet/live modes.

    Records the order intent, then delegates to LiveOrderExecutor which
    handles normalization, exchange submission, and response persistence.
    """

    def __init__(
        self,
        exchange_gateway: ExchangeGateway,
        order_normalizer: OrderNormalizer | None,
        repo: BotStateRepository,
        executor: LiveOrderExecutor | None = None,
    ) -> None:
        self._submitter = executor or LiveOrderExecutor(
            exchange_gateway, order_normalizer, repo
        )
        self._repo = repo

    def submit(
        self,
        intent: OrderIntent,
        bot_run_id: str,
        latest_bar: dict[str, Any] | None,
    ) -> tuple[str, bool]:
        """Record intent and submit to the exchange."""
        intent_id = self._repo.record_order_intent(intent)

        ref_price = Decimal("0")
        if latest_bar is not None:
            ref_price = Decimal(str(latest_bar.get("close", "0")))

        submitted = self._submitter.submit(intent, intent_id, bot_run_id, ref_price)
        return intent_id, submitted
