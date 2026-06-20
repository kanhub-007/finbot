"""Tests for decomposed BotManager collaborators (S7: H1).

Each collaborator is independently testable with in-memory fakes. These
tests assert each collaborator's responsibility in isolation — the full
BotManager facade (which forwards to these collaborators) is covered by
the existing characterisation tests in test_bot_manager.py,
test_active_symbol_management.py, and test_manual_order_gates.py.
"""

from __future__ import annotations

from decimal import Decimal

from finbot.core.domain.entities.position_direction import PositionDirection
from finbot.core.domain.entities.wallet_balance import WalletBalance
from finbot.core.domain.services.bot_manager.bot_manager_lock import BotManagerLock
from finbot.core.domain.services.bot_manager.bot_manager_state import (
    BotManagerState,
)
from finbot.core.domain.services.bot_manager.bot_query_service import BotQueryService
from finbot.core.domain.services.bot_manager.runtime_config_service import (
    RuntimeConfigService,
)
from finbot.core.domain.services.bot_manager.symbol_session_service import (
    SymbolSessionService,
)
from tests.fakes import FakeBotStateRepository, FakeExchangeGateway


class TestBotManagerLock:
    def test_lock_is_reentrant(self) -> None:
        """The lock must be reentrant (collaborators call each other's locked methods)."""
        lock = BotManagerLock()
        with lock:
            with lock:  # nested acquire must not deadlock
                pass


class TestSymbolSessionService:
    def _make(self, exchange=None) -> SymbolSessionService:
        return SymbolSessionService(
            state=BotManagerState(),
            lock=BotManagerLock(),
            exchange=exchange or FakeExchangeGateway(),
            metadata_provider=None,
            repo=FakeBotStateRepository(),
        )

    def test_get_active_symbol_returns_none_when_idle(self) -> None:
        svc = self._make()
        assert svc.get_active_symbol() is None

    def test_activate_symbol_sets_active_symbol(self) -> None:
        svc = self._make()
        result = svc.activate_symbol("BTC")
        assert result["status"] == "active"
        assert result["symbol"] == "BTC"
        active = svc.get_active_symbol()
        assert active is not None
        assert active.symbol == "BTC"

    def test_get_active_position_returns_flat_when_no_position(self) -> None:
        svc = self._make()
        svc.activate_symbol("BTC")
        pos = svc.get_active_position()
        assert pos is not None
        assert pos.direction == PositionDirection.FLAT

    def test_get_balance_returns_exchange_balance(self) -> None:
        svc = self._make()
        bal = svc.get_balance()
        assert isinstance(bal, WalletBalance)

    def test_methods_return_none_when_no_exchange(self) -> None:
        svc = SymbolSessionService(
            state=BotManagerState(),
            lock=BotManagerLock(),
            exchange=None,
            metadata_provider=None,
            repo=FakeBotStateRepository(),
        )
        assert svc.get_active_position() is None
        assert svc.list_active_orders() is None
        assert svc.get_active_price() is None
        assert svc.get_balance() is None


class TestRuntimeConfigService:
    def _make(self) -> RuntimeConfigService:
        return RuntimeConfigService(
            state=BotManagerState(),
            lock=BotManagerLock(),
            config_writer=None,
        )

    def test_get_bot_config_returns_defaults(self) -> None:
        svc = self._make()
        cfg = svc.get_bot_config()
        assert cfg.max_open_orders == 3

    def test_update_bot_config_rejects_unknown_key(self) -> None:
        svc = self._make()
        result = svc.update_bot_config("nonsense", "1")
        assert result["status"] == "rejected"

    def test_update_and_read_max_position(self) -> None:
        svc = self._make()
        result = svc.update_bot_config("max_position", "500")
        assert result["status"] == "ok"
        assert svc.get_bot_config().max_position_usd == Decimal("500")

    def test_save_config_to_env_rejected_without_writer(self) -> None:
        svc = self._make()
        result = svc.save_config_to_env()
        assert result["status"] == "rejected"

    def test_default_size_set_get_clear(self) -> None:
        svc = self._make()
        assert svc.get_default_size() is None
        assert svc.set_default_size(Decimal("0.5"))["status"] == "ok"
        assert svc.get_default_size() == Decimal("0.5")
        svc.clear_default_size()
        assert svc.get_default_size() is None

    def test_profiles_save_load_list(self) -> None:
        svc = self._make()
        svc.update_bot_config("max_position", "999")
        assert svc.save_config_profile("aggressive")["status"] == "ok"
        svc.update_bot_config("max_position", "10")
        assert "aggressive" in svc.list_config_profiles()["profiles"]
        assert svc.load_config_profile("aggressive")["status"] == "ok"
        assert svc.get_bot_config().max_position_usd == Decimal("999")
        assert svc.load_config_profile("unknown")["status"] == "rejected"


class TestBotQueryService:
    def _make(self) -> BotQueryService:
        return BotQueryService(repo=FakeBotStateRepository())

    def test_list_bot_runs_empty(self) -> None:
        svc = self._make()
        assert svc.list_bot_runs() == []

    def test_get_bot_run_returns_none_for_unknown(self) -> None:
        svc = self._make()
        assert svc.get_bot_run("nonexistent") is None

    def test_get_audit_log_empty(self) -> None:
        svc = self._make()
        assert svc.get_audit_log() == []
