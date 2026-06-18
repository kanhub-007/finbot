"""Tests that the runtime batches per-candle writes into one SQLite commit (P7)."""

from decimal import Decimal

from finbot.core.domain.entities.market_metadata import MarketMetadata
from finbot.core.domain.entities.signal_action import SignalAction
from finbot.core.domain.entities.signal_decision import SignalDecision
from finbot.core.domain.entities.trading_mode import TradingMode
from finbot.core.domain.services.cloid_generator import CloidGenerator
from finbot.core.domain.services.enrichment_validator import EnrichmentValidator
from finbot.core.domain.services.order_normalizer import OrderNormalizer
from finbot.core.domain.services.order_planner import OrderPlanner
from finbot.core.domain.services.risk_gates.mode_gate import ModeGate
from finbot.infrastructure.repositories.sqlite_bot_state_repository import (
    SqliteBotStateRepository,
)
from finbot.infrastructure.repositories.sqlite_migrator import SqliteMigrator
from tests.fakes import (
    FakeExchangeGateway,
    FakeStrategyEvaluator,
    InMemoryBarFrameConverter,
    InMemoryIndicatorEngine,
    closed_warmup_bars,
    indicator_bar,
    make_event_emitter,
    new_closed_candle,
)

from finbot.infrastructure.adapters.live_submission_strategy import (
    LiveSubmissionStrategy,
)


def _db_path() -> str:
    import uuid

    return f"file:mem{uuid.uuid4().hex}?mode=memory&cache=shared"


def _sqlite_repo() -> SqliteBotStateRepository:
    db = _db_path()
    SqliteMigrator(db).migrate()
    repo = SqliteBotStateRepository(db)
    repo.create_bot_run  # ensure exists
    from finbot.core.domain.entities.bot_run import BotRun

    repo.create_bot_run(
        BotRun(
            strategy_name="t",
            strategy_hash="h",
            symbol="BTC",
            interval="1h",
            mode="testnet",
        )
    )
    return repo


def test_accepted_candle_uses_one_transaction() -> None:
    """All per-candle writes go through a single repo.transaction() block."""
    repo = _sqlite_repo()
    tx_entries = []
    real_tx = repo.transaction

    from contextlib import contextmanager

    @contextmanager
    def counting_tx():
        tx_entries.append("enter")
        with real_tx():
            yield
        tx_entries.append("exit")

    repo.transaction = counting_tx  # type: ignore[assignment]

    from finbot.core.application.use_cases.live_trading_runtime import (
        LiveTradingRuntimeUseCase,
    )

    runtime = LiveTradingRuntimeUseCase(
        exchange_gateway=FakeExchangeGateway(),
        strategy_evaluator=FakeStrategyEvaluator(
            signal=SignalDecision(
                action=SignalAction.LONG_ENTRY,
                symbol="BTC",
                interval="1h",
                candle_timestamp=1735689600,
                strategy_hash="h",
            )
        ),
        state_repository=repo,
        indicator_calculator=InMemoryIndicatorEngine(
            latest_bar=indicator_bar(atr=1200.0)
        ),
        enrichment_validator=EnrichmentValidator(),
        bar_frame_converter=InMemoryBarFrameConverter(),
        mode=TradingMode.TESTNET,
        submission_strategy=LiveSubmissionStrategy(
            FakeExchangeGateway(), None, repo
        ),
        event_emitter=make_event_emitter(),
        warmup_bars=closed_warmup_bars(100),
        required_columns={"atr"},
        order_planner=OrderPlanner(gates=[ModeGate()]),
        order_normalizer=OrderNormalizer(
            metadata=MarketMetadata(
                symbol="BTC", sz_decimals=5, price_tick=Decimal("0.1")
            )
        ),
        cloid_generator=CloidGenerator(),
    )
    runtime._start_session("s", "h", "BTC", "1h")

    runtime.process_closed_candle(new_closed_candle())

    # Exactly one transaction wraps all the per-candle writes.
    assert tx_entries.count("enter") == 1
    assert tx_entries.count("exit") == 1
