"""Tests for BotLiveState strict update (S18: M2)."""

import pytest

from finbot.core.domain.services.bot_live_state import BotLiveState


class TestBotLiveStateStrict:
    def test_update_rejects_unknown_field(self):
        state = BotLiveState()
        with pytest.raises(TypeError):
            state.update(stategy_name="typo")
        state.update(strategy_name="ok")
        assert state.strategy_name == "ok"

    def test_unknown_field_message_names_the_field(self):
        state = BotLiveState()
        with pytest.raises(TypeError, match="stategy_name"):
            state.update(stategy_name="x")
