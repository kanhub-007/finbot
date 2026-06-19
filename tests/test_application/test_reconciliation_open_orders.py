"""Tests for startup open-orders reconciliation (S5, C6).

Closes C6: on ``main`` ``reconcile_on_startup`` hardcodes
``open_orders_match=True`` with the comment "placeholder; full order
reconcile later". Only positions are reconciled; open exchange orders
are not fetched or compared. A bot restarting with resting orders
treats them as if they don't exist — ``MaxOpenOrdersGate`` undercounts,
duplicate-cloid tracking is incomplete, and the reconciliation record
lies about whether the books match.

The fix fetches ``exchange.list_open_orders(symbol)``, upserts an
``OrderLifecycle`` (state=OPEN) for any exchange oid the DB doesn't know
about, and sets ``open_orders_match`` based on the diff.

Classical school: in-memory repo + FakeExchangeGateway. Asserts on
observable outcomes (persisted lifecycle rows, the reconciliation
record's fields), never on interaction counts.
"""

from __future__ import annotations

from decimal import Decimal

from finbot.core.application.use_cases.live_trading_runtime import (
    LiveTradingRuntimeUseCase,
)
from finbot.core.domain.entities.order_lifecycle import OrderLifecycle
from finbot.core.domain.entities.order_state import OrderState
from finbot.core.domain.entities.position_direction import PositionDirection
from finbot.core.domain.entities.position_snapshot import PositionSnapshot
from finbot.core.domain.entities.trading_mode import TradingMode
from finbot.core.domain.services.enrichment_validator import EnrichmentValidator
from finbot.core.domain.services.trade_ledger import TradeLedger
from finbot.infrastructure.adapters.simple_runtime_event_emitter import (
    SimpleRuntimeEventEmitter,
)
from tests.fakes import (
    FakeExchangeGateway,
    FakeStrategyEvaluator,
    InMemoryBarFrameConverter,
    InMemoryIndicatorEngine,
    FakeBotStateRepository,
    closed_warmup_bars,
    make_dry_run_submission_strategy,
)


def _make_runtime(
    *,
    repo: FakeBotStateRepository | None = None,
    exchange: FakeExchangeGateway | None = None,
) -> LiveTradingRuntimeUseCase:
    repo = repo or FakeBotStateRepository()
    exchange = exchange or FakeExchangeGateway()
    return LiveTradingRuntimeUseCase(
        exchange_gateway=exchange,
        strategy_evaluator=FakeStrategyEvaluator(),
        state_repository=repo,
        indicator_calculator=InMemoryIndicatorEngine(),
        enrichment_validator=EnrichmentValidator(),
        bar_frame_converter=InMemoryBarFrameConverter(),
        mode=TradingMode.DRY_RUN,
        submission_strategy=make_dry_run_submission_strategy(repo, exchange=exchange),
        event_emitter=SimpleRuntimeEventEmitter(),
        warmup_bars=closed_warmup_bars(30),
        trade_ledger=TradeLedger(repo),
    )


def _exchange_with_orders(*orders: dict) -> FakeExchangeGateway:
    """Build a fake exchange whose list_open_orders returns the given rows."""
    exchange = FakeExchangeGateway()
    exchange.orders_to_report = list(orders)
    # Position is FLAT so reconcile doesn't try to reconstruct a trade.
    exchange._position = PositionSnapshot(
        symbol="BTC", direction=PositionDirection.FLAT, size=Decimal("0")
    )
    return exchange


class TestReconcilePersistsOpenOrders:
    """C6: exchange open orders are persisted as OPEN lifecycles on startup."""

    def test_exchange_orders_with_empty_db_persists_lifecycles(self):
        repo = FakeBotStateRepository()
        exchange = _exchange_with_orders(
            {"oid": "A", "coin": "BTC", "side": "B", "sz": "0.1"},
            {"oid": "B", "coin": "BTC", "side": "S", "sz": "0.2"},
        )
        runtime = _make_runtime(repo=repo, exchange=exchange)
        runtime._start_session("strat", "hash", "BTC", "1h")

        runtime.reconcile_on_startup()

        # Both exchange oids are now persisted as OPEN lifecycles.
        a = repo.get_order_lifecycle("A")
        b = repo.get_order_lifecycle("B")
        assert a is not None and a.state == OrderState.OPEN
        assert b is not None and b.state == OrderState.OPEN
        # original_size is parsed from the exchange payload.
        assert a.original_size == Decimal("0.1")
        assert b.original_size == Decimal("0.2")

    def test_exchange_orders_with_empty_db_reports_mismatch(self):
        """When the DB has no lifecycle for an exchange oid, the reconciliation
        record must report ``open_orders_match=False`` (not the hardcoded True)."""
        repo = FakeBotStateRepository()
        exchange = _exchange_with_orders(
            {"oid": "X", "coin": "BTC", "side": "B", "sz": "0.1"},
        )
        runtime = _make_runtime(repo=repo, exchange=exchange)
        runtime._start_session("strat", "hash", "BTC", "1h")

        rec = runtime.reconcile_on_startup()

        assert rec.open_orders_match is False
        # Details surface the unmatched oid so operators can investigate.
        assert "X" in rec.details

    def test_all_orders_known_in_db_reports_match(self):
        """When every exchange oid already has a DB lifecycle, match is True."""
        repo = FakeBotStateRepository()
        # Pre-seed the DB with both lifecycles the exchange will report.
        repo.save_order_lifecycle(
            OrderLifecycle(
                order_id="A",
                symbol="BTC",
                side="buy",
                original_size=Decimal("0.1"),
                state=OrderState.OPEN,
            )
        )
        exchange = _exchange_with_orders(
            {"oid": "A", "coin": "BTC", "side": "B", "sz": "0.1"},
        )
        runtime = _make_runtime(repo=repo, exchange=exchange)
        runtime._start_session("strat", "hash", "BTC", "1h")

        rec = runtime.reconcile_on_startup()

        assert rec.open_orders_match is True
        """When every exchange oid already has a DB lifecycle, match is True."""
        repo = FakeBotStateRepository()
        # Pre-seed the DB with both lifecycles the exchange will report.
        repo.save_order_lifecycle(
            OrderLifecycle(
                order_id="A",
                symbol="BTC",
                side="buy",
                original_size=Decimal("0.1"),
                state=OrderState.OPEN,
            )
        )
        exchange = _exchange_with_orders(
            {"oid": "A", "coin": "BTC", "side": "B", "sz": "0.1"},
        )
        runtime = _make_runtime(repo=repo, exchange=exchange)
        runtime._start_session("strat", "hash", "BTC", "1h")

        rec = runtime.reconcile_on_startup()

        assert rec.open_orders_match is True

    def test_stale_db_lifecycle_not_on_exchange_reports_mismatch(self):
        """An oid in the DB but not on the exchange is also a mismatch."""
        repo = FakeBotStateRepository()
        repo.save_order_lifecycle(
            OrderLifecycle(
                order_id="STALE",
                symbol="BTC",
                side="buy",
                original_size=Decimal("0.1"),
                state=OrderState.OPEN,
            )
        )
        # Exchange reports no open orders.
        exchange = _exchange_with_orders()

        runtime = _make_runtime(repo=repo, exchange=exchange)
        runtime._start_session("strat", "hash", "BTC", "1h")

        rec = runtime.reconcile_on_startup()

        assert rec.open_orders_match is False
        assert "STALE" in rec.details

    def test_no_exchange_orders_and_empty_db_reports_match(self):
        """Both sides empty is a match (the common clean-restart case)."""
        repo = FakeBotStateRepository()
        exchange = _exchange_with_orders()
        runtime = _make_runtime(repo=repo, exchange=exchange)
        runtime._start_session("strat", "hash", "BTC", "1h")

        rec = runtime.reconcile_on_startup()

        assert rec.open_orders_match is True

    def test_existing_lifecycle_is_not_overwritten(self):
        """If a lifecycle already exists with transition history, reconcile
        must not replace it with a fresh stub (would lose history)."""
        repo = FakeBotStateRepository()
        existing = OrderLifecycle(
            order_id="A",
            symbol="BTC",
            side="buy",
            original_size=Decimal("0.5"),
            state=OrderState.PARTIALLY_FILLED,
        )
        existing.record_transition(
            OrderState.SUBMITTED, OrderState.OPEN, "order_update: open"
        )
        existing.persisted_transition_count = 1
        repo.save_order_lifecycle(existing)

        exchange = _exchange_with_orders(
            {"oid": "A", "coin": "BTC", "side": "B", "sz": "0.5"},
        )
        runtime = _make_runtime(repo=repo, exchange=exchange)
        runtime._start_session("strat", "hash", "BTC", "1h")

        runtime.reconcile_on_startup()

        after = repo.get_order_lifecycle("A")
        assert after is not None
        # State preserved (not reset to OPEN).
        assert after.state == OrderState.PARTIALLY_FILLED
        # Transition history preserved.
        assert len(after.transition_history) == 1
