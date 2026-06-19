"""Concurrency tests for SqliteBotStateRepository (S1: H10 + M3).

The repository is shared across three threads in production:
  - the runtime thread (candle pipeline writes inside ``transaction()``)
  - the MCP status thread (read queries)
  - the Telegram thread (notifications + command flows)

A single ``sqlite3.Connection(check_same_thread=False)`` is **not** safe
for concurrent cursor use. These tests pin down the thread-safety
contract: concurrent writers must not lose writes, must not raise, and
must not commit/roll back each other's work.
"""

from __future__ import annotations

import threading
from decimal import Decimal

import pytest

from finbot.core.domain.entities.bot_run import BotRun
from finbot.core.domain.entities.fill_record import FillRecord
from finbot.core.domain.entities.processed_signal import ProcessedSignal
from finbot.infrastructure.repositories.sqlite_bot_state_repository import (
    SqliteBotStateRepository,
)
from finbot.infrastructure.repositories.sqlite_migrator import SqliteMigrator


@pytest.fixture
def migrated_db(tmp_path) -> str:
    """Return a path to a freshly-migrated SQLite file DB."""
    db_path = str(tmp_path / "concurrency.db")
    SqliteMigrator(db_path).migrate()
    # Seed a bot run so FK constraints are satisfied for fills.
    repo = SqliteBotStateRepository(db_path=db_path)
    repo.create_bot_run(
        BotRun(
            strategy_name="test",
            strategy_hash="abc",
            symbol="BTC",
            interval="1h",
            mode="dry_run",
            run_id="run",
        )
    )
    repo.close()
    return db_path


class TestSqliteConcurrency:
    def test_concurrent_writes_in_transactions_persist_exactly_once(
        self, migrated_db: str
    ) -> None:
        """Eight threads × 200 writes inside transaction() blocks.

        All writes must persist exactly once and no thread may raise.
        """
        repo = SqliteBotStateRepository(db_path=migrated_db)
        errors: list[Exception] = []
        thread_count = 8
        writes_per_thread = 200

        def writer(tid: int) -> None:
            try:
                for i in range(writes_per_thread):
                    with repo.transaction():
                        repo.mark_signal_processed(
                            ProcessedSignal(
                                signal_key=f"t{tid}-s{i}",
                                bot_run_id="run",
                                signal_action="long_entry",
                                bar_timestamp=str(i),
                            )
                        )
            except Exception as e:  # noqa: BLE001 - collect, don't swallow
                errors.append(e)

        threads = [
            threading.Thread(target=writer, args=(t,)) for t in range(thread_count)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        try:
            assert not errors, errors
            assert repo.count_signals() == thread_count * writes_per_thread
        finally:
            repo.close()

    def test_thread_a_rollback_does_not_undo_thread_b_commit(
        self, migrated_db: str
    ) -> None:
        """Thread A rolls back; Thread B commits in the same window.

        Thread B's committed row must survive; Thread A's rolled-back row
        must not be present. The per-thread transaction flag (threading.local)
        is what prevents the instance-flag bug from M3.
        """
        repo = SqliteBotStateRepository(db_path=migrated_db)
        b_started = threading.Event()
        b_committed = threading.Event()
        a_in_transaction = threading.Event()
        errors: list[Exception] = []

        def thread_a() -> None:
            try:
                with repo.transaction():
                    a_in_transaction.set()
                    repo.mark_signal_processed(
                        ProcessedSignal(
                            signal_key="a-rolledback",
                            bot_run_id="run",
                            signal_action="long_entry",
                            bar_timestamp="0",
                        )
                    )
                    # Wait until B has committed, then roll back.
                    b_committed.wait(timeout=5.0)
                    raise RuntimeError("intentional rollback in thread A")
            except RuntimeError:
                pass  # expected — the transaction rolled back
            except Exception as e:  # noqa: BLE001
                errors.append(e)

        def thread_b() -> None:
            try:
                a_in_transaction.wait(timeout=5.0)
                b_started.set()
                with repo.transaction():
                    repo.mark_signal_processed(
                        ProcessedSignal(
                            signal_key="b-committed",
                            bot_run_id="run",
                            signal_action="long_entry",
                            bar_timestamp="0",
                        )
                    )
                b_committed.set()
            except Exception as e:  # noqa: BLE001
                errors.append(e)

        ta = threading.Thread(target=thread_a)
        tb = threading.Thread(target=thread_b)
        ta.start()
        tb.start()
        ta.join(timeout=10.0)
        tb.join(timeout=10.0)

        try:
            assert not errors, errors
            # B's row survived, A's did not.
            assert repo.has_processed_signal("b-committed")
            assert not repo.has_processed_signal("a-rolledback")
        finally:
            repo.close()

    def test_read_from_third_thread_during_write_transaction_does_not_raise(
        self, migrated_db: str
    ) -> None:
        """A read query issued while another thread holds an open write
        transaction must not raise ``sqlite3.ProgrammingError``.
        """
        repo = SqliteBotStateRepository(db_path=migrated_db)
        write_started = threading.Event()
        write_done = threading.Event()
        read_errors: list[Exception] = []

        def writer() -> None:
            try:
                with repo.transaction():
                    write_started.set()
                    repo.mark_signal_processed(
                        ProcessedSignal(
                            signal_key="writer-signal",
                            bot_run_id="run",
                            signal_action="long_entry",
                            bar_timestamp="0",
                        )
                    )
                    # Hold the transaction open so the reader observes it.
                    write_done.wait(timeout=5.0)
            except Exception:  # noqa: BLE001 - writer failure is not under test
                pass

        def reader() -> None:
            try:
                write_started.wait(timeout=5.0)
                # Read while the writer holds an open transaction.
                repo.get_latest_bot_run()
                repo.count_signals()
            except Exception as e:  # noqa: BLE001
                read_errors.append(e)

        tw = threading.Thread(target=writer)
        tr = threading.Thread(target=reader)
        tw.start()
        tr.start()
        tr.join(timeout=10.0)
        write_done.set()
        tw.join(timeout=10.0)

        try:
            assert not read_errors, read_errors
        finally:
            repo.close()

    def test_sequential_writes_regression_guard(self, migrated_db: str) -> None:
        """1000 sequential writes (no concurrency) still produce 1000 rows.

        Guards against the synchronisation strategy accidentally dropping
        writes on the single-thread path.
        """
        repo = SqliteBotStateRepository(db_path=migrated_db)
        try:
            for i in range(1000):
                repo.mark_signal_processed(
                    ProcessedSignal(
                        signal_key=f"seq-{i}",
                        bot_run_id="run",
                        signal_action="long_entry",
                        bar_timestamp=str(i),
                    )
                )
            assert repo.count_signals() == 1000
        finally:
            repo.close()

    def test_concurrent_fills_persist_via_transaction(self, migrated_db: str) -> None:
        """Concurrent record_fill calls inside transaction() blocks.

        Fills carry generated fill_ids; each must persist exactly once.
        Exercises a different write path (record_fill) than the signals
        test so the lock covers every method.
        """
        repo = SqliteBotStateRepository(db_path=migrated_db)
        errors: list[Exception] = []
        thread_count = 4
        fills_per_thread = 50

        def filler(tid: int) -> None:
            try:
                for i in range(fills_per_thread):
                    with repo.transaction():
                        repo.record_fill(
                            FillRecord(
                                bot_run_id="run",
                                order_id=f"o-{tid}-{i}",
                                symbol="BTC",
                                side="buy",
                                size=Decimal("0.1"),
                                price=Decimal("50000"),
                                fee=Decimal("0"),
                                fill_id=f"f-{tid}-{i}",
                            )
                        )
            except Exception as e:  # noqa: BLE001
                errors.append(e)

        threads = [
            threading.Thread(target=filler, args=(t,)) for t in range(thread_count)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        try:
            assert not errors, errors
            assert repo.count_fills() == thread_count * fills_per_thread
        finally:
            repo.close()
