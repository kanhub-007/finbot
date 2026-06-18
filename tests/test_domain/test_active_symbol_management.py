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


class TestRuntimeConfig:
    """Scenario 13: /config views and adjusts runtime settings."""

    def test_default_config_has_safe_defaults(self):
        """Fresh manager exposes safe default risk limits."""
        manager = _make_manager()
        cfg = manager.get_bot_config()

        assert cfg.max_position_usd == Decimal("100")
        assert cfg.max_daily_loss_usd == Decimal("25")
        assert cfg.max_open_orders == 3
        assert cfg.stale_data_seconds == 120

    def test_update_max_position_takes_effect_immediately(self):
        """update_bot_config('max_position', '500') updates the live config."""
        manager = _make_manager()

        result = manager.update_bot_config("max_position", "500")

        assert result["status"] == "ok"
        assert manager.get_bot_config().max_position_usd == Decimal("500")

    def test_update_unknown_key_rejected(self):
        """Unknown key → rejected with available keys listed."""
        manager = _make_manager()

        result = manager.update_bot_config("nonsense", "1")

        assert result["status"] == "rejected"
        assert "max_position" in result["message"]

    def test_update_non_numeric_rejected(self):
        """Non-numeric value for numeric key → rejected."""
        manager = _make_manager()

        result = manager.update_bot_config("max_position", "abc")

        assert result["status"] == "rejected"
        assert "number" in result["message"].lower()

    def test_update_negative_rejected(self):
        """Negative value → rejected."""
        manager = _make_manager()

        result = manager.update_bot_config("max_position", "-100")

        assert result["status"] == "rejected"

    def test_update_daily_loss_key(self):
        """'daily_loss' is the short key for max_daily_loss_usd."""
        manager = _make_manager()

        manager.update_bot_config("daily_loss", "50")

        assert manager.get_bot_config().max_daily_loss_usd == Decimal("50")


class TestSubmitManualOrder:
    """Scenario 7: /long opens a long position (and /short mirrors it)."""

    def test_submit_buy_places_market_order(self):
        """submit_manual_order(BUY, 0.01) submits a market buy on the symbol."""
        from finbot.core.domain.entities.order_side import OrderSide

        exchange = FakeExchangeGateway()
        exchange.price_to_report = Decimal("50000")
        manager = _make_manager(exchange=exchange)
        manager.activate_symbol("BTC")
        manager.update_bot_config("max_position", "10000")

        result = manager.submit_manual_order(OrderSide.BUY, Decimal("0.01"))

        assert result["status"] == "ok"
        assert len(exchange.submitted_intents) == 1
        intent = exchange.submitted_intents[0]
        assert intent.side == OrderSide.BUY
        assert intent.size == Decimal("0.01")
        assert intent.symbol == "BTC"

    def test_submit_sell_places_market_order(self):
        """submit_manual_order(SELL, 0.01) submits a market sell."""
        from finbot.core.domain.entities.order_side import OrderSide

        exchange = FakeExchangeGateway()
        exchange.price_to_report = Decimal("50000")
        manager = _make_manager(exchange=exchange)
        manager.activate_symbol("BTC")
        manager.update_bot_config("max_position", "10000")

        manager.submit_manual_order(OrderSide.SELL, Decimal("0.01"))

        assert exchange.submitted_intents[0].side == OrderSide.SELL

    def test_submit_requires_active_symbol(self):
        """No active symbol → rejected."""
        from finbot.core.domain.entities.order_side import OrderSide

        manager = _make_manager()

        result = manager.submit_manual_order(OrderSide.BUY, Decimal("0.01"))

        assert result["status"] == "rejected"
        assert "symbol" in result["message"].lower()

    def test_submit_blocked_when_strategy_running(self):
        """Manual orders are hard-blocked while a strategy runs."""
        from finbot.core.domain.entities.order_side import OrderSide
        from tests.fakes import FakeRuntime

        repo = InMemoryBotStateRepository()
        runtime = FakeRuntime(repo=repo)
        from finbot.core.domain.services.bot_manager import BotManager

        manager = BotManager(
            runtime_factory=lambda **kw: runtime,
            repository=repo,
            exchange=FakeExchangeGateway(),
            startup_time=time.time(),
        )
        manager.activate_symbol("BTC")
        manager.start(
            strategy_path="tests/fixtures/strategies/amt_dip_buyer_final.yaml",
            symbol="BTC", interval="1h", mode="dry_run", warmup_bars=0,
        )

        result = manager.submit_manual_order(OrderSide.BUY, Decimal("0.01"))

        assert result["status"] == "rejected"
        assert "stop" in result["message"].lower()

    def test_submit_blocked_when_position_open(self):
        """Existing position → rejected (close first)."""
        from finbot.core.domain.entities.order_side import OrderSide
        from finbot.core.domain.entities.position_direction import PositionDirection
        from finbot.core.domain.entities.position_snapshot import PositionSnapshot

        exchange = FakeExchangeGateway()
        exchange._position = PositionSnapshot(
            symbol="BTC", direction=PositionDirection.LONG, size=Decimal("0.01")
        )
        manager = _make_manager(exchange=exchange)
        manager.activate_symbol("BTC")

        result = manager.submit_manual_order(OrderSide.BUY, Decimal("0.01"))

        assert result["status"] == "rejected"
        assert "close" in result["message"].lower()
        assert exchange.submitted_intents == []

    def test_submit_blocked_by_max_position_gate(self):
        """Notional over config limit → rejected with reason."""
        from finbot.core.domain.entities.order_side import OrderSide

        exchange = FakeExchangeGateway()
        exchange.price_to_report = Decimal("50000")
        manager = _make_manager(exchange=exchange)
        manager.activate_symbol("BTC")
        manager.update_bot_config("max_position", "100")  # 0.01*50000=500 > 100

        result = manager.submit_manual_order(OrderSide.BUY, Decimal("0.01"))

        assert result["status"] == "rejected"
        assert "100" in result["message"]
        assert exchange.submitted_intents == []

    def test_submit_invalid_size_rejected(self):
        """Size <= 0 → rejected."""
        from finbot.core.domain.entities.order_side import OrderSide

        exchange = FakeExchangeGateway()
        manager = _make_manager(exchange=exchange)
        manager.activate_symbol("BTC")

        result = manager.submit_manual_order(OrderSide.BUY, Decimal("-0.01"))

        assert result["status"] == "rejected"
        assert "positive" in result["message"].lower() or "size" in result["message"].lower()


class TestCloseActivePosition:
    """Scenario 9: /close closes the current position and clears SL/TP."""

    def test_close_submits_reduce_only_market(self):
        """close_active_position submits a reduce-only market close."""
        from finbot.core.domain.entities.position_direction import PositionDirection
        from finbot.core.domain.entities.position_snapshot import PositionSnapshot

        exchange = FakeExchangeGateway()
        exchange._position = PositionSnapshot(
            symbol="BTC", direction=PositionDirection.LONG, size=Decimal("0.01")
        )
        manager = _make_manager(exchange=exchange)
        manager.activate_symbol("BTC")

        result = manager.close_active_position()

        assert result["status"] == "ok"
        assert len(exchange.submitted_intents) == 1
        intent = exchange.submitted_intents[0]
        assert intent.reduce_only is True

    def test_close_no_position(self):
        """No open position → message."""
        exchange = FakeExchangeGateway()
        manager = _make_manager(exchange=exchange)
        manager.activate_symbol("BTC")

        result = manager.close_active_position()

        assert result["status"] == "rejected"
        assert "no" in result["message"].lower() and "position" in result["message"].lower()

    def test_close_requires_active_symbol(self):
        """No active symbol → rejected."""
        manager = _make_manager()

        result = manager.close_active_position()

        assert result["status"] == "rejected"
        assert "symbol" in result["message"].lower()


class TestClearAll:
    """Scenario 10: /clear closes all + cancels all orders (idle only)."""

    def test_clear_cancels_orders_and_closes_position(self):
        """clear_all cancels orders + closes position on the active symbol."""
        from finbot.core.domain.entities.position_direction import PositionDirection
        from finbot.core.domain.entities.position_snapshot import PositionSnapshot

        exchange = FakeExchangeGateway()
        exchange._position = PositionSnapshot(
            symbol="BTC", direction=PositionDirection.LONG, size=Decimal("0.01")
        )
        manager = _make_manager(exchange=exchange)
        manager.activate_symbol("BTC")

        result = manager.clear_all()

        assert result["status"] == "ok"
        assert result["cancelled_orders"] >= 0
        assert result["closed_positions"] >= 1

    def test_clear_blocked_when_strategy_running(self):
        """Strategy running → hard block (use /panic for emergency)."""
        from tests.fakes import FakeRuntime

        repo = InMemoryBotStateRepository()
        runtime = FakeRuntime(repo=repo)
        from finbot.core.domain.services.bot_manager import BotManager

        manager = BotManager(
            runtime_factory=lambda **kw: runtime,
            repository=repo,
            exchange=FakeExchangeGateway(),
            startup_time=time.time(),
        )
        manager.activate_symbol("BTC")
        manager.start(
            strategy_path="tests/fixtures/strategies/amt_dip_buyer_final.yaml",
            symbol="BTC", interval="1h", mode="dry_run", warmup_bars=0,
        )

        result = manager.clear_all()

        assert result["status"] == "rejected"
        assert "stop" in result["message"].lower()

    def test_clear_nothing_to_clear(self):
        """No position, no orders → 'Nothing to clear'."""
        exchange = FakeExchangeGateway()
        manager = _make_manager(exchange=exchange)
        manager.activate_symbol("BTC")

        result = manager.clear_all()

        assert result["status"] == "rejected"
        assert "nothing" in result["message"].lower()


class TestStopLossAndTakeProfit:
    """Scenarios 11 & 12: /sl and /tp attach reduce-only trigger orders."""

    def _long_manager(self):
        from finbot.core.domain.entities.position_direction import PositionDirection
        from finbot.core.domain.entities.position_snapshot import PositionSnapshot

        exchange = FakeExchangeGateway()
        exchange._position = PositionSnapshot(
            symbol="BTC",
            direction=PositionDirection.LONG,
            size=Decimal("0.01"),
            entry_price=Decimal("95000"),
        )
        manager = _make_manager(exchange=exchange)
        manager.activate_symbol("BTC")
        return manager, exchange

    def test_attach_stop_loss_places_trigger_with_cloid(self):
        """attach_stop_loss places a reduce-only order with cloid SL:BTC."""
        manager, exchange = self._long_manager()

        result = manager.attach_stop_loss(Decimal("94000"))

        assert result["status"] == "ok"
        assert len(exchange.submitted_intents) == 1
        intent = exchange.submitted_intents[0]
        assert intent.cloid == "SL:BTC"
        assert intent.reduce_only is True

    def test_attach_take_profit_places_trigger_with_cloid(self):
        """attach_take_profit places a reduce-only order with cloid TP:BTC."""
        manager, exchange = self._long_manager()

        result = manager.attach_take_profit(Decimal("97000"))

        assert result["status"] == "ok"
        intent = exchange.submitted_intents[0]
        assert intent.cloid == "TP:BTC"
        assert intent.reduce_only is True

    def test_sl_rejects_above_entry_for_long(self):
        """SL above entry on a long → rejected."""
        manager, exchange = self._long_manager()

        result = manager.attach_stop_loss(Decimal("100000"))

        assert result["status"] == "rejected"
        assert exchange.submitted_intents == []

    def test_tp_rejects_below_entry_for_long(self):
        """TP below entry on a long → rejected."""
        manager, exchange = self._long_manager()

        result = manager.attach_take_profit(Decimal("90000"))

        assert result["status"] == "rejected"
        assert exchange.submitted_intents == []

    def test_sl_requires_open_position(self):
        """No position → rejected."""
        manager = _make_manager()
        manager.activate_symbol("BTC")

        result = manager.attach_stop_loss(Decimal("94000"))

        assert result["status"] == "rejected"
        assert "position" in result["message"].lower()

    def test_clear_risk_order_cancels_by_cloid(self):
        """clear_risk_order('sl') cancels the SL:BTC order."""
        manager, exchange = self._long_manager()
        manager.attach_stop_loss(Decimal("94000"))

        result = manager.clear_risk_order("sl")

        assert result["status"] == "ok"

    def test_sl_blocked_when_strategy_running(self):
        """SL/TP hard-blocked while a strategy runs."""
        from tests.fakes import FakeRuntime

        repo = InMemoryBotStateRepository()
        runtime = FakeRuntime(repo=repo)
        from finbot.core.domain.entities.position_direction import PositionDirection
        from finbot.core.domain.entities.position_snapshot import PositionSnapshot
        from finbot.core.domain.services.bot_manager import BotManager

        exchange = FakeExchangeGateway()
        exchange._position = PositionSnapshot(
            symbol="BTC", direction=PositionDirection.LONG, size=Decimal("0.01")
        )
        manager = BotManager(
            runtime_factory=lambda **kw: runtime,
            repository=repo,
            exchange=exchange,
            startup_time=time.time(),
        )
        manager.activate_symbol("BTC")
        manager.start(
            strategy_path="tests/fixtures/strategies/amt_dip_buyer_final.yaml",
            symbol="BTC", interval="1h", mode="dry_run", warmup_bars=0,
        )

        result = manager.attach_stop_loss(Decimal("94000"))

        assert result["status"] == "rejected"
        assert "stop" in result["message"].lower()


class TestActiveSymbolPersistence:
    """Scenario 15: ActiveSymbolState persists so leverage survives restart."""

    def test_activate_persists_to_repository(self):
        """activate_symbol writes ActiveSymbolState to the repository."""
        repo = InMemoryBotStateRepository()
        manager = _make_manager(repo=repo)
        manager.activate_symbol("BTC")

        persisted = repo.load_active_symbol()
        assert persisted is not None
        assert persisted.symbol == "BTC"

    def test_set_leverage_updates_persisted_state(self):
        """set_leverage updates the persisted ActiveSymbolState."""
        repo = InMemoryBotStateRepository()
        manager = _make_manager(repo=repo)
        manager.activate_symbol("BTC")
        manager.set_leverage(5)

        persisted = repo.load_active_symbol()
        assert persisted is not None
        assert persisted.leverage == 5

    def test_new_manager_restores_persisted_symbol(self):
        """A fresh BotManager with the same repo restores the active symbol."""
        repo = InMemoryBotStateRepository()
        manager_a = _make_manager(repo=repo)
        manager_a.activate_symbol("BTC")
        manager_a.set_leverage(5)

        manager_b = _make_manager(repo=repo)

        active = manager_b.get_active_symbol()
        assert active is not None
        assert active.symbol == "BTC"
        assert active.leverage == 5


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


class TestConfigDefaultsFromEnv:
    """Scenario 2 (Slice 2): .env provides startup defaults for BotConfig."""

    def test_settings_seed_runtime_config(self):
        """Settings max_position/daily_loss seed the RuntimeBotConfig."""
        from finbot.core.domain.entities.runtime_bot_config import RuntimeBotConfig
        from finbot.core.domain.services.bot_manager import BotManager

        class FakeSettings:
            mode = "dry_run"
            live_trading_ack = False
            max_position_usd = Decimal("500")
            max_daily_loss_usd = Decimal("75")
            max_open_orders = 5
            stale_data_seconds = 60

        repo = InMemoryBotStateRepository()
        manager = BotManager(
            runtime_factory=lambda **kw: None,
            repository=repo,
            settings=FakeSettings(),
            startup_time=time.time(),
        )

        cfg = manager.get_bot_config()
        assert cfg.max_position_usd == Decimal("500")
        assert cfg.max_daily_loss_usd == Decimal("75")
        assert cfg.max_open_orders == 5
        assert cfg.stale_data_seconds == 60


class TestDefaultOrderSize:
    """Scenario 3 (Slice 2): /size sets a default for /long and /short."""

    def test_set_default_size_stored(self):
        """set_default_size stores the size for subsequent orders."""
        exchange = FakeExchangeGateway()
        exchange.price_to_report = Decimal("50000")
        manager = _make_manager(exchange=exchange)
        manager.activate_symbol("BTC")

        result = manager.set_default_size(Decimal("0.1"))

        assert result["status"] == "ok"
        assert manager.get_default_size() == Decimal("0.1")

    def test_default_size_used_when_no_size_given(self):
        """submit_manual_order with size=None uses the default."""
        from finbot.core.domain.entities.order_side import OrderSide

        exchange = FakeExchangeGateway()
        exchange.price_to_report = Decimal("50000")
        manager = _make_manager(exchange=exchange)
        manager.activate_symbol("BTC")
        manager.update_bot_config("max_position", "100000")
        manager.set_default_size(Decimal("0.1"))

        result = manager.submit_manual_order(OrderSide.BUY, None)

        assert result["status"] == "ok"
        assert exchange.submitted_intents[0].size == Decimal("0.1")

    def test_no_default_and_no_size_rejected(self):
        """No default size and no explicit size → rejected."""
        from finbot.core.domain.entities.order_side import OrderSide

        manager = _make_manager()
        manager.activate_symbol("BTC")

        result = manager.submit_manual_order(OrderSide.BUY, None)

        assert result["status"] == "rejected"

    def test_clear_default_size(self):
        """clear_default_size resets to None."""
        exchange = FakeExchangeGateway()
        manager = _make_manager(exchange=exchange)
        manager.activate_symbol("BTC")
        manager.set_default_size(Decimal("0.1"))

        manager.clear_default_size()

        assert manager.get_default_size() is None


class TestStopLossTakeProfitPercentage:
    """Scenario 4 (Slice 2): /sl 2% and /tp 5% as percentage of entry."""

    def _long_manager(self):
        from finbot.core.domain.entities.position_direction import PositionDirection
        from finbot.core.domain.entities.position_snapshot import PositionSnapshot

        exchange = FakeExchangeGateway()
        exchange._position = PositionSnapshot(
            symbol="BTC",
            direction=PositionDirection.LONG,
            size=Decimal("0.01"),
            entry_price=Decimal("95000"),
        )
        manager = _make_manager(exchange=exchange)
        manager.activate_symbol("BTC")
        return manager, exchange

    def test_sl_percentage_below_entry_for_long(self):
        """/sl 2% on a long at 95000 → SL at 93100 (2% below)."""
        manager, exchange = self._long_manager()

        result = manager.attach_stop_loss("2%")

        assert result["status"] == "ok"
        intent = exchange.submitted_intents[0]
        # 95000 * (1 - 0.02) = 93100
        assert intent.limit_price == Decimal("93100.0")

    def test_tp_percentage_above_entry_for_long(self):
        """/tp 5% on a long at 95000 → TP at 99750 (5% above)."""
        manager, exchange = self._long_manager()

        result = manager.attach_take_profit("5%")

        assert result["status"] == "ok"
        intent = exchange.submitted_intents[0]
        # 95000 * (1 + 0.05) = 99750
        assert intent.limit_price == Decimal("99750.0")

    def test_sl_absolute_still_works(self):
        """Absolute price (/sl 94000) still works alongside percentage."""
        manager, exchange = self._long_manager()

        manager.attach_stop_loss(Decimal("94000"))

        assert exchange.submitted_intents[0].limit_price == Decimal("94000")


class TestListActiveOrders:
    """Scenario: /orders lists open orders for the active symbol (Slice 3)."""

    def test_list_active_orders_returns_exchange_orders(self):
        """list_active_orders returns orders from the exchange for the symbol."""
        exchange = FakeExchangeGateway()
        exchange.orders_to_report = [
            {"oid": "1", "side": "buy", "sz": "0.01", "limit_px": "95000"},
            {"oid": "2", "side": "sell", "sz": "0.02", "limit_px": "96000"},
        ]
        manager = _make_manager(exchange=exchange)
        manager.activate_symbol("BTC")

        orders = manager.list_active_orders()

        assert len(orders) == 2
        assert orders[0]["oid"] == "1"

    def test_list_active_orders_none_when_idle(self):
        """No active symbol → returns None."""
        manager = _make_manager()

        assert manager.list_active_orders() is None

    def test_list_active_orders_empty_when_no_orders(self):
        """Active symbol with no open orders → empty list."""
        exchange = FakeExchangeGateway()
        manager = _make_manager(exchange=exchange)
        manager.activate_symbol("BTC")

        orders = manager.list_active_orders()

        assert orders == []


class TestCancelOrder:
    """Scenario: /cancel ORDER_ID cancels a specific order (Slice 3)."""

    def test_cancel_order_cancels_by_oid(self):
        """cancel_order('123') cancels the order with oid=123 on the exchange."""
        exchange = FakeExchangeGateway()
        exchange.cancel_by_oid_result = {"status": "ok", "cancelled": "123"}
        manager = _make_manager(exchange=exchange)
        manager.activate_symbol("BTC")

        result = manager.cancel_order("123")

        assert result["status"] == "ok"
        assert exchange.last_cancel_oid == "123"

    def test_cancel_order_requires_active_symbol(self):
        """No active symbol → rejected."""
        manager = _make_manager()

        result = manager.cancel_order("123")

        assert result["status"] == "rejected"

    def test_cancel_order_unknown_oid_returns_error(self):
        """Unknown oid → exchange rejects, surfaced as error."""
        exchange = FakeExchangeGateway()
        exchange.cancel_by_oid_result = {"status": "error", "message": "not found"}
        manager = _make_manager(exchange=exchange)
        manager.activate_symbol("BTC")

        result = manager.cancel_order("999")

        assert result["status"] == "error"
        assert "not found" in result["message"].lower()
