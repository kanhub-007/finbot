"""Telegram-related test fakes for Classical (Detroit) school testing.

In-memory implementations of domain interfaces — no mocks, no
interaction assertions. All state is observable and assertable.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from finbot.core.domain.entities.telegram_chat import TelegramChat
from finbot.core.domain.entities.telegram_run_flow_session import (
    TelegramRunFlowSession,
)
from finbot.core.domain.interfaces.strategy_directory import StrategyDirectory
from finbot.core.domain.interfaces.telegram_chat_repository import (
    TelegramChatRepository,
)
from finbot.core.domain.interfaces.telegram_session_store import (
    TelegramSessionStore,
)

# ---------------------------------------------------------------------------
# InMemoryTelegramChatRepository
# ---------------------------------------------------------------------------


class InMemoryTelegramChatRepository(TelegramChatRepository):
    """Fake chat repository that stores TelegramChat entities in a dict."""

    def __init__(self) -> None:
        self._chats: dict[int, TelegramChat] = {}

    async def add_chat(self, chat: TelegramChat) -> None:
        self._chats[chat.chat_id] = chat

    async def get_chat(self, chat_id: int) -> TelegramChat | None:
        return self._chats.get(chat_id)

    async def list_chats(self) -> list[TelegramChat]:
        return list(self._chats.values())

    async def remove_chat(self, chat_id: int) -> None:
        self._chats.pop(chat_id, None)

    async def set_notifications(self, chat_id: int, enabled: bool) -> None:
        chat = self._chats.get(chat_id)
        if chat is None:
            return
        self._chats[chat_id] = TelegramChat(
            chat_id=chat.chat_id,
            user_id=chat.user_id,
            registered_at=chat.registered_at,
            notifications_enabled=enabled,
        )


# ---------------------------------------------------------------------------
# InMemoryTelegramSessionStore
# ---------------------------------------------------------------------------


class InMemoryTelegramSessionStore(TelegramSessionStore):
    """Fake session store that stores TelegramRunFlowSession in a dict."""

    def __init__(self) -> None:
        self._sessions: dict[str, TelegramRunFlowSession] = {}

    def create(self, chat_id: int, message_id: int) -> TelegramRunFlowSession:
        session_id = _short_id()
        session = TelegramRunFlowSession(
            session_id=session_id,
            chat_id=chat_id,
            message_id=message_id,
        )
        self._sessions[session_id] = session
        return session

    def get(self, session_id: str) -> TelegramRunFlowSession | None:
        return self._sessions.get(session_id)

    def save(self, session: TelegramRunFlowSession) -> None:
        self._sessions[session.session_id] = session

    def delete(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)

    def expire_old(self, now: object) -> int:
        assert isinstance(now, datetime)
        to_delete = [sid for sid, s in self._sessions.items() if s.is_expired(now)]
        for sid in to_delete:
            del self._sessions[sid]
        return len(to_delete)


# ---------------------------------------------------------------------------
# FakeStrategyDirectory
# ---------------------------------------------------------------------------


class FakeStrategyDirectory(StrategyDirectory):
    """Fake strategy directory that returns a pre-configured list of filenames."""

    def __init__(self, strategies: list[str] | None = None) -> None:
        self._strategies: list[str] = strategies or []
        self._base_dir: str = "/fake/strategies"

    def list_strategies(self) -> list[str]:
        return list(self._strategies)

    def strategy_exists(self, name: str) -> bool:
        return name in self._strategies

    def get_strategy_path(self, name: str) -> str:
        return f"{self._base_dir}/{name}"


# ---------------------------------------------------------------------------
# FakeBotManager
# ---------------------------------------------------------------------------


class FakeBotManager:
    """Fake BotManager that records started/stopped state without side effects.

    Used by HandleTelegramCommand tests to verify the use case delegates
    start/stop/get_status calls correctly.
    """

    def __init__(
        self,
        *,
        is_running: bool = False,
        bot_run_id: str = "",
    ) -> None:
        self.is_running_flag = is_running
        self._bot_run_id = bot_run_id
        self._last_run: dict | None = None

        # Observables for outcome-based assertions
        self.start_called: bool = False
        self.start_called_with: dict | None = None
        self.stop_called: bool = False
        self.stop_result: dict = {"status": "no_bot_running", "bot_run_id": ""}

    def is_running(self) -> bool:
        return self.is_running_flag

    def start(
        self,
        strategy_path: str,
        symbol: str,
        interval: str,
        mode: str,
        warmup_bars: int = 100,
        live_trading_ack: bool = False,
        execution_config=None,
    ) -> dict[str, str]:
        self.start_called = True
        self.start_called_with = {
            "strategy_path": strategy_path,
            "symbol": symbol,
            "interval": interval,
            "mode": mode,
            "warmup_bars": warmup_bars,
            "live_trading_ack": live_trading_ack,
            "execution_config": execution_config,
        }
        run_id = f"r_{_short_id()}"
        self._bot_run_id = run_id
        self.is_running_flag = True
        return {"status": "running", "bot_run_id": run_id}

    def stop(self) -> dict[str, str]:
        self.stop_called = True
        if self.is_running_flag:
            self.is_running_flag = False
            return {"status": "stopped", "bot_run_id": self._bot_run_id}
        return {"status": "no_bot_running", "bot_run_id": ""}

    def get_status(self) -> dict[str, object]:
        status: dict[str, object] = {
            "is_running": self.is_running_flag,
            "uptime_seconds": 3600,
            "total_signals": 0,
            "total_orders": 0,
            "total_fills": 0,
        }
        if self.is_running_flag:
            status["bot_run_id"] = self._bot_run_id
            status["strategy_name"] = "test_strategy.yaml"
            status["symbol"] = "BTC"
            status["interval"] = "1h"
            status["mode"] = "dry_run"
        else:
            status["last_run"] = self._last_run
        return status

    def set_last_run(self, last_run: dict | None) -> None:
        self._last_run = last_run
        if last_run:
            self._bot_run_id = last_run.get("run_id", "")

    def list_bot_runs(self, limit: int = 20, mode_filter: str | None = None) -> list:
        return []

    def get_bot_run(self, run_id: str) -> object | None:
        return None

    # -- trading-control spec methods (recording fakes) --------------------

    def activate_symbol(self, symbol: str) -> dict[str, str]:
        from finbot.core.domain.entities.active_symbol_state import ActiveSymbolState

        self._active_symbol = ActiveSymbolState(symbol=symbol)
        return {
            "status": "active",
            "symbol": symbol,
            "leverage": "1",
            "margin_mode": "isolated",
        }

    def get_active_symbol(self):
        return getattr(self, "_active_symbol", None)

    def get_active_price(self):
        from decimal import Decimal

        return Decimal("50000") if getattr(self, "_active_symbol", None) else None

    def get_active_position(self):
        return None

    def get_balance(self):
        return None

    def set_leverage(
        self, leverage: int, margin_mode: str = "isolated"
    ) -> dict[str, str]:
        return {"status": "ok", "leverage": str(leverage), "margin_mode": margin_mode}

    def submit_manual_order(self, side, size, limit_px=None, usd_notional=None) -> dict:
        return {"status": "ok", "response": {"order_id": "fake"}}

    def submit_manual_order_with_brackets(
        self,
        side,
        size,
        sl_price=None,
        tp_price=None,
        limit_px=None,
        usd_notional=None,
    ) -> dict:
        return {"status": "ok", "response": {"order_id": "fake"}}

    def close_active_position(self) -> dict[str, str]:
        return {"status": "ok"}

    def clear_all(self) -> dict:
        return {"status": "ok", "cancelled_orders": 0, "closed_positions": 0}

    def attach_stop_loss(self, price) -> dict:
        return {"status": "ok", "kind": "sl", "price": str(price)}

    def attach_take_profit(self, price) -> dict:
        return {"status": "ok", "kind": "tp", "price": str(price)}

    def clear_risk_order(self, kind: str) -> dict:
        return {"status": "ok", "kind": kind}

    def list_active_orders(self):
        return [] if getattr(self, "_active_symbol", None) is not None else None

    def cancel_order(self, order_id: str) -> dict:
        return {"status": "ok", "order_id": order_id}

    # -- panic support (S6) ----------------------------------------------

    def cancel_all_orders(self, symbol: str) -> dict:
        """Return the configured cancel result for outcome-based assertions.

        Tests override ``cancel_all_orders_result`` to drive the panic
        report-count assertions (H1).
        """
        return getattr(self, "cancel_all_orders_result", {"status": "ok"})

    def close_position(self, symbol: str) -> dict:
        return getattr(self, "close_position_result", {"status": "ok"})

    def save_config_profile(self, name: str) -> dict:
        return {"status": "ok", "profile": name}

    def load_config_profile(self, name: str) -> dict:
        return {"status": "ok", "profile": name}

    def list_config_profiles(self) -> dict:
        return {"status": "ok", "profiles": []}

    def get_bot_config(self):
        from finbot.core.domain.entities.runtime_bot_config import RuntimeBotConfig

        return RuntimeBotConfig()

    def update_bot_config(self, key: str, value: str) -> dict[str, str]:
        return {"status": "ok", "key": key, "value": value}

    def save_config_to_env(self) -> dict[str, str]:
        return {"status": "ok", "saved": 4}

    def set_default_size(self, size) -> dict[str, str]:
        self._default_size = size
        return {"status": "ok", "default_size": str(size)}

    def get_default_size(self):
        return getattr(self, "_default_size", None)

    def clear_default_size(self) -> None:
        self._default_size = None


# ---------------------------------------------------------------------------
# FakeTelegramOutbox — fake Telegram bot that stores sent messages
# ---------------------------------------------------------------------------


class FakeTelegramOutbox:
    """Fake Telegram send mechanism that stores messages as observable output.

    Implements the same shape as TelegramBotPort but synchronous and
    records every sent/edited message for outcome-based assertions.
    """

    def __init__(self) -> None:
        self.sent_messages: list[dict] = []
        self.edited_messages: list[dict] = []
        self.answered_callbacks: list[dict] = []
        self._next_message_id: int = 1000

    async def send_message(
        self,
        chat_id: int,
        text: str,
        parse_mode: str | None = None,
        reply_markup: dict | None = None,
    ) -> object:
        msg_id = self._next_message_id
        self._next_message_id += 1
        self.sent_messages.append(
            {
                "chat_id": chat_id,
                "text": text,
                "parse_mode": parse_mode,
                "reply_markup": reply_markup,
                "message_id": msg_id,
            }
        )
        from finbot.core.domain.entities.send_result import SendResult

        return SendResult(success=True, message_id=msg_id)

    async def edit_message_text(
        self,
        chat_id: int,
        message_id: int,
        text: str,
        parse_mode: str | None = None,
        reply_markup: dict | None = None,
    ) -> object:
        self.edited_messages.append(
            {
                "chat_id": chat_id,
                "message_id": message_id,
                "text": text,
                "parse_mode": parse_mode,
                "reply_markup": reply_markup,
            }
        )
        from finbot.core.domain.entities.send_result import SendResult

        return SendResult(success=True, message_id=message_id)

    async def answer_callback_query(
        self,
        callback_query_id: str,
        text: str | None = None,
    ) -> bool:
        self.answered_callbacks.append(
            {
                "callback_query_id": callback_query_id,
                "text": text,
            }
        )
        return True

    async def edit_message_reply_markup(
        self,
        chat_id: int,
        message_id: int,
        reply_markup: dict | None = None,
    ) -> bool:
        return True


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _short_id() -> str:
    """Generate a short unique ID suitable for session IDs."""
    return uuid.uuid4().hex[:6]
