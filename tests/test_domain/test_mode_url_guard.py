"""Tests for the mode/URL consistency guard (S3, C4).

Pure helper tests + an integration test that the MCP ``start_bot`` tool
rejects mode/testnet-flag combinations that would route orders to the
wrong environment (e.g. ``mode=testnet`` with the mainnet URL selected).

On ``main`` the CLI has an inline guard for this; the MCP tool has none,
so ``start_bot(mode="testnet")`` with ``FINBOT_HYPERLIQUID_TESTNET=false``
would sign and submit orders against mainnet while the bot believed it
was on testnet.
"""

from __future__ import annotations

import json

import pytest

from finbot.core.domain.services.mode_url_guard import check_mode_url_consistency


class TestCheckModeUrlConsistency:
    """Pure helper: returns reasons list (empty = consistent)."""

    def test_testnet_mode_with_testnet_flag_is_consistent(self):
        assert (
            check_mode_url_consistency(mode="testnet", hyperliquid_testnet=True) == []
        )

    def test_live_mode_with_mainnet_flag_is_consistent(self):
        assert check_mode_url_consistency(mode="live", hyperliquid_testnet=False) == []

    def test_dry_run_with_either_flag_is_consistent(self):
        # Dry-run never submits, so the URL choice is informational only.
        assert (
            check_mode_url_consistency(mode="dry_run", hyperliquid_testnet=False) == []
        )
        assert (
            check_mode_url_consistency(mode="dry_run", hyperliquid_testnet=True) == []
        )

    def test_testnet_mode_with_mainnet_flag_is_rejected(self):
        reasons = check_mode_url_consistency(mode="testnet", hyperliquid_testnet=False)
        assert len(reasons) == 1
        assert "TESTNET" in reasons[0].upper()

    def test_live_mode_with_testnet_flag_is_rejected(self):
        reasons = check_mode_url_consistency(mode="live", hyperliquid_testnet=True)
        assert len(reasons) == 1
        assert "LIVE" in reasons[0].upper() or "MAINNET" in reasons[0].upper()


class TestMCPStartBotModeUrlGuard:
    """C4: MCP start_bot rejects mode/URL inconsistency before BotManager.start."""

    def test_start_bot_rejects_testnet_mode_with_mainnet_url(self, monkeypatch):
        """start_bot(mode='testnet') with FINBOT_HYPERLIQUID_TESTNET=false is
        rejected without constructing a runtime."""
        from finbot.config.settings import Settings
        from tests.test_presentation.test_mcp_tools import _build_tools

        mainnet_settings = Settings(
            mode="dry_run",
            hyperliquid_testnet=False,
            hyperliquid_private_key="0x" + "ab" * 32,
        )
        monkeypatch.setattr(
            "finbot.presentation.mcp.tools.bot_control.Settings",
            lambda: mainnet_settings,
        )
        tools = _build_tools()
        try:
            result = tools["start_bot"](
                strategy_path="tests/fixtures/strategies/amt_dip_buyer_final.yaml",
                symbol="BTC",
                interval="1h",
                mode="testnet",
                warmup_bars=0,
            )
            data = json.loads(result)
            assert data["status"] == "rejected"
            assert "TESTNET" in data.get("message", "").upper()
        finally:
            tools["stop_bot"]()

    def test_start_bot_rejects_live_mode_with_testnet_url(self, monkeypatch):
        from finbot.config.settings import Settings
        from tests.test_presentation.test_mcp_tools import _build_tools

        testnet_settings = Settings(
            mode="dry_run",
            hyperliquid_testnet=True,
            hyperliquid_private_key="0x" + "ab" * 32,
        )
        monkeypatch.setattr(
            "finbot.presentation.mcp.tools.bot_control.Settings",
            lambda: testnet_settings,
        )
        tools = _build_tools()
        try:
            result = tools["start_bot"](
                strategy_path="tests/fixtures/strategies/amt_dip_buyer_final.yaml",
                symbol="BTC",
                interval="1h",
                mode="live",
                warmup_bars=0,
            )
            data = json.loads(result)
            assert data["status"] == "rejected"
        finally:
            tools["stop_bot"]()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
