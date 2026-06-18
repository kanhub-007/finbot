"""Tests for active symbol state management — Classical school, black-box.

Covers the trading-control spec: the bot starts fully idle (no active symbol),
and an active symbol must be selected before manual orders / leverage work.
"""

import time

from finbot.infrastructure.repositories.in_memory_bot_state_repository import (
    InMemoryBotStateRepository,
)
from tests.fakes import FakeExchangeGateway


def _make_manager(repo=None, exchange=None):
    """Build a real BotManager with in-memory fakes at the boundaries."""
    from finbot.core.domain.services.bot_manager import BotManager

    repo = repo or InMemoryBotStateRepository()
    factory = lambda **kw: None  # noqa: E731 — runtime not needed for state tests
    return BotManager(
        runtime_factory=factory,
        repository=repo,
        exchange=exchange or FakeExchangeGateway(),
        startup_time=time.time(),
    )


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
