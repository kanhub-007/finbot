"""Tests for SqliteBotStateRepository."""

from decimal import Decimal

import pytest

from finbot.core.domain.entities.audit_log_entry import AuditLogEntry
from finbot.core.domain.entities.bot_run import BotRun
from finbot.core.domain.entities.fill_record import FillRecord
from finbot.core.domain.entities.order_intent import OrderIntent
from finbot.core.domain.entities.order_response_record import (
    OrderResponseRecord,
)
from finbot.core.domain.entities.order_side import OrderSide
from finbot.core.domain.entities.order_type import OrderType
from finbot.core.domain.entities.processed_signal import ProcessedSignal
from finbot.core.domain.entities.reconciliation_record import (
    ReconciliationRecord,
)
from finbot.core.domain.entities.risk_event_record import RiskEventRecord
from finbot.core.domain.entities.strategy_snapshot import StrategySnapshot
from finbot.infrastructure.repositories.sqlite_bot_state_repository import (
    SqliteBotStateRepository,
)
from finbot.infrastructure.repositories.sqlite_migrator import SqliteMigrator


def _db_path() -> str:
    """Return a unique in-memory path so each test gets a fresh DB."""
    import uuid

    return f"file:mem{uuid.uuid4().hex}?mode=memory&cache=shared"


@pytest.fixture
def repo() -> SqliteBotStateRepository:
    db_path = _db_path()
    SqliteMigrator(db_path).migrate()
    r = SqliteBotStateRepository(db_path)
    # Pre-seed a bot run so FK constraints are satisfied.
    r.create_bot_run(
        BotRun(
            strategy_name="test",
            strategy_hash="abc",
            symbol="BTC",
            interval="1h",
            mode="dry_run",
            run_id="r1",
        )
    )
    yield r
    r.close()


class TestSqliteBotStateRepository:
    def test_create_bot_run(self, repo: SqliteBotStateRepository) -> None:
        run = BotRun(
            strategy_name="amt_dip",
            strategy_hash="xyz",
            symbol="ETH",
            interval="1h",
            mode="dry_run",
        )
        repo.create_bot_run(run)
        assert run.run_id

    def test_store_strategy_snapshot(self, repo: SqliteBotStateRepository) -> None:
        snap = StrategySnapshot(
            bot_run_id="r1",
            strategy_hash="abc",
            full_yaml="name: test\n",
        )
        repo.store_strategy_snapshot(snap)

    def test_processed_signal_key_is_idempotent(
        self, repo: SqliteBotStateRepository
    ) -> None:
        sig = ProcessedSignal(
            signal_key="sig1",
            bot_run_id="r1",
            signal_action="long_entry",
            bar_timestamp="2025-01-01T09:00",
        )
        assert not repo.has_processed_signal("sig1")
        repo.mark_signal_processed(sig)
        assert repo.has_processed_signal("sig1")
        repo.mark_signal_processed(sig)
        assert repo.has_processed_signal("sig1")

    def test_order_intent_then_response(self, repo: SqliteBotStateRepository) -> None:
        intent = OrderIntent(
            symbol="BTC",
            side=OrderSide.BUY,
            size=Decimal("0.001"),
            order_type=OrderType.LIMIT,
            limit_price=Decimal("50000"),
        )
        intent_id = repo.record_order_intent(intent)
        assert intent_id

        resp = OrderResponseRecord(
            intent_id=intent_id,
            bot_run_id="r1",
            response_json='{"status":"ok"}',
            status="accepted",
        )
        repo.record_order_response(resp)

    def test_record_fill(self, repo: SqliteBotStateRepository) -> None:
        fill = FillRecord(
            bot_run_id="r1",
            order_id="oid1",
            symbol="BTC",
            side="buy",
            size=Decimal("0.001"),
            price=Decimal("50000"),
        )
        repo.record_fill(fill)

    def test_record_reconciliation(self, repo: SqliteBotStateRepository) -> None:
        rec = ReconciliationRecord(
            bot_run_id="r1",
            position_matches=True,
            open_orders_match=True,
        )
        repo.record_reconciliation(rec)

    def test_record_risk_event(self, repo: SqliteBotStateRepository) -> None:
        event = RiskEventRecord(
            bot_run_id="r1",
            event_type="stale_data",
            signal_key="sig1",
            decision="rejected",
            reason="data too old",
        )
        repo.record_risk_event(event)

    def test_append_audit_log(self, repo: SqliteBotStateRepository) -> None:
        entry = AuditLogEntry(
            bot_run_id="r1",
            event_type="signal",
            event_data_json='{"action":"long_entry"}',
        )
        repo.append_audit_log(entry)

    def test_repository_survives_new_session_restart(self) -> None:
        """Signal marked in one session persists across re-opens."""
        db_path = _db_path()
        SqliteMigrator(db_path).migrate()
        repo1 = SqliteBotStateRepository(db_path)
        repo1.create_bot_run(
            BotRun(
                strategy_name="t",
                strategy_hash="h",
                symbol="BTC",
                interval="1h",
                mode="dry_run",
                run_id="r1",
            )
        )
        repo1.mark_signal_processed(
            ProcessedSignal(
                signal_key="persistent",
                bot_run_id="r1",
                signal_action="long_entry",
                bar_timestamp="2025-01-01T09:00",
            )
        )
        repo1.close()

        repo2 = SqliteBotStateRepository(db_path)
        assert repo2.has_processed_signal("persistent")
        repo2.close()

    def test_order_lifecycle_round_trips(self, repo: SqliteBotStateRepository) -> None:
        """Saving then loading an order lifecycle preserves state and sizes."""
        from finbot.core.domain.entities.order_lifecycle import OrderLifecycle
        from finbot.core.domain.entities.order_state import OrderState

        lifecycle = OrderLifecycle(
            order_id="oid-1",
            symbol="BTC",
            side="buy",
            original_size=Decimal("0.002"),
            state=OrderState.SUBMITTED,
        )
        repo.save_order_lifecycle(lifecycle)

        loaded = repo.get_order_lifecycle("oid-1")
        assert loaded is not None
        assert loaded.symbol == "BTC"
        assert loaded.side == "buy"
        assert loaded.original_size == Decimal("0.002")
        assert loaded.remaining_size == Decimal("0.002")
        assert loaded.state == OrderState.SUBMITTED

    def test_order_lifecycle_update_persists_new_state(self, repo) -> None:
        """A second save upserts the row rather than duplicating it."""
        from finbot.core.domain.entities.order_lifecycle import OrderLifecycle
        from finbot.core.domain.entities.order_state import OrderState

        lifecycle = OrderLifecycle(
            order_id="oid-2",
            symbol="BTC",
            side="buy",
            original_size=Decimal("0.001"),
            state=OrderState.SUBMITTED,
        )
        repo.save_order_lifecycle(lifecycle)
        lifecycle.state = OrderState.OPEN
        repo.save_order_lifecycle(lifecycle)

        loaded = repo.get_order_lifecycle("oid-2")
        assert loaded is not None
        assert loaded.state == OrderState.OPEN

    def test_transaction_rolls_back_on_exception(self) -> None:
        """Writes inside a failed transaction() must not persist."""
        db_path = _db_path()
        SqliteMigrator(db_path).migrate()
        repo = SqliteBotStateRepository(db_path)
        repo.create_bot_run(
            BotRun(
                strategy_name="t",
                strategy_hash="h",
                symbol="BTC",
                interval="1h",
                mode="dry_run",
                run_id="r1",
            )
        )
        try:
            with repo.transaction():
                repo.mark_signal_processed(
                    ProcessedSignal(
                        signal_key="tx-signal",
                        bot_run_id="r1",
                        signal_action="long_entry",
                        bar_timestamp="2025-01-01T09:00",
                    )
                )
                raise RuntimeError("boom")
        except RuntimeError:
            pass

        assert not repo.has_processed_signal("tx-signal")
        repo.close()

    def test_transaction_commits_on_success(self) -> None:
        """Writes inside a successful transaction() persist atomically."""
        db_path = _db_path()
        SqliteMigrator(db_path).migrate()
        repo = SqliteBotStateRepository(db_path)
        repo.create_bot_run(
            BotRun(
                strategy_name="t",
                strategy_hash="h",
                symbol="BTC",
                interval="1h",
                mode="dry_run",
                run_id="r1",
            )
        )
        with repo.transaction():
            repo.mark_signal_processed(
                ProcessedSignal(
                    signal_key="tx-ok",
                    bot_run_id="r1",
                    signal_action="long_entry",
                    bar_timestamp="2025-01-01T09:00",
                )
            )
        assert repo.has_processed_signal("tx-ok")
        repo.close()
