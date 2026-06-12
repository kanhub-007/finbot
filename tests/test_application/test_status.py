"""Tests for the status CLI command."""

from decimal import Decimal

from finbot.core.application.use_cases.status import StatusUseCase
from finbot.core.domain.entities.bot_run import BotRun
from finbot.core.domain.entities.order_intent import OrderIntent
from finbot.core.domain.entities.order_response_record import (
    OrderResponseRecord,
)
from finbot.core.domain.entities.order_side import OrderSide
from finbot.core.domain.entities.order_type import OrderType
from finbot.core.domain.entities.processed_signal import ProcessedSignal
from finbot.infrastructure.repositories.in_memory_bot_state_repository import (
    InMemoryBotStateRepository,
)


class TestStatusUseCase:
    def test_status_reports_last_signal_and_last_order(self) -> None:
        repo = InMemoryBotStateRepository()
        repo.create_bot_run(
            BotRun(
                strategy_name="amt_dip",
                strategy_hash="abc",
                symbol="BTC",
                interval="1h",
                mode="dry_run",
                run_id="r1",
            )
        )
        repo.mark_signal_processed(
            ProcessedSignal(
                signal_key="sig1",
                bot_run_id="r1",
                signal_action="long_entry",
                bar_timestamp="2025-01-01T09:00",
            )
        )

        intent = OrderIntent(
            symbol="BTC",
            side=OrderSide.BUY,
            size=Decimal("0.001"),
            order_type=OrderType.LIMIT,
            signal_key="sig1",
        )
        intent_id = repo.record_order_intent(intent)

        # Let the in-memory repo track order responses differently than
        # the SQL one — directly store for the status query.
        repo._responses[intent_id]["response"] = OrderResponseRecord(
            intent_id=intent_id,
            bot_run_id="r1",
            response_json="{}",
            status="accepted",
        )

        uc = StatusUseCase(repo)
        result = uc.execute()

        assert result.strategy_name == "amt_dip"
        assert result.last_signal_key == "sig1"
        assert result.last_signal_action == "long_entry"
        assert result.last_order_intent_id == intent_id
        assert result.last_order_status == "accepted"
        assert result.total_signals == 1
        assert result.total_orders == 1

    def test_status_handles_empty_repository(self) -> None:
        repo = InMemoryBotStateRepository()
        uc = StatusUseCase(repo)
        result = uc.execute()
        assert result.strategy_name == ""
        assert result.total_signals == 0
        assert result.total_orders == 0
        assert result.total_fills == 0
