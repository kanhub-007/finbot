"""Tests for the HandleTelegramCommand use case — /whoami, authorization, etc."""

import pytest

from finbot.core.application.dto.callback_query_request import (
    CallbackQueryRequest,
)
from finbot.core.application.dto.telegram_command_request import (
    TelegramCommandRequest,
)
from finbot.core.application.use_cases.handle_telegram_command import (
    HandleTelegramCommand,
)
from tests.fakes_telegram import (
    FakeBotManager,
    FakeStrategyDirectory,
    InMemoryTelegramChatRepository,
    InMemoryTelegramSessionStore,
)


class TestUnauthorizedUser:
    @pytest.mark.asyncio
    async def test_unauthorized_user_cannot_execute_control_command(self):
        """Control commands are rejected for users not in allowed list."""
        fake_repo = InMemoryTelegramChatRepository()
        fake_manager = FakeBotManager()

        use_case = HandleTelegramCommand(
            bot_manager=fake_manager,
            chat_repo=fake_repo,
            strategy_dir=FakeStrategyDirectory([]),
            session_store=InMemoryTelegramSessionStore(),
            allowed_users=frozenset({111}),  # only user 111 allowed
        )

        # Unauthorized user (999) tries /status
        result = await use_case.execute(
            TelegramCommandRequest(
                command="/status", args="", chat_id=999999,
                user_id=999, message_id=1,
            )
        )

        assert "Unauthorized" in result.text
        assert fake_manager.start_called is False
        chats = await fake_repo.list_chats()
        assert chats == []

    @pytest.mark.asyncio
    async def test_fail_closed_empty_allowed_users_rejects_control_commands(self):
        """When allowed_users is empty, control commands fail closed."""
        fake_repo = InMemoryTelegramChatRepository()
        fake_manager = FakeBotManager()

        use_case = HandleTelegramCommand(
            bot_manager=fake_manager,
            chat_repo=fake_repo,
            strategy_dir=FakeStrategyDirectory([]),
            session_store=InMemoryTelegramSessionStore(),
            allowed_users=frozenset(),
        )

        result = await use_case.execute(
            TelegramCommandRequest(
                command="/run", args="", chat_id=123, user_id=456, message_id=1,
            )
        )

        assert "/whoami" in result.text
        assert "FINBOT_TELEGRAM_ALLOWED_USERS" in result.text
        assert fake_manager.start_called is False


class TestUnknownCommand:
    @pytest.mark.asyncio
    async def test_unknown_command_returns_help_hint(self):
        """Unknown commands get a helpful response suggesting /help."""
        use_case = HandleTelegramCommand(
            bot_manager=FakeBotManager(),
            chat_repo=InMemoryTelegramChatRepository(),
            strategy_dir=FakeStrategyDirectory([]),
            session_store=InMemoryTelegramSessionStore(),
            allowed_users=frozenset({123}),
        )

        result = await use_case.execute(
            TelegramCommandRequest(
                command="/asdf", args="", chat_id=1, user_id=123, message_id=1,
            )
        )

        assert "/help" in result.text


class TestStart:
    @pytest.mark.asyncio
    async def test_start_registers_authorized_chat_and_returns_welcome(self):
        """/start registers the chat and returns welcome message with keyboard."""
        fake_repo = InMemoryTelegramChatRepository()

        use_case = HandleTelegramCommand(
            bot_manager=FakeBotManager(),
            chat_repo=fake_repo,
            strategy_dir=FakeStrategyDirectory([]),
            session_store=InMemoryTelegramSessionStore(),
            allowed_users=frozenset({987654321}),
        )

        result = await use_case.execute(
            TelegramCommandRequest(
                command="/start", args="", chat_id=123456789,
                user_id=987654321, message_id=1,
            )
        )

        assert "Finbot Trading Bot" in result.text
        assert result.reply_markup is not None
        # Verify inline keyboard has at least one row
        assert len(result.reply_markup["inline_keyboard"]) >= 1

        # Chat should be persisted
        chat = await fake_repo.get_chat(123456789)
        assert chat is not None
        assert chat.user_id == 987654321
        assert chat.notifications_enabled is True

    @pytest.mark.asyncio
    async def test_start_repeated_returns_same_welcome(self):
        """Repeated /start returns the same welcome without error."""
        fake_repo = InMemoryTelegramChatRepository()

        use_case = HandleTelegramCommand(
            bot_manager=FakeBotManager(),
            chat_repo=fake_repo,
            strategy_dir=FakeStrategyDirectory([]),
            session_store=InMemoryTelegramSessionStore(),
            allowed_users=frozenset({987654321}),
        )

        result1 = await use_case.execute(
            TelegramCommandRequest(
                command="/start", args="", chat_id=123456789,
                user_id=987654321, message_id=1,
            )
        )
        result2 = await use_case.execute(
            TelegramCommandRequest(
                command="/start", args="", chat_id=123456789,
                user_id=987654321, message_id=2,
            )
        )

        assert "Finbot Trading Bot" in result1.text
        assert "Finbot Trading Bot" in result2.text

    @pytest.mark.asyncio
    async def test_start_unauthorized_user_rejected(self):
        """/start from unauthorized user returns Unauthorized."""
        fake_repo = InMemoryTelegramChatRepository()

        use_case = HandleTelegramCommand(
            bot_manager=FakeBotManager(),
            chat_repo=fake_repo,
            strategy_dir=FakeStrategyDirectory([]),
            session_store=InMemoryTelegramSessionStore(),
            allowed_users=frozenset({111}),
        )

        result = await use_case.execute(
            TelegramCommandRequest(
                command="/start", args="", chat_id=999,
                user_id=999, message_id=1,
            )
        )

        assert "Unauthorized" in result.text
        chat = await fake_repo.get_chat(999)
        assert chat is None


class TestWhoAmI:
    @pytest.mark.asyncio
    async def test_whoami_returns_user_and_chat_id_without_authorization(self):
        """/whoami returns exact user_id and chat_id; no chat persisted; no auth required."""
        fake_repo = InMemoryTelegramChatRepository()
        use_case = HandleTelegramCommand(
            bot_manager=FakeBotManager(),
            chat_repo=fake_repo,
            strategy_dir=FakeStrategyDirectory([]),
            session_store=InMemoryTelegramSessionStore(),
            allowed_users=frozenset(),
        )

        result = await use_case.execute(
            TelegramCommandRequest(
                command="/whoami",
                args="",
                chat_id=123456789,
                user_id=987654321,
                message_id=1,
            )
        )

        assert "987654321" in result.text
        assert "123456789" in result.text
        assert await fake_repo.list_chats() == []


class TestHelp:
    @pytest.mark.asyncio
    async def test_help_lists_commands_and_safety_notes(self):
        """/help returns command list and safety notes."""
        use_case = HandleTelegramCommand(
            bot_manager=FakeBotManager(),
            chat_repo=InMemoryTelegramChatRepository(),
            strategy_dir=FakeStrategyDirectory([]),
            session_store=InMemoryTelegramSessionStore(),
            allowed_users=frozenset({123}),
        )

        result = await use_case.execute(
            TelegramCommandRequest(
                command="/help", args="", chat_id=1,
                user_id=123, message_id=1,
            )
        )

        assert "Commands" in result.text or "/run" in result.text
        assert "/status" in result.text
        assert "/stop" in result.text
        assert "/panic" in result.text
        assert result.reply_markup is not None


class TestStatus:
    @pytest.mark.asyncio
    async def test_status_idle_returns_last_run_summary(self):
        """/status when idle returns last run summary."""
        fake_manager = FakeBotManager(is_running=False)
        fake_manager.set_last_run({
            "run_id": "r_abc122",
            "strategy_name": "trend_follow.yaml",
            "symbol": "ETH",
            "interval": "4h",
            "mode": "dry_run",
            "started_at": "2026-06-15T10:00:00+00:00",
            "ended_at": "2026-06-15T14:30:00+00:00",
        })

        use_case = HandleTelegramCommand(
            bot_manager=fake_manager,
            chat_repo=InMemoryTelegramChatRepository(),
            strategy_dir=FakeStrategyDirectory([]),
            session_store=InMemoryTelegramSessionStore(),
            allowed_users=frozenset({123}),
        )

        result = await use_case.execute(
            TelegramCommandRequest(
                command="/status", args="", chat_id=1,
                user_id=123, message_id=1,
            )
        )

        assert "Idle" in result.text or "idle" in result.text.lower()
        assert "r\_abc122" in result.text
        assert "trend\_follow" in result.text
        assert result.reply_markup is not None

    @pytest.mark.asyncio
    async def test_status_idle_no_prior_runs(self):
        """/status when idle with no history shows appropriate message."""
        fake_manager = FakeBotManager(is_running=False)

        use_case = HandleTelegramCommand(
            bot_manager=fake_manager,
            chat_repo=InMemoryTelegramChatRepository(),
            strategy_dir=FakeStrategyDirectory([]),
            session_store=InMemoryTelegramSessionStore(),
            allowed_users=frozenset({123}),
        )

        result = await use_case.execute(
            TelegramCommandRequest(
                command="/status", args="", chat_id=1,
                user_id=123, message_id=1,
            )
        )

        # Should not crash — returns some status text
        assert result.text

    @pytest.mark.asyncio
    async def test_status_running_returns_live_state_summary(self):
        """/status when running returns live state with counts."""
        fake_manager = FakeBotManager(is_running=True, bot_run_id="r_abc123")
        fake_manager.is_running_flag = True
        fake_manager._bot_run_id = "r_abc123"
        # Override get_status to return running data
        fake_manager.get_status = lambda: {
            "is_running": True,
            "bot_run_id": "r_abc123",
            "strategy_name": "macd_cross.yaml",
            "symbol": "BTC",
            "interval": "1h",
            "mode": "LIVE",
            "uptime_seconds": 9240,
            "total_signals": 47,
            "total_orders": 12,
            "total_fills": 11,
        }

        use_case = HandleTelegramCommand(
            bot_manager=fake_manager,
            chat_repo=InMemoryTelegramChatRepository(),
            strategy_dir=FakeStrategyDirectory([]),
            session_store=InMemoryTelegramSessionStore(),
            allowed_users=frozenset({123}),
        )

        result = await use_case.execute(
            TelegramCommandRequest(
                command="/status", args="", chat_id=1,
                user_id=123, message_id=1,
            )
        )

        assert "r\_abc123" in result.text
        assert "macd\_cross" in result.text
        assert "47" in result.text
        assert "12" in result.text
        assert "11" in result.text
        assert result.reply_markup is not None


class TestStop:
    @pytest.mark.asyncio
    async def test_stop_returns_stopped_summary(self):
        """/stop stops the bot and returns a summary."""
        fake_manager = FakeBotManager(is_running=True, bot_run_id="r_abc123")

        use_case = HandleTelegramCommand(
            bot_manager=fake_manager,
            chat_repo=InMemoryTelegramChatRepository(),
            strategy_dir=FakeStrategyDirectory([]),
            session_store=InMemoryTelegramSessionStore(),
            allowed_users=frozenset({123}),
        )

        result = await use_case.execute(
            TelegramCommandRequest(
                command="/stop", args="", chat_id=1,
                user_id=123, message_id=1,
            )
        )

        assert fake_manager.stop_called is True
        assert "Stopped" in result.text or "stopped" in result.text.lower()

    @pytest.mark.asyncio
    async def test_stop_when_idle_returns_no_bot_running(self):
        """/stop when no bot is running says so."""
        fake_manager = FakeBotManager(is_running=False)

        use_case = HandleTelegramCommand(
            bot_manager=fake_manager,
            chat_repo=InMemoryTelegramChatRepository(),
            strategy_dir=FakeStrategyDirectory([]),
            session_store=InMemoryTelegramSessionStore(),
            allowed_users=frozenset({123}),
        )

        result = await use_case.execute(
            TelegramCommandRequest(
                command="/stop", args="", chat_id=1,
                user_id=123, message_id=1,
            )
        )

        assert "no bot" in result.text.lower()


class TestRunRejection:
    @pytest.mark.asyncio
    async def test_run_when_bot_running_returns_rejection_keyboard(self):
        """/run when bot is running rejects with stop option."""
        fake_manager = FakeBotManager(is_running=True, bot_run_id="r_abc123")

        use_case = HandleTelegramCommand(
            bot_manager=fake_manager,
            chat_repo=InMemoryTelegramChatRepository(),
            strategy_dir=FakeStrategyDirectory(["test.yaml"]),
            session_store=InMemoryTelegramSessionStore(),
            allowed_users=frozenset({123}),
        )

        result = await use_case.execute(
            TelegramCommandRequest(
                command="/run", args="", chat_id=1,
                user_id=123, message_id=1,
            )
        )

        assert fake_manager.start_called is False
        assert "already running" in result.text.lower()
        assert result.reply_markup is not None


class TestRunFlow:
    @pytest.mark.asyncio
    async def test_run_flow_starts_dry_run_after_keyboard_selection(self):
        """Full /run guided flow: strategies → symbol → interval → mode=DRY_RUN."""
        fake_manager = FakeBotManager(is_running=False)
        fake_strategy_dir = FakeStrategyDirectory([
            "macd_cross.yaml", "trend_follow.yaml"
        ])
        fake_sessions = InMemoryTelegramSessionStore()

        use_case = HandleTelegramCommand(
            bot_manager=fake_manager,
            chat_repo=InMemoryTelegramChatRepository(),
            strategy_dir=fake_strategy_dir,
            session_store=fake_sessions,
            allowed_users=frozenset({987654321}),
        )

        # Step 1: /run → show strategies
        result = await use_case.execute(TelegramCommandRequest(
            command="/run", args="", chat_id=123456789,
            user_id=987654321, message_id=100,
        ))
        assert len(result.reply_markup["inline_keyboard"]) >= 1

        # Step 2: select strategy via callback
        cb_data = result.reply_markup["inline_keyboard"][0][0]["callback_data"]
        result = await use_case.handle_callback(CallbackQueryRequest(
            callback_data=cb_data, chat_id=123456789,
            user_id=987654321, message_id=100, callback_query_id="cq1",
        ))
        assert "Symbol" in result.text or "symbol" in result.text.lower()

        # Step 3: select symbol via callback
        cb_data = result.reply_markup["inline_keyboard"][0][0]["callback_data"]
        result = await use_case.handle_callback(CallbackQueryRequest(
            callback_data=cb_data, chat_id=123456789,
            user_id=987654321, message_id=100, callback_query_id="cq2",
        ))
        assert "interval" in result.text.lower()

        # Step 4: select interval via callback
        cb_data = result.reply_markup["inline_keyboard"][0][0]["callback_data"]
        result = await use_case.handle_callback(CallbackQueryRequest(
            callback_data=cb_data, chat_id=123456789,
            user_id=987654321, message_id=100, callback_query_id="cq3",
        ))
        assert "mode" in result.text.lower() or "dry" in result.text.lower()

        # Step 5: select dry_run mode via callback
        # Find the dry_run button
        keyboard = result.reply_markup["inline_keyboard"]
        dry_cb = None
        for row in keyboard:
            for btn in row:
                if "dry" in str(btn.get("text", "")).lower():
                    dry_cb = btn["callback_data"]
        assert dry_cb is not None, "Dry Run button not found in mode keyboard"

        result = await use_case.handle_callback(CallbackQueryRequest(
            callback_data=dry_cb, chat_id=123456789,
            user_id=987654321, message_id=100, callback_query_id="cq4",
        ))

        assert fake_manager.start_called is True
        assert fake_manager.start_called_with is not None
        assert fake_manager.start_called_with["mode"] == "dry_run"
        assert "Bot started" in result.text or "started" in result.text.lower()

    @pytest.mark.asyncio
    async def test_run_flow_live_requires_env_ack_and_telegram_confirmation(self):
        """Live mode requires explicit inline confirmation, then performs start."""
        fake_manager = FakeBotManager(is_running=False)
        fake_sessions = InMemoryTelegramSessionStore()

        use_case = HandleTelegramCommand(
            bot_manager=fake_manager,
            chat_repo=InMemoryTelegramChatRepository(),
            strategy_dir=FakeStrategyDirectory(["macd_cross.yaml"]),
            session_store=fake_sessions,
            allowed_users=frozenset({987654321}),
            live_trading_ack=True,
        )

        # Setup: create a session with strategy, symbol, interval pre-selected
        session = fake_sessions.create(123456789, 100)
        session.strategy_path = "macd_cross.yaml"
        session.symbol = "BTC"
        session.interval = "1h"
        fake_sessions.save(session)

        # Tap Live mode → should show confirmation prompt
        result = await use_case.handle_callback(CallbackQueryRequest(
            callback_data=f"run:{session.session_id}:mode:live",
            chat_id=123456789, user_id=987654321,
            message_id=100, callback_query_id="cq1",
        ))

        assert "Are you sure" in result.text or "confirm" in result.text.lower()
        # Confirm YES
        cb_data = result.reply_markup["inline_keyboard"][0][0]["callback_data"]
        result = await use_case.handle_callback(CallbackQueryRequest(
            callback_data=cb_data, chat_id=123456789,
            user_id=987654321, message_id=100, callback_query_id="cq2",
        ))

        assert fake_manager.start_called is True
        assert fake_manager.start_called_with["mode"] == "live"

    @pytest.mark.asyncio
    async def test_run_flow_live_cancel_does_not_start_bot(self):
        """Cancelling live confirmation does not start the bot."""
        fake_manager = FakeBotManager(is_running=False)
        fake_sessions = InMemoryTelegramSessionStore()

        use_case = HandleTelegramCommand(
            bot_manager=fake_manager,
            chat_repo=InMemoryTelegramChatRepository(),
            strategy_dir=FakeStrategyDirectory(["macd_cross.yaml"]),
            session_store=fake_sessions,
            allowed_users=frozenset({987654321}),
        )

        session = fake_sessions.create(123456789, 100)
        session.strategy_path = "macd_cross.yaml"
        session.symbol = "BTC"
        session.interval = "1h"
        fake_sessions.save(session)

        # Tap Live mode
        result = await use_case.handle_callback(CallbackQueryRequest(
            callback_data=f"run:{session.session_id}:mode:live",
            chat_id=123456789, user_id=987654321,
            message_id=100, callback_query_id="cq1",
        ))

        # Tap Cancel (second button)
        cb_data = result.reply_markup["inline_keyboard"][0][1]["callback_data"]
        result = await use_case.handle_callback(CallbackQueryRequest(
            callback_data=cb_data, chat_id=123456789,
            user_id=987654321, message_id=100, callback_query_id="cq2",
        ))

        assert fake_manager.start_called is False


class TestHistory:
    @pytest.mark.asyncio
    async def test_history_returns_paginated_run_list(self):
        """/history returns a paginated list of recent bot runs."""
        from finbot.core.domain.entities.bot_run import BotRun
        from datetime import datetime, timezone

        fake_manager = FakeBotManager(is_running=False)
        runs = [
            BotRun(
                strategy_name="macd_cross.yaml",
                strategy_hash="abc",
                symbol="BTC",
                interval="1h",
                mode="LIVE",
                run_id="r_001",
                started_at=datetime.now(timezone.utc),
            ),
            BotRun(
                strategy_name="trend_follow.yaml",
                strategy_hash="def",
                symbol="ETH",
                interval="4h",
                mode="dry_run",
                run_id="r_002",
                started_at=datetime.now(timezone.utc),
            ),
        ]
        fake_manager.list_bot_runs = lambda limit=20, mode_filter=None: runs[:limit]

        use_case = HandleTelegramCommand(
            bot_manager=fake_manager,
            chat_repo=InMemoryTelegramChatRepository(),
            strategy_dir=FakeStrategyDirectory([]),
            session_store=InMemoryTelegramSessionStore(),
            allowed_users=frozenset({123}),
        )

        result = await use_case.execute(
            TelegramCommandRequest(
                command="/history", args="", chat_id=1,
                user_id=123, message_id=1,
            )
        )

        assert "r\_001" in result.text
        assert "r\_002" in result.text
        assert result.reply_markup is not None

    @pytest.mark.asyncio
    async def test_history_no_runs_yet(self):
        """/history with zero runs shows helpful message."""
        fake_manager = FakeBotManager(is_running=False)
        fake_manager.list_bot_runs = lambda limit=20, mode_filter=None: []

        use_case = HandleTelegramCommand(
            bot_manager=fake_manager,
            chat_repo=InMemoryTelegramChatRepository(),
            strategy_dir=FakeStrategyDirectory([]),
            session_store=InMemoryTelegramSessionStore(),
            allowed_users=frozenset({123}),
        )

        result = await use_case.execute(
            TelegramCommandRequest(
                command="/history", args="", chat_id=1,
                user_id=123, message_id=1,
            )
        )

        assert result.text  # should not crash
        assert "No runs" in result.text or "runs" in result.text.lower()


class TestList:
    @pytest.mark.asyncio
    async def test_list_returns_strategy_files(self):
        """/list shows available strategy files."""
        use_case = HandleTelegramCommand(
            bot_manager=FakeBotManager(),
            chat_repo=InMemoryTelegramChatRepository(),
            strategy_dir=FakeStrategyDirectory([
                "macd_cross.yaml", "trend_follow.yaml"
            ]),
            session_store=InMemoryTelegramSessionStore(),
            allowed_users=frozenset({123}),
        )

        result = await use_case.execute(
            TelegramCommandRequest(
                command="/list", args="", chat_id=1,
                user_id=123, message_id=1,
            )
        )

        assert "macd\_cross" in result.text
        assert "trend\_follow" in result.text


class TestPanic:
    @pytest.mark.asyncio
    async def test_panic_running_infers_symbol_from_current_run(self):
        """/panic when running shows symbol and action options."""
        fake_manager = FakeBotManager(is_running=True, bot_run_id="r_abc123")
        fake_manager.get_status = lambda: {
            "is_running": True,
            "bot_run_id": "r_abc123",
            "symbol": "BTC",
            "interval": "1h",
            "mode": "LIVE",
            "uptime_seconds": 3600,
            "total_signals": 10,
            "total_orders": 5,
            "total_fills": 4,
        }
        fake_manager.cancel_all_orders = lambda symbol: {"status": "ok"}
        fake_manager.close_position = lambda symbol: {"status": "ok"}

        use_case = HandleTelegramCommand(
            bot_manager=fake_manager,
            chat_repo=InMemoryTelegramChatRepository(),
            strategy_dir=FakeStrategyDirectory([]),
            session_store=InMemoryTelegramSessionStore(),
            allowed_users=frozenset({123}),
        )

        result = await use_case.execute(
            TelegramCommandRequest(
                command="/panic", args="", chat_id=1,
                user_id=123, message_id=1,
            )
        )

        assert "BTC" in result.text
        assert result.reply_markup is not None

    @pytest.mark.asyncio
    async def test_panic_idle_asks_for_symbol_selection(self):
        """/panic when idle shows symbol picker first."""
        fake_manager = FakeBotManager(is_running=False)

        use_case = HandleTelegramCommand(
            bot_manager=fake_manager,
            chat_repo=InMemoryTelegramChatRepository(),
            strategy_dir=FakeStrategyDirectory([]),
            session_store=InMemoryTelegramSessionStore(),
            allowed_users=frozenset({123}),
        )

        result = await use_case.execute(
            TelegramCommandRequest(
                command="/panic", args="", chat_id=1,
                user_id=123, message_id=1,
            )
        )

        # Should show symbol picker
        assert result.reply_markup is not None


class TestMuteUnmute:
    @pytest.mark.asyncio
    async def test_mute_disables_notifications(self):
        """/mute disables notifications for this chat."""
        from finbot.core.domain.entities.telegram_chat import TelegramChat

        fake_repo = InMemoryTelegramChatRepository()
        await fake_repo.add_chat(TelegramChat(
            chat_id=1, user_id=123, notifications_enabled=True
        ))

        use_case = HandleTelegramCommand(
            bot_manager=FakeBotManager(),
            chat_repo=fake_repo,
            strategy_dir=FakeStrategyDirectory([]),
            session_store=InMemoryTelegramSessionStore(),
            allowed_users=frozenset({123}),
        )

        result = await use_case.execute(
            TelegramCommandRequest(
                command="/mute", args="", chat_id=1,
                user_id=123, message_id=1,
            )
        )

        chat = await fake_repo.get_chat(1)
        assert chat is not None
        assert chat.notifications_enabled is False
        assert "muted" in result.text.lower()

    @pytest.mark.asyncio
    async def test_unmute_reenables_notifications(self):
        """/unmute re-enables notifications."""
        from finbot.core.domain.entities.telegram_chat import TelegramChat

        fake_repo = InMemoryTelegramChatRepository()
        await fake_repo.add_chat(TelegramChat(
            chat_id=1, user_id=123, notifications_enabled=False
        ))

        use_case = HandleTelegramCommand(
            bot_manager=FakeBotManager(),
            chat_repo=fake_repo,
            strategy_dir=FakeStrategyDirectory([]),
            session_store=InMemoryTelegramSessionStore(),
            allowed_users=frozenset({123}),
        )

        result = await use_case.execute(
            TelegramCommandRequest(
                command="/unmute", args="", chat_id=1,
                user_id=123, message_id=1,
            )
        )

        chat = await fake_repo.get_chat(1)
        assert chat is not None
        assert chat.notifications_enabled is True
        assert "unmuted" in result.text.lower()


class TestSymbolCommand:
    """/symbol activates a symbol (trading-control spec)."""

    @pytest.mark.asyncio
    async def test_symbol_activates_and_replies(self):
        from tests.fakes_telegram import FakeBotManager

        fake_manager = FakeBotManager()
        use_case = HandleTelegramCommand(
            bot_manager=fake_manager,
            chat_repo=InMemoryTelegramChatRepository(),
            strategy_dir=FakeStrategyDirectory([]),
            session_store=InMemoryTelegramSessionStore(),
            allowed_users=frozenset({1}),
        )

        result = await use_case.execute(
            TelegramCommandRequest(
                command="/symbol", args="BTC", chat_id=1, user_id=1, message_id=1,
            )
        )

        assert "BTC" in result.text
        assert fake_manager.get_active_symbol() is not None
        assert fake_manager.get_active_symbol().symbol == "BTC"

    @pytest.mark.asyncio
    async def test_symbol_no_args_shows_picker(self):
        from tests.fakes_telegram import FakeBotManager

        fake_manager = FakeBotManager()
        use_case = HandleTelegramCommand(
            bot_manager=fake_manager,
            chat_repo=InMemoryTelegramChatRepository(),
            strategy_dir=FakeStrategyDirectory([]),
            session_store=InMemoryTelegramSessionStore(),
            allowed_users=frozenset({1}),
        )

        result = await use_case.execute(
            TelegramCommandRequest(
                command="/symbol", args="", chat_id=1, user_id=1, message_id=1,
            )
        )

        # No crash; returns some guidance text
        assert result.text


class TestTradingControlHandlers:
    """Smoke tests for the trading-control command handlers (wiring)."""

    def _use_case(self):
        from tests.fakes_telegram import FakeBotManager

        return HandleTelegramCommand(
            bot_manager=FakeBotManager(),
            chat_repo=InMemoryTelegramChatRepository(),
            strategy_dir=FakeStrategyDirectory([]),
            session_store=InMemoryTelegramSessionStore(),
            allowed_users=frozenset({1}),
        )

    @pytest.mark.asyncio
    async def test_config_view_returns_keys(self):
        uc = self._use_case()
        result = await uc.execute(
            TelegramCommandRequest(command="/config", args="", chat_id=1, user_id=1, message_id=1)
        )
        assert "max_position" in result.text

    @pytest.mark.asyncio
    async def test_config_update_returns_ok(self):
        uc = self._use_case()
        result = await uc.execute(
            TelegramCommandRequest(command="/config", args="max_position 500", chat_id=1, user_id=1, message_id=1)
        )
        assert "500" in result.text

    @pytest.mark.asyncio
    async def test_leverage_requires_symbol(self):
        uc = self._use_case()
        result = await uc.execute(
            TelegramCommandRequest(command="/leverage", args="5", chat_id=1, user_id=1, message_id=1)
        )
        assert "symbol" in result.text.lower()

    @pytest.mark.asyncio
    async def test_long_requires_symbol(self):
        uc = self._use_case()
        result = await uc.execute(
            TelegramCommandRequest(command="/long", args="0.01", chat_id=1, user_id=1, message_id=1)
        )
        assert "symbol" in result.text.lower()

    @pytest.mark.asyncio
    async def test_symbol_then_price(self):
        uc = self._use_case()
        await uc.execute(
            TelegramCommandRequest(command="/symbol", args="BTC", chat_id=1, user_id=1, message_id=1)
        )
        result = await uc.execute(
            TelegramCommandRequest(command="/price", args="", chat_id=1, user_id=1, message_id=1)
        )
        assert "BTC" in result.text
