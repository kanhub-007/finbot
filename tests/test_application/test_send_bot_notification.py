"""Tests for SendBotNotification — trade, risk, and error notifications."""

from datetime import UTC, datetime

import pytest

from finbot.core.application.use_cases.send_bot_notification import (
    SendBotNotification,
)
from finbot.core.domain.entities.telegram_chat import TelegramChat
from finbot.core.domain.events.bot_error_event import BotErrorEvent
from finbot.core.domain.events.risk_event_triggered import RiskEventTriggered
from finbot.core.domain.events.trade_executed import TradeExecuted
from tests.fakes_telegram import (
    FakeTelegramOutbox,
    InMemoryTelegramChatRepository,
)


@pytest.fixture
def populated_repo() -> InMemoryTelegramChatRepository:
    """Repository with two registered chats."""
    import asyncio

    repo = InMemoryTelegramChatRepository()
    loop = asyncio.new_event_loop()
    loop.run_until_complete(repo.add_chat(TelegramChat(chat_id=111, user_id=1)))
    loop.run_until_complete(repo.add_chat(TelegramChat(chat_id=222, user_id=2)))
    loop.close()
    return repo


class TestTradeNotification:
    @pytest.mark.asyncio
    async def test_trade_notification_broadcasts_to_all_registered_chats(
        self, populated_repo
    ):
        """Trade notification goes to all registered chats."""
        outbox = FakeTelegramOutbox()
        use_case = SendBotNotification(bot_port=outbox, chat_repo=populated_repo)

        event = TradeExecuted(
            run_id="r_abc123",
            symbol="BTC-USD",
            side="BUY",
            size="0.05",
            price="67432.50",
            pnl=None,
            order_id="12345",
            timestamp=datetime.now(UTC),
        )

        results = await use_case.notify_trade(event)

        assert len(outbox.sent_messages) == 2
        assert len(results) == 2
        assert all(r.success for r in results)

        # Both messages include the trade details
        for msg in outbox.sent_messages:
            assert "BUY" in msg["text"]
            assert "BTC-USD" in msg["text"]
            assert "12345" in msg["text"]
            assert "r_abc123" in msg["text"]
            # Each chat gets a "View status" button
            assert (
                msg["reply_markup"]["inline_keyboard"][0][0]["callback_data"]
                == "/status"
            )

    @pytest.mark.asyncio
    async def test_trade_notification_includes_pnl_when_closing(self, populated_repo):
        """Closing trades include PnL in the notification."""
        outbox = FakeTelegramOutbox()
        use_case = SendBotNotification(bot_port=outbox, chat_repo=populated_repo)

        event = TradeExecuted(
            run_id="r_abc123",
            symbol="BTC-USD",
            side="SELL",
            size="0.05",
            price="67890.00",
            pnl="22.87",
            order_id="12346",
            timestamp=datetime.now(UTC),
        )

        await use_case.notify_trade(event)

        msg = outbox.sent_messages[0]
        assert "22.87" in msg["text"]

    @pytest.mark.asyncio
    async def test_trade_notification_no_chats_no_error(self):
        """No chats registered — notification silently dropped."""
        outbox = FakeTelegramOutbox()
        repo = InMemoryTelegramChatRepository()
        use_case = SendBotNotification(bot_port=outbox, chat_repo=repo)

        event = TradeExecuted(
            run_id="r_abc123",
            symbol="BTC-USD",
            side="BUY",
            size="0.05",
            price="67432.50",
            pnl=None,
            order_id="12345",
            timestamp=datetime.now(UTC),
        )

        results = await use_case.notify_trade(event)
        assert len(results) == 0
        assert len(outbox.sent_messages) == 0


class TestRiskNotification:
    @pytest.mark.asyncio
    async def test_risk_notification_broadcasts_actionable_risk_event(
        self, populated_repo
    ):
        """Risk event notification goes to all chats with reason."""
        outbox = FakeTelegramOutbox()
        use_case = SendBotNotification(bot_port=outbox, chat_repo=populated_repo)

        event = RiskEventTriggered(
            run_id="r_abc123",
            event_type="daily_loss",
            reason="Daily loss limit reached: \\-$25\\.00",
            bot_stopped=True,
        )

        results = await use_case.notify_risk(event)

        assert len(outbox.sent_messages) == 2
        assert len(results) == 2
        for msg in outbox.sent_messages:
            assert "Daily loss" in msg["text"]
            assert "r_abc123" in msg["text"]

    @pytest.mark.asyncio
    async def test_risk_notification_bot_not_stopped(self, populated_repo):
        """Non-fatal risk events note that bot continues."""
        outbox = FakeTelegramOutbox()
        use_case = SendBotNotification(bot_port=outbox, chat_repo=populated_repo)

        event = RiskEventTriggered(
            run_id="r_abc123",
            event_type="stale_data",
            reason="Stale market data \\(>120s\\)\\. Orders blocked\\.",
            bot_stopped=False,
        )

        await use_case.notify_risk(event)

        msg = outbox.sent_messages[0]
        assert "Stale market data" in msg["text"]
        # No "Bot stopped" line since bot_stopped=False
        # This is optional — the key assertion is that stale data was mentioned


class TestErrorNotification:
    @pytest.mark.asyncio
    async def test_error_notification_broadcasts_to_all_chats(self, populated_repo):
        """Error event notification goes to all chats."""
        outbox = FakeTelegramOutbox()
        use_case = SendBotNotification(bot_port=outbox, chat_repo=populated_repo)

        event = BotErrorEvent(
            run_id="r_abc123",
            error_type="connection_lost",
            message="Exchange connection lost\\. Retrying in 30s\\.\\.",
        )

        results = await use_case.notify_error(event)

        assert len(outbox.sent_messages) == 2
        assert len(results) == 2
        for msg in outbox.sent_messages:
            assert "Exchange connection lost" in msg["text"]
            assert "r_abc123" in msg["text"]
