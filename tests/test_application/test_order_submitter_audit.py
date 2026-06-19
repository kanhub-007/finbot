"""Tests for OrderSubmitter audit hygiene (S3: H7).

``OrderSubmitter`` previously wrote a ``ReconciliationRecord`` after every
live order with ``position_matches=False`` / ``open_orders_match=False``.
That polluted the operator-facing ``reconciliations`` table (used to
detect exchange/DB drift) — every live order looked like a reconciliation
failure.

ADR-1 (option A): delete the call. Real reconciliation happens in
``LiveTradingRuntimeUseCase.reconcile_on_startup``; the order-response
row already records that a submission happened.
"""

from __future__ import annotations

from decimal import Decimal

from finbot.core.application.use_cases.order_submitter import OrderSubmitter
from finbot.core.domain.entities.order_intent import OrderIntent
from finbot.core.domain.entities.order_side import OrderSide
from finbot.core.domain.entities.order_type import OrderType
from tests.fakes import InMemoryExchangeGateway, StubBotStateRepository


class _PassthroughNormalizer:
    """Normalizer fake that returns the intent unchanged."""

    def normalize(self, intent, ref_price):  # noqa: ANN001 - fake signature
        return intent


def _intent(cloid: str = "c-1") -> OrderIntent:
    return OrderIntent(
        symbol="BTC",
        side=OrderSide.BUY,
        size=Decimal("0.1"),
        order_type=OrderType.LIMIT,
        cloid=cloid,
    )


class TestOrderSubmitterNoReconciliationPollution:
    def test_submit_writes_no_reconciliation_record(self) -> None:
        """A single live submit must not write a reconciliation row."""
        repo = StubBotStateRepository()
        exchange = InMemoryExchangeGateway()
        submitter = OrderSubmitter(exchange, _PassthroughNormalizer(), repo)

        intent_id = repo.record_order_intent(_intent())
        submitter.submit(_intent(), intent_id, "run-1", Decimal("50000"))

        assert len(repo._reconciliations) == 0
        # The order response is still persisted.
        assert len(repo._order_responses) == 1

    def test_ten_submits_leave_zero_reconciliation_rows(self) -> None:
        """Repeated submits must not accumulate reconciliation noise."""
        repo = StubBotStateRepository()
        exchange = InMemoryExchangeGateway()
        submitter = OrderSubmitter(exchange, _PassthroughNormalizer(), repo)

        for i in range(10):
            intent = _intent(cloid=f"c-{i}")
            intent_id = repo.record_order_intent(intent)
            submitter.submit(intent, intent_id, "run-1", Decimal("50000"))

        assert len(repo._reconciliations) == 0
        assert len(repo._order_responses) == 10

    def test_submit_without_normalizer_writes_no_reconciliation(self) -> None:
        """The disabled-submission path (no normalizer) also writes none."""
        repo = StubBotStateRepository()
        exchange = InMemoryExchangeGateway()
        submitter = OrderSubmitter(exchange, normalizer=None, repo=repo)

        intent_id = repo.record_order_intent(_intent())
        submitted = submitter.submit(_intent(), intent_id, "run-1", Decimal("50000"))

        assert submitted is False
        assert len(repo._reconciliations) == 0
