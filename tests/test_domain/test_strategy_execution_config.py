"""Tests for strategy execution config (leverage/margin from YAML).

Slice 2: when a strategy YAML declares an optional ``execution`` block,
starting the bot reads leverage from it and syncs to the exchange.
"""

import time
from decimal import Decimal

from finbot.core.domain.entities.strategy_execution_config import (
    StrategyExecutionConfig,
)
from finbot.infrastructure.repositories.in_memory_bot_state_repository import (
    InMemoryBotStateRepository,
)
from tests.fakes import FakeExchangeGateway, FakeRuntime


def _make_manager(exchange=None, repo=None):
    from finbot.core.domain.services.bot_manager import BotManager

    repo = repo or InMemoryBotStateRepository()
    runtime = FakeRuntime(repo=repo)
    return BotManager(
        runtime_factory=lambda **kw: runtime,
        repository=repo,
        exchange=exchange or FakeExchangeGateway(),
        startup_time=time.time(),
    )


class TestStrategyExecutionConfig:
    """Scenario: leverage from strategy YAML execution block."""

    def test_start_with_execution_leverage_calls_set_leverage(self):
        """Starting a strategy with execution.leverage syncs to exchange."""
        exchange = FakeExchangeGateway()
        manager = _make_manager(exchange=exchange)
        manager.activate_symbol("BTC")

        exec_cfg = StrategyExecutionConfig(leverage=3, margin_mode="isolated")
        manager.start(
            strategy_path="tests/fixtures/strategies/amt_dip_buyer_final.yaml",
            symbol="BTC",
            interval="1h",
            mode="dry_run",
            warmup_bars=0,
            execution_config=exec_cfg,
        )

        assert ("BTC", 3, "isolated") in exchange.set_leverage_calls
        # ActiveSymbolState updated too
        assert manager.get_active_symbol().leverage == 3

    def test_start_without_execution_config_does_not_call_set_leverage(self):
        """No execution block → leverage unchanged (no exchange call)."""
        exchange = FakeExchangeGateway()
        manager = _make_manager(exchange=exchange)
        manager.activate_symbol("BTC")

        manager.start(
            strategy_path="tests/fixtures/strategies/amt_dip_buyer_final.yaml",
            symbol="BTC",
            interval="1h",
            mode="dry_run",
            warmup_bars=0,
        )

        assert exchange.set_leverage_calls == []

    def test_start_with_execution_cross_margin(self):
        """execution.margin_mode: cross is honoured."""
        exchange = FakeExchangeGateway()
        manager = _make_manager(exchange=exchange)
        manager.activate_symbol("BTC")

        manager.start(
            strategy_path="tests/fixtures/strategies/amt_dip_buyer_final.yaml",
            symbol="BTC",
            interval="1h",
            mode="dry_run",
            warmup_bars=0,
            execution_config=StrategyExecutionConfig(
                leverage=5, margin_mode="cross"
            ),
        )

        assert ("BTC", 5, "cross") in exchange.set_leverage_calls


class TestParseStrategyExecution:
    """Parsing the execution block from raw strategy YAML text."""

    def test_parse_extracts_leverage_and_margin_mode(self):
        from finbot.core.domain.services.strategy_execution_parser import (
            parse_strategy_execution,
        )

        yaml_text = (
            "schema_version: '2.0'\n"
            "name: test\n"
            "execution:\n"
            "  leverage: 3\n"
            "  margin_mode: cross\n"
        )
        cfg = parse_strategy_execution(yaml_text)

        assert cfg is not None
        assert cfg.leverage == 3
        assert cfg.margin_mode == "cross"

    def test_parse_returns_none_when_no_execution_block(self):
        from finbot.core.domain.services.strategy_execution_parser import (
            parse_strategy_execution,
        )

        yaml_text = "schema_version: '2.0'\nname: test\n"
        cfg = parse_strategy_execution(yaml_text)

        assert cfg is None

    def test_parse_defaults_margin_mode_to_isolated(self):
        from finbot.core.domain.services.strategy_execution_parser import (
            parse_strategy_execution,
        )

        yaml_text = "execution:\n  leverage: 2\n"
        cfg = parse_strategy_execution(yaml_text)

        assert cfg is not None
        assert cfg.margin_mode == "isolated"
