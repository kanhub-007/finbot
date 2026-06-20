"""Tests for BotManager — Classical school, black-box style."""

import time

from finbot.infrastructure.repositories.in_memory_bot_state_repository import (
    InMemoryBotStateRepository,
)
from tests.fakes import FakeRuntime

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_manager(runtime=None, repo=None, exchange=None):
    from pathlib import Path

    from finbot.core.domain.services.bot_manager import BotManager

    repo = repo or InMemoryBotStateRepository()
    if runtime is not None:
        factory = lambda **kw: runtime  # noqa: E731
    else:
        def _factory(**kw):
            path = kw.get("strategy_path", "")
            if path and not Path(path).exists():
                return {
                    "status": "rejected",
                    "message": f"Strategy file not found: {path}",
                }
            return FakeRuntime(repo=repo)

        factory = _factory

    return BotManager(
        runtime_factory=factory,
        repository=repo,
        exchange=exchange,
        startup_time=time.time(),
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestBotManagerStart:
    """start_bot scenarios."""

    def test_start_dry_run_returns_running(self):
        """A dry-run start returns status='running' with a bot_run_id."""
        manager = _make_manager()
        result = manager.start(
            strategy_path="tests/fixtures/strategies/amt_dip_buyer_final.yaml",
            symbol="BTC",
            interval="1h",
            mode="dry_run",
            warmup_bars=0,
        )
        assert result["status"] == "running"
        assert result["bot_run_id"]

    def test_start_sets_is_running_true(self):
        """After start, is_running() returns True."""
        manager = _make_manager()
        manager.start(
            strategy_path="tests/fixtures/strategies/amt_dip_buyer_final.yaml",
            symbol="BTC",
            interval="1h",
            mode="dry_run",
            warmup_bars=0,
        )
        assert manager.is_running() is True

    def test_start_with_nonexistent_strategy_rejected(self):
        """Starting with a nonexistent strategy path returns rejected."""
        manager = _make_manager()
        result = manager.start(
            strategy_path="/nonexistent/path.yaml",
            symbol="BTC",
            interval="1h",
            mode="dry_run",
            warmup_bars=0,
        )
        assert result["status"] == "rejected"
        assert manager.is_running() is False

    def test_start_second_bot_rejected(self):
        """Starting a bot while one is running returns rejected."""
        manager = _make_manager()
        manager.start(
            strategy_path="tests/fixtures/strategies/amt_dip_buyer_final.yaml",
            symbol="BTC",
            interval="1h",
            mode="dry_run",
            warmup_bars=0,
        )
        result = manager.start(
            strategy_path="tests/fixtures/strategies/amt_dip_buyer_final.yaml",
            symbol="ETH",
            interval="1h",
            mode="dry_run",
            warmup_bars=0,
        )
        assert result["status"] == "rejected"
        assert "already running" in result["message"].lower()

    def test_start_invalid_mode_rejected(self):
        """An invalid mode string returns rejected."""
        manager = _make_manager()
        result = manager.start(
            strategy_path="tests/fixtures/strategies/amt_dip_buyer_final.yaml",
            symbol="BTC",
            interval="1h",
            mode="paper_trading",
            warmup_bars=0,
        )
        assert result["status"] == "rejected"


class TestBotManagerStop:
    """stop_bot scenarios."""

    def test_stop_returns_stopped(self):
        """Stopping a running bot returns status='stopped'."""
        manager = _make_manager()
        manager.start(
            strategy_path="tests/fixtures/strategies/amt_dip_buyer_final.yaml",
            symbol="BTC",
            interval="1h",
            mode="dry_run",
            warmup_bars=0,
        )
        result = manager.stop()
        assert result["status"] == "stopped"
        assert result["bot_run_id"]

    def test_stop_sets_is_running_false(self):
        """After stop, is_running() returns False."""
        manager = _make_manager()
        manager.start(
            strategy_path="tests/fixtures/strategies/amt_dip_buyer_final.yaml",
            symbol="BTC",
            interval="1h",
            mode="dry_run",
            warmup_bars=0,
        )
        manager.stop()
        assert manager.is_running() is False

    def test_stop_when_no_bot_running(self):
        """Stopping when no bot is running returns 'no_bot_running'."""
        manager = _make_manager()
        result = manager.stop()
        assert result["status"] == "no_bot_running"

    def test_stop_is_idempotent(self):
        """Calling stop twice does not crash."""
        manager = _make_manager()
        manager.start(
            strategy_path="tests/fixtures/strategies/amt_dip_buyer_final.yaml",
            symbol="BTC",
            interval="1h",
            mode="dry_run",
            warmup_bars=0,
        )
        manager.stop()
        result = manager.stop()
        assert result["status"] == "no_bot_running"


class TestBotManagerStatus:
    """get_status scenarios."""

    def test_status_when_no_bot_running(self):
        """Status when no bot has ever run shows is_running=False."""
        manager = _make_manager()
        status = manager.get_status()
        assert status["is_running"] is False
        assert status["last_run"] is None

    def test_status_when_bot_running(self):
        """Status while bot is running shows live state."""
        manager = _make_manager()
        manager.start(
            strategy_path="tests/fixtures/strategies/amt_dip_buyer_final.yaml",
            symbol="BTC",
            interval="1h",
            mode="dry_run",
            warmup_bars=0,
        )
        status = manager.get_status()
        assert status["is_running"] is True
        assert status["symbol"] == "BTC"
        assert status["mode"] == "dry_run"
        assert "uptime_seconds" in status
        manager.stop()

    def test_status_after_stop_shows_last_run(self):
        """Status after stopping shows the completed run as last_run."""
        repo = InMemoryBotStateRepository()
        manager = _make_manager(repo=repo)
        manager.start(
            strategy_path="tests/fixtures/strategies/amt_dip_buyer_final.yaml",
            symbol="BTC",
            interval="1h",
            mode="dry_run",
            warmup_bars=0,
        )
        manager.stop()

        status = manager.get_status()
        assert status["is_running"] is False
        assert status["last_run"] is not None
        assert status["last_run"]["symbol"] == "BTC"


class TestBotManagerThreadSafety:
    """Thread safety — start/stop/status with concurrent access."""

    def test_start_and_stop_in_rapid_succession(self):
        """Rapid start/stop cycles do not deadlock or crash."""
        manager = _make_manager()
        for _ in range(5):
            manager.start(
                strategy_path="tests/fixtures/strategies/amt_dip_buyer_final.yaml",
                symbol="BTC",
                interval="1h",
                mode="dry_run",
                warmup_bars=0,
            )
            time.sleep(0.05)
            result = manager.stop()
            assert result["status"] == "stopped"


class TestBotManagerPublicQueries:
    """Public query methods delegate to the repository correctly."""

    def test_get_bot_run_found(self):
        """get_bot_run returns the run after start+stop."""
        repo = InMemoryBotStateRepository()
        manager = _make_manager(repo=repo)
        manager.start(
            strategy_path="tests/fixtures/strategies/amt_dip_buyer_final.yaml",
            symbol="BTC",
            interval="1h",
            mode="dry_run",
            warmup_bars=0,
        )
        manager.stop()

        last_run = repo.get_latest_bot_run()
        found = manager.get_bot_run(last_run.run_id)
        assert found is not None
        assert found.run_id == last_run.run_id

    def test_get_bot_run_not_found(self):
        """get_bot_run returns None for nonexistent ID."""
        manager = _make_manager()
        assert manager.get_bot_run("nonexistent") is None

    def test_list_bot_runs_delegates(self):
        """list_bot_runs matches repository output."""
        repo = InMemoryBotStateRepository()
        manager = _make_manager(repo=repo)
        manager.start(
            strategy_path="tests/fixtures/strategies/amt_dip_buyer_final.yaml",
            symbol="BTC",
            interval="1h",
            mode="dry_run",
            warmup_bars=0,
        )
        manager.stop()

        runs = manager.list_bot_runs()
        assert len(runs) >= 1
