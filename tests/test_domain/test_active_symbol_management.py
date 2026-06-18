"""Tests for active symbol state management — Classical school, black-box.

Covers the trading-control spec: the bot starts fully idle (no active symbol),
and an active symbol must be selected before manual orders / leverage work.
"""

import time

from finbot.infrastructure.repositories.in_memory_bot_state_repository import (
    InMemoryBotStateRepository,
)
from tests.fakes import FakeExchangeGateway


def _make_manager(repo=None, exchange=None):
    """Build a real BotManager with in-memory fakes at the boundaries."""
    from finbot.core.domain.services.bot_manager import BotManager

    repo = repo or InMemoryBotStateRepository()
    factory = lambda **kw: None  # noqa: E731 — runtime not needed for state tests
    return BotManager(
        runtime_factory=factory,
        repository=repo,
        exchange=exchange or FakeExchangeGateway(),
        startup_time=time.time(),
    )


class TestActivateSymbol:
    """Scenario 2: /symbol activates a symbol and reads exchange leverage."""

    def test_activate_symbol_sets_active_symbol(self):
        """activate_symbol('BTC') makes get_active_symbol() return BTC state."""
        manager = _make_manager()
        result = manager.activate_symbol("BTC")

        assert result["status"] == "active"
        assert result["symbol"] == "BTC"

        active = manager.get_active_symbol()
        assert active is not None
        assert active.symbol == "BTC"

    def test_activate_symbol_reads_leverage_does_not_set(self):
        """Activating reads leverage from exchange; set_leverage is NOT called."""
        exchange = FakeExchangeGateway()
        exchange.leverage_to_report = (5, "isolated")
        manager = _make_manager(exchange=exchange)

        manager.activate_symbol("BTC")

        # set_leverage must NOT be called on /symbol (spec: read-only)
        assert exchange.set_leverage_calls == []
        # The active state reflects the exchange-reported leverage
        active = manager.get_active_symbol()
        assert active is not None
        assert active.leverage == 5
        assert active.margin_mode == "isolated"

    def test_activate_symbol_falls_back_to_1x_when_exchange_has_no_leverage(self):
        """If exchange can't report leverage, default to 1x isolated."""
        exchange = FakeExchangeGateway()
        exchange.leverage_to_report = None  # simulate unreadable
        manager = _make_manager(exchange=exchange)

        manager.activate_symbol("BTC")

        active = manager.get_active_symbol()
        assert active is not None
        assert active.leverage == 1
        assert active.margin_mode == "isolated"

    def test_activate_symbol_blocked_when_strategy_running(self):
        """Switching symbol while a strategy runs is a hard block."""
        from tests.fakes import FakeRuntime

        repo = InMemoryBotStateRepository()
        runtime = FakeRuntime(repo=repo)
        factory = lambda **kw: runtime  # noqa: E731
        from finbot.core.domain.services.bot_manager import BotManager

        manager = BotManager(
            runtime_factory=factory,
            repository=repo,
            exchange=FakeExchangeGateway(),
            startup_time=time.time(),
        )
        manager.activate_symbol("BTC")
        manager.start(
            strategy_path="tests/fixtures/strategies/amt_dip_buyer_final.yaml",
            symbol="BTC",
            interval="1h",
            mode="dry_run",
            warmup_bars=0,
        )

        result = manager.activate_symbol("ETH")

        assert result["status"] == "rejected"
        assert "stop" in result["message"].lower()
        # Active symbol unchanged
        assert manager.get_active_symbol().symbol == "BTC"


class TestBotStartsIdle:
    """Scenario 1: Bot starts fully idle — no symbol, no strategy, no position."""

    def test_fresh_manager_has_no_active_symbol(self):
        """On startup, get_active_symbol() returns None."""
        manager = _make_manager()
        assert manager.get_active_symbol() is None

    def test_fresh_manager_is_not_running_strategy(self):
        """On startup, no strategy is running."""
        manager = _make_manager()
        assert manager.is_running() is False
