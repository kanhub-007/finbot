"""Order submitter — normalizes, submits, and persists exchange responses.

Extracted from :class:`LiveTradingRuntimeUseCase` so the candle pipeline
stays a thin orchestrator.  Owns the post-planning side effects for a
testnet/live order: precision normalization, exchange submission, and
response persistence.

Audit note (H7 remediation): this class no longer writes a
``ReconciliationRecord`` per order. The ``reconciliations`` table is the
operator-facing drift signal and is populated only by
``LiveTradingRuntimeUseCase.reconcile_on_startup``; a per-order
placeholder with ``position_matches=False`` made every live order look
like drift. The order-response row already records that a submission
happened.
"""

from __future__ import annotations

import json
import logging
from decimal import Decimal
from typing import Any

from finbot.core.domain.entities.order_intent import OrderIntent
from finbot.core.domain.entities.order_response_record import (
    OrderResponseRecord,
)
from finbot.core.domain.interfaces.bot_state_repository import (
    BotStateRepository,
)
from finbot.core.domain.interfaces.exchange_gateway import ExchangeGateway
from finbot.core.domain.interfaces.order_normalizer import OrderNormalizer
from finbot.core.domain.services.order_normalizer import (
    OrderNormalizationError,
)

logger = logging.getLogger(__name__)


class LiveOrderExecutor:
    """Normalize an intent, submit it, and persist the exchange response.

    Parameters
    ----------
    exchange:
        Gateway used to submit the normalized order.
    normalizer:
        Exchange-precision normalizer.  When ``None`` the submitter is
        disabled (returns ``False``) — matching the prior behaviour.
    repo:
        Repository for persisting the order response.
    """

    def __init__(
        self,
        exchange: ExchangeGateway,
        normalizer: OrderNormalizer | None,
        repo: BotStateRepository,
    ) -> None:
        self._exchange = exchange
        self._normalizer = normalizer
        self._repo = repo

    def submit(
        self,
        intent: OrderIntent,
        intent_id: str,
        bot_run_id: str,
        reference_price: Decimal,
    ) -> bool:
        """Normalize, submit, and persist.  Returns ``True`` on submission.

        Returns ``False`` (without side effects) when no normalizer is
        configured, the intent lacks an idempotent ``cloid``, or
        normalization rejects the order.
        """
        if self._normalizer is None or not intent.cloid:
            return False

        try:
            normalized = self._normalizer.normalize(intent, reference_price)
        except OrderNormalizationError as e:
            logger.warning("Order normalization failed for intent %s: %s", intent_id, e)
            return False

        response = self._exchange.submit_order(normalized)
        self._persist_response(intent_id, bot_run_id, response)
        return True

    # -- internal -----------------------------------------------------------

    def _persist_response(
        self, intent_id: str, bot_run_id: str, response: dict[str, Any]
    ) -> None:
        status = str(response.get("status", "unknown"))
        self._repo.record_order_response(
            OrderResponseRecord(
                intent_id=intent_id,
                bot_run_id=bot_run_id,
                response_json=json.dumps(response, default=str),
                status=status,
            )
        )
