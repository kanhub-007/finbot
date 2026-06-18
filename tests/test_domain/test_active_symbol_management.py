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


class TestSetLeverage:
    """Scenario 5: /leverage sets leverage with symbol-aware validation."""

    def test_set_leverage_updates_active_state_and_exchange(self):
        """set_leverage(5) calls exchange + updates ActiveSymbolState."""
        exchange = FakeExchangeGateway()
        manager = _make_manager(exchange=exchange)
        manager.activate_symbol("BTC")

        result = manager.set_leverage(5)

        assert result["status"] == "ok"
        assert ("BTC", 5, "isolated") in exchange.set_leverage_calls
        active = manager.get_active_symbol()
        assert active.leverage == 5
        assert active.margin_mode == "isolated"

    def test_set_leverage_cross_margin(self):
        """set_leverage(5, 'cross') sets cross margin."""
        exchange = FakeExchangeGateway()
        manager = _make_manager(exchange=exchange)
        manager.activate_symbol("BTC")

        manager.set_leverage(5, margin_mode="cross")

        assert ("BTC", 5, "cross") in exchange.set_leverage_calls
        assert manager.get_active_symbol().margin_mode == "cross"

    def test_set_leverage_requires_active_symbol(self):
        """No active symbol → rejected."""
        manager = _make_manager()

        result = manager.set_leverage(5)

        assert result["status"] == "rejected"
        assert "symbol" in result["message"].lower()

    def test_set_leverage_rejects_above_max(self):
        """leverage > symbol max_leverage → rejected."""
        from tests.fakes import InMemoryMarketMetadataProvider

        meta = InMemoryMarketMetadataProvider.for_btc()
        exchange = FakeExchangeGateway()
        manager = _make_manager(exchange=exchange)
        manager._metadata_provider = meta
        manager.activate_symbol("BTC")

        result = manager.set_leverage(60)  # BTC max is 50

        assert result["status"] == "rejected"
        assert "50" in result["message"]
        assert exchange.set_leverage_calls == []

    def test_set_leverage_rejects_zero(self):
        """leverage < 1 → rejected."""
        exchange = FakeExchangeGateway()
        manager = _make_manager(exchange=exchange)
        manager.activate_symbol("BTC")

        result = manager.set_leverage(0)

        assert result["status"] == "rejected"
        assert exchange.set_leverage_calls == []


class TestGetPosition:
    """Scenario 6: /position shows current position + PnL."""

    def test_get_active_position_returns_exchange_position(self):
        """get_active_position() returns the position for the active symbol."""
        from finbot.core.domain.entities.position_direction import PositionDirection
        from finbot.core.domain.entities.position_snapshot import PositionSnapshot

        exchange = FakeExchangeGateway()
        exchange._position = PositionSnapshot(
            symbol="BTC",
            direction=PositionDirection.LONG,
            size=Decimal("0.01"),
            entry_price=Decimal("95000"),
            unrealized_pnl=Decimal("12"),
        )
        manager = _make_manager(exchange=exchange)
        manager.activate_symbol("BTC")

        position = manager.get_active_position()

        assert position is not None
        assert position.direction == PositionDirection.LONG
        assert position.size == Decimal("0.01")
        assert position.unrealized_pnl == Decimal("12")

    def test_get_active_position_none_when_idle(self):
        """No active symbol → get_active_position() returns None."""
        manager = _make_manager()

        assert manager.get_active_position() is None

    def test_get_active_position_flat_when_no_position(self):
        """Active symbol but no position → returns a FLAT snapshot."""
        from finbot.core.domain.entities.position_direction import PositionDirection

        manager = _make_manager()
        manager.activate_symbol("BTC")

        position = manager.get_active_position()

        assert position is not None
        assert position.direction == PositionDirection.FLAT


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
