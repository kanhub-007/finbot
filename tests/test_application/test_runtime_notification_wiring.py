"""Composition-root test for runtime risk-event → Telegram delivery (S4).

Closes C3: on ``main`` the MCP composition root captures
``notification_sender=None`` in the runtime factory closure *before* the
Telegram control plane is constructed, then reassigns the outer local
variable after Telegram starts. The closure never sees the new value, so
``SimpleRuntimeEventEmitter`` never subscribes a ``TelegramRuntimeObserver``
and runtime-emitted ``RiskTriggeredEvent``s are silently dropped.

The fix is lazy lookup: the factory receives a callable ``telegram_ref``
and reads ``.notification_dispatcher`` at call time.

Black-box: the only boundaries mocked are ``create_telegram_control_plane``
(infrastructure factory) and the Hyperliquid SDK (via the S1 smoke-test
patches). Everything else — the composition root, the event emitter, the
observer, the dispatcher interface — runs with real production wiring.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from finbot.core.domain.events.risk_event_triggered import RiskEventTriggered


class _RecordingDispatcher:
    """Fake BotNotificationSender — records scheduled risk/trade/error calls.

    Outcome-based: tests assert on the recorded call list, never on
    interaction counts of internal collaborators.
    """

    def __init__(self) -> None:
        self.risk_calls: list[RiskEventTriggered] = []
        self.trade_calls: list[Any] = []
        self.error_calls: list[Any] = []

    def notify_risk(self, event: RiskEventTriggered) -> None:
        self.risk_calls.append(event)

    def notify_trade(self, event: Any) -> None:
        self.trade_calls.append(event)

    def notify_error(self, event: Any) -> None:
        self.error_calls.append(event)


class FakeTelegramControlPlane:
    """Minimal stand-in for TelegramControlPlane.

    Exposes ``notification_dispatcher`` (the attribute the runtime factory
    reads lazily) and the lifecycle hooks ``create_server`` calls.
    """

    def __init__(self) -> None:
        self.dispatcher = _RecordingDispatcher()
        self.attached: object | None = None
        self.started = False

    @property
    def notification_dispatcher(self) -> _RecordingDispatcher:
        return self.dispatcher

    def attach_bot_manager(self, bot_manager: object) -> None:
        self.attached = bot_manager

    def start_in_background(self) -> None:
        self.started = True


def _settings_env(monkeypatch, *, telegram_enabled: bool) -> None:
    """Point the MCP composition root at an in-memory DB + Telegram flag.

    In-memory avoids Windows file-lock cleanup issues and is sufficient
    for wiring tests (no durable-state assertions).
    """
    monkeypatch.setenv("FINBOT_DATABASE_URL", "sqlite:///:memory:")
    monkeypatch.setenv("FINBOT_MODE", "dry_run")
    monkeypatch.setenv(
        "FINBOT_TELEGRAM_ENABLED", "true" if telegram_enabled else "false"
    )
    monkeypatch.setenv("FINBOT_TELEGRAM_BOT_TOKEN", "fake-token")
    monkeypatch.setenv("FINBOT_TELEGRAM_ALLOWED_USERS", "12345")


def _build_runtime_via_factory(bot_manager) -> object:
    """Invoke the BotManager's runtime_factory to build a real runtime.

    The factory is the closure that captures (or lazily reads) the
    Telegram dispatcher — exercising it is the point of this test.
    """
    return bot_manager._runtime_factory(
        strategy_path="tests/fixtures/strategies/amt_dip_buyer_final.yaml",
        symbol="BTC",
        interval="1h",
        mode="dry_run",
        live_data=False,
        warmup_bars=0,
    )


class TestRuntimeRiskEventReachesTelegram:
    """C3: a runtime built via the MCP factory must deliver risk events."""

    def test_risk_event_reaches_telegram_dispatcher(self, monkeypatch):
        from finbot.startup import mcp as startup_mcp
        from finbot.startup import telegram as startup_telegram

        fake_telegram = FakeTelegramControlPlane()
        _settings_env(monkeypatch, telegram_enabled=True)
        monkeypatch.setattr(
            startup_telegram,
            "create_telegram_control_plane",
            lambda *a, **kw: fake_telegram,
        )

        server = startup_mcp.create_server()
        bot_manager = server._finbot_bot_manager  # type: ignore[attr-defined]
        runtime = _build_runtime_via_factory(bot_manager)

        # Sanity: Telegram was attached and started by the composition root.
        assert fake_telegram.started, "Telegram never started"
        assert fake_telegram.attached is bot_manager

        # Emit a risk event the way the runtime does internally.
        runtime._emit_risk(
            "daily_loss",
            "Daily loss 50 >= max 25",
            bot_stopped=True,
        )

        assert fake_telegram.dispatcher.risk_calls, (
            "risk event never reached the Telegram dispatcher — "
            "factory closure captured a stale notification_sender=None"
        )
        call = fake_telegram.dispatcher.risk_calls[0]
        assert call.reason == "Daily loss 50 >= max 25"
        assert call.bot_stopped is True

    def test_factory_resolves_dispatcher_lazily_not_at_construction(self, monkeypatch):
        """The closure must not snapshot ``notification_sender`` at construction
        time — Telegram starts *after* the BotManager is built."""
        from finbot.startup import mcp as startup_mcp
        from finbot.startup import telegram as startup_telegram

        fake_telegram = FakeTelegramControlPlane()
        _settings_env(monkeypatch, telegram_enabled=True)
        monkeypatch.setattr(
            startup_telegram,
            "create_telegram_control_plane",
            lambda *a, **kw: fake_telegram,
        )

        server = startup_mcp.create_server()
        bot_manager = server._finbot_bot_manager  # type: ignore[attr-defined]
        # Build the runtime BEFORE checking that the dispatcher is the
        # post-Telegram-start one. A snapshotting closure would capture
        # None here and never recover.
        runtime = _build_runtime_via_factory(bot_manager)
        assert fake_telegram.started, (
            "Test setup invariant: Telegram should have started before "
            "the runtime is built"
        )

        # The runtime's event emitter must have a subscriber for
        # RiskTriggeredEvent. (Black-box: we observe via emit, not via
        # introspecting the subscriber list.)
        runtime._emit_risk("mode", "live mode requires ack", bot_stopped=False)
        assert len(fake_telegram.dispatcher.risk_calls) == 1


class TestTelegramDisabledIsSafe:
    """When Telegram is disabled, no dispatcher exists and emit is a no-op."""

    def test_disabled_telegram_does_not_crash_emit(self, monkeypatch):
        from finbot.startup import mcp as startup_mcp
        from finbot.startup import telegram as startup_telegram

        _settings_env(monkeypatch, telegram_enabled=False)
        # Guard: ensure the factory isn't called either.
        monkeypatch.setattr(
            startup_telegram,
            "create_telegram_control_plane",
            lambda *a, **kw: pytest.fail(
                "create_telegram_control_plane called with Telegram disabled"
            ),
        )

        server = startup_mcp.create_server()
        bot_manager = server._finbot_bot_manager  # type: ignore[attr-defined]
        runtime = _build_runtime_via_factory(bot_manager)

        # emit must not raise even with no subscriber wired.
        runtime._emit_risk("mode", "ack missing", bot_stopped=False)


# Ensure JSON import stays referenced (used by tooling that introspects this
# module's dependencies); keeps ruff F401 happy if future tests add asserts
# on serialised payloads.
_ = json
