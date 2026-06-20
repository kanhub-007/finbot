"""Tests for Slice 4 — account websocket events updating order lifecycle and fills."""

from decimal import Decimal

from finbot.core.domain.entities.order_intent import OrderIntent
from finbot.core.domain.entities.order_lifecycle import OrderLifecycle
from finbot.core.domain.entities.order_side import OrderSide
from finbot.core.domain.entities.order_state import OrderState
from finbot.core.domain.entities.order_type import OrderType
from finbot.core.domain.entities.trading_mode import TradingMode
from finbot.core.domain.services.enrichment_validator import (
    EnrichmentValidator,
)
from finbot.core.domain.services.order_planner import OrderPlanner
from finbot.core.domain.services.risk_gates.duplicate_signal_gate import (
    DuplicateSignalGate,
)
from finbot.core.domain.services.risk_gates.mode_gate import ModeGate
from tests.fakes import (
    FakeBotStateRepository,
    FakeStrategyEvaluator,
    InMemoryBarFrameConverter,
    InMemoryExchangeGateway,
    InMemoryIndicatorEngine,
    closed_warmup_bars,
    indicator_bar,
    make_dry_run_submission_strategy,
    make_event_emitter,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_runtime(repo=None):
    from finbot.core.application.use_cases.account_event_handler import (
        AccountEventHandler,
    )
    from finbot.core.application.use_cases.live_trading_runtime import (
        LiveTradingRuntimeUseCase,
    )

    repo = repo or FakeBotStateRepository()
    exchange = InMemoryExchangeGateway()
    return LiveTradingRuntimeUseCase(
        exchange_gateway=exchange,
        strategy_evaluator=FakeStrategyEvaluator(),
        state_repository=repo,
        indicator_calculator=InMemoryIndicatorEngine(
            latest_bar=indicator_bar(atr=1200.0)
        ),
        enrichment_validator=EnrichmentValidator(),
        bar_frame_converter=InMemoryBarFrameConverter(),
        mode=TradingMode.DRY_RUN,
        submission_strategy=make_dry_run_submission_strategy(repo, exchange=exchange),
        event_emitter=make_event_emitter(),
        warmup_bars=closed_warmup_bars(100),
        required_columns={"atr"},
        order_planner=OrderPlanner(gates=[ModeGate(), DuplicateSignalGate(repo)]),
        account_event_handler=AccountEventHandler(repo),
    )


def _sample_intent(intent_id: str = "test-intent-1") -> OrderIntent:
    return OrderIntent(
        symbol="BTC",
        side=OrderSide.BUY,
        size=Decimal("0.001"),
        order_type=OrderType.LIMIT,
        signal_key="BTC:1h:1735689600:test-hash",
        cloid=f"finbot_cloid_{intent_id}",
    )


def _start_session_with_intent(runtime, repo, intent_id="test-intent-1"):
    """Start a session and record a submitted intent with lifecycle."""
    runtime._start_session("test-strategy", "test-hash", "BTC", "1h")
    intent = _sample_intent(intent_id)
    repo.record_order_intent(intent)
    lifecycle = OrderLifecycle(
        order_id=intent_id,
        symbol="BTC",
        side="buy",
        original_size=Decimal("0.001"),
        state=OrderState.SUBMITTED,
    )
    repo._lifecycles[intent_id] = lifecycle
    repo._cloid_map[intent.cloid or ""] = intent_id
    return intent


# ---------------------------------------------------------------------------
# Scenario: Account websocket events update order lifecycle and fills
# ---------------------------------------------------------------------------


def test_accepted_update_moves_lifecycle_to_accepted() -> None:
    """Accepted order update moves lifecycle from SUBMITTED to ACCEPTED."""
    repo = FakeBotStateRepository()
    runtime = _make_runtime(repo)
    _start_session_with_intent(runtime, repo, "intent-1")

    result = runtime.process_account_event(
        {
            "type": "order_update",
            "order_id": "intent-1",
            "status": "accepted",
        }
    )

    lifecycle = repo._lifecycles.get("intent-1")
    assert lifecycle is not None
    assert lifecycle.state == OrderState.ACCEPTED
    assert result["status"] == "processed"


def test_open_update_moves_lifecycle_to_open() -> None:
    """Open order update moves lifecycle from ACCEPTED to OPEN."""
    repo = FakeBotStateRepository()
    runtime = _make_runtime(repo)
    _start_session_with_intent(runtime, repo, "intent-2")
    repo._lifecycles["intent-2"].state = OrderState.ACCEPTED

    runtime.process_account_event(
        {
            "type": "order_update",
            "order_id": "intent-2",
            "status": "open",
        }
    )

    assert repo._lifecycles["intent-2"].state == OrderState.OPEN


def test_partial_fill_persists_fill_and_updates_remaining_size() -> None:
    """Partial fill persists FillRecord and updates lifecycle remaining size."""
    repo = FakeBotStateRepository()
    runtime = _make_runtime(repo)
    _start_session_with_intent(runtime, repo, "intent-3")
    repo._lifecycles["intent-3"].state = OrderState.OPEN

    runtime.process_account_event(
        {
            "type": "fill",
            "order_id": "intent-3",
            "fill_id": "fill-1",
            "size": str(Decimal("0.0005")),
            "price": str(Decimal("50000")),
            "fee": str(Decimal("1.25")),
        }
    )

    lifecycle = repo._lifecycles["intent-3"]
    assert lifecycle.state == OrderState.PARTIALLY_FILLED
    assert lifecycle.filled_size == Decimal("0.0005")
    assert lifecycle.remaining_size == Decimal("0.0005")
    assert repo.count_fills() == 1


def test_duplicate_fill_is_idempotent() -> None:
    """Duplicate fill with same fill_id does not create duplicate records."""
    repo = FakeBotStateRepository()
    runtime = _make_runtime(repo)
    _start_session_with_intent(runtime, repo, "intent-4")
    repo._lifecycles["intent-4"].state = OrderState.OPEN

    fill_event = {
        "type": "fill",
        "order_id": "intent-4",
        "fill_id": "fill-2",
        "size": str(Decimal("0.0003")),
        "price": str(Decimal("51000")),
        "fee": str(Decimal("0.75")),
    }

    runtime.process_account_event(fill_event)
    assert repo.count_fills() == 1

    # Same fill again — should be ignored
    runtime.process_account_event(fill_event)
    assert repo.count_fills() == 1


def test_full_fill_moves_lifecycle_to_filled() -> None:
    """Full fill moves lifecycle to FILLED."""
    repo = FakeBotStateRepository()
    runtime = _make_runtime(repo)
    _start_session_with_intent(runtime, repo, "intent-5")
    repo._lifecycles["intent-5"].state = OrderState.OPEN

    runtime.process_account_event(
        {
            "type": "fill",
            "order_id": "intent-5",
            "fill_id": "fill-3",
            "size": str(Decimal("0.001")),  # Full size
            "price": str(Decimal("50000")),
            "fee": str(Decimal("2.50")),
        }
    )

    assert repo._lifecycles["intent-5"].state == OrderState.FILLED
    assert repo._lifecycles["intent-5"].remaining_size == Decimal("0")


def test_rejected_update_marks_lifecycle_rejected() -> None:
    """Rejected order update marks lifecycle as REJECTED."""
    repo = FakeBotStateRepository()
    runtime = _make_runtime(repo)
    _start_session_with_intent(runtime, repo, "intent-6")

    runtime.process_account_event(
        {
            "type": "order_update",
            "order_id": "intent-6",
            "status": "rejected",
        }
    )

    assert repo._lifecycles["intent-6"].state == OrderState.REJECTED


def test_cancelled_update_marks_lifecycle_cancelled() -> None:
    """Cancelled order update marks lifecycle as CANCELLED."""
    repo = FakeBotStateRepository()
    runtime = _make_runtime(repo)
    _start_session_with_intent(runtime, repo, "intent-7")
    repo._lifecycles["intent-7"].state = OrderState.OPEN

    runtime.process_account_event(
        {
            "type": "order_update",
            "order_id": "intent-7",
            "status": "cancelled",
        }
    )

    # A "cancelled" exchange status means the order is done — it reaches
    # the terminal CANCELLED state directly (not stuck in CANCEL_REQUESTED).
    assert repo._lifecycles["intent-7"].state == OrderState.CANCELLED


def test_unknown_order_update_blocks_new_orders() -> None:
    """Unknown order ID moves to UNKNOWN_RECONCILE_REQUIRED."""
    repo = FakeBotStateRepository()
    runtime = _make_runtime(repo)
    _start_session_with_intent(runtime, repo, "intent-8")
    repo._lifecycles["intent-8"].state = OrderState.SUBMITTED

    runtime.process_account_event(
        {
            "type": "order_update",
            "order_id": "intent-8",
            "status": "unknown",
        }
    )

    assert repo._lifecycles["intent-8"].state == OrderState.UNKNOWN_RECONCILE_REQUIRED


def test_fill_opens_trade_atomically() -> None:
    """A buy fill through AccountEventHandler opens a Trade.

    Regression test: TradeLedger.apply_fill must NOT see the fill as
    already recorded (has_fill returns False on first call) — the fill
    record and Trade update happen atomically but apply_fill must run
    before record_fill.
    """
    repo = FakeBotStateRepository()
    runtime = _make_runtime(repo)
    _start_session_with_intent(runtime, repo, "intent-9")
    repo._lifecycles["intent-9"].state = OrderState.OPEN

    runtime.process_account_event(
        {
            "type": "fill",
            "order_id": "intent-9",
            "fill_id": "fill-trade-1",
            "size": str(Decimal("0.1")),
            "price": str(Decimal("50000")),
            "fee": str(Decimal("0.5")),
        }
    )

    # A Trade should now be open.
    trade = repo.get_open_trade("BTC")
    assert trade is not None, (
        "Fill should have opened a Trade — apply_fill must run before "
        "record_fill so has_fill returns False on the first call"
    )
    assert trade.side.value == "long"
    assert trade.size == Decimal("0.1")
