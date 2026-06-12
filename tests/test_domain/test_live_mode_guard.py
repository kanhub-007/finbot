"""Tests for live mode safety gate."""

from finbot.core.domain.services.live_mode_guard import check_live_mode


class TestLiveModeGuard:
    def test_live_mode_with_all_gates_passes(self) -> None:
        result = check_live_mode(
            mode="live",
            live_trading_ack=True,
            private_key="a" * 64,
            max_position_usd=100,
            database_path="/opt/finbot/data/finbot.db",
        )
        assert result.allowed
        assert len(result.reasons) == 0

    def test_live_mode_without_ack_is_rejected(self) -> None:
        result = check_live_mode(
            mode="live",
            live_trading_ack=False,
            private_key="a" * 64,
            max_position_usd=100,
            database_path="/opt/finbot/data/finbot.db",
        )
        assert not result.allowed
        assert any("ACK" in r for r in result.reasons)

    def test_live_mode_without_private_key_is_rejected(self) -> None:
        result = check_live_mode(
            mode="live",
            live_trading_ack=True,
            private_key="",
            max_position_usd=100,
            database_path="/opt/finbot/data/finbot.db",
        )
        assert not result.allowed
        assert any("PRIVATE_KEY" in r for r in result.reasons)

    def test_live_mode_without_max_position_is_rejected(self) -> None:
        result = check_live_mode(
            mode="live",
            live_trading_ack=True,
            private_key="a" * 64,
            max_position_usd=0,
            database_path="/opt/finbot/data/finbot.db",
        )
        assert not result.allowed
        assert any("MAX_POSITION" in r for r in result.reasons)

    def test_live_mode_without_db_path_is_rejected(self) -> None:
        result = check_live_mode(
            mode="live",
            live_trading_ack=True,
            private_key="a" * 64,
            max_position_usd=100,
            database_path="data/finbot.db",  # default → rejected
        )
        assert not result.allowed
        assert any("DATABASE_URL" in r for r in result.reasons)

    def test_non_live_mode_skips_all_checks(self) -> None:
        result = check_live_mode(
            mode="dry_run",
            live_trading_ack=False,
            private_key="",
            max_position_usd=0,
            database_path="data/finbot.db",
        )
        assert not result.allowed
        assert "MODE" in result.reasons[0]
