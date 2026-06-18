"""Tests for active symbol state management — Classical school, black-box.

Covers the trading-control spec: the bot starts fully idle (no active symbol),
and an active symbol must be selected before manual orders / leverage work.
"""

import time
from decimal import Decimal

from finbot.infrastructure.repositories.in_memory_bot_state_repository import (
    InMemoryBotStateRepository,
)
from tests.fakes import FakeExchangeGateway


_NO_EXCHANGE = object()


def _make_manager(repo=None, exchange=_NO_EXCHANGE):
    """Build a real BotManager with in-memory fakes at the boundaries."""
    from finbot.core.domain.services.bot_manager import BotManager

    repo = repo or InMemoryBotStateRepository()
    factory = lambda **kw: None  # noqa: E731 — runtime not needed for state tests
    return BotManager(
        runtime_factory=factory,
        repository=repo,
        exchange=FakeExchangeGateway() if exchange is _NO_EXCHANGE else exchange,
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


class TestGetPrice:
    """Scenario 3: /price shows current price for the active symbol."""

    def test_get_active_price_returns_exchange_price(self):
        """get_active_price() returns the exchange price for the active symbol."""
        exchange = FakeExchangeGateway()
        exchange.price_to_report = Decimal("96250.50")
        manager = _make_manager(exchange=exchange)
        manager.activate_symbol("BTC")

        price = manager.get_active_price()

        assert price == Decimal("96250.50")

    def test_get_active_price_requires_active_symbol(self):
        """With no active symbol, get_active_price() returns None."""
        manager = _make_manager()

        price = manager.get_active_price()

        assert price is None


class TestGetBalance:
    """Scenario 4: /balance shows wallet balance."""

    def test_get_balance_returns_exchange_balance(self):
        """get_balance() returns the exchange-reported wallet balance."""
        from finbot.core.domain.entities.wallet_balance import WalletBalance

        exchange = FakeExchangeGateway()
        exchange.balance_to_report = WalletBalance(
            wallet_value=Decimal("1250"),
            margin_used=Decimal("300"),
            available=Decimal("950"),
        )
        manager = _make_manager(exchange=exchange)

        balance = manager.get_balance()

        assert balance.wallet_value == Decimal("1250")
        assert balance.margin_used == Decimal("300")
        assert balance.available == Decimal("950")

    def test_get_balance_returns_none_without_exchange(self):
        """No exchange wired → get_balance() returns None."""
        manager = _make_manager(exchange=None)

        balance = manager.get_balance()

        assert balance is None


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
