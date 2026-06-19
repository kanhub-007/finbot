"""Tests for the composition root — factory wiring of safety-critical paths.

Covers:
* C1: the Hyperliquid gateway is built with credentials and the
  environment-appropriate URL (testnet vs mainnet).
* C2: the live runtime's OrderPlanner is wired with the full risk-gate
  chain so no gate is silently dropped.
"""

from decimal import Decimal

import pytest

from finbot.config.settings import Settings
from finbot.core.domain.entities.trading_mode import TradingMode
from finbot.infrastructure.adapters.dry_run_exchange_gateway import (
    DryRunExchangeGateway,
)
from finbot.infrastructure.adapters.hyperliquid_exchange_gateway import (
    HyperliquidExchangeGateway,
)
from finbot.startup.service_factory import (
    _build_exchange_gateway,
    hyperliquid_base_url,
)


def _settings(**overrides) -> Settings:
    base = {
        "mode": "dry_run",
        "hyperliquid_testnet": True,
        "hyperliquid_private_key": "0x" + "ab" * 32,
        "hyperliquid_account_address": "0xabc",
        "hyperliquid_vault_address": "",
        "max_position_usd": Decimal("100"),
        "max_daily_loss_usd": Decimal("25"),
        "max_open_orders": 3,
        "stale_data_seconds": 120,
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


class TestHyperliquidBaseUrl:
    def test_testnet_flag_selects_testnet_url(self) -> None:
        assert (
            hyperliquid_base_url(_settings(hyperliquid_testnet=True))
            == "https://api.hyperliquid-testnet.xyz"
        )

    def test_mainnet_flag_selects_mainnet_url(self) -> None:
        assert (
            hyperliquid_base_url(_settings(hyperliquid_testnet=False))
            == "https://api.hyperliquid.xyz"
        )


class TestBuildExchangeGateway:
    def test_dry_run_uses_noop_gateway(self) -> None:
        gateway = _build_exchange_gateway(
            _settings(mode="dry_run"), TradingMode.DRY_RUN
        )
        assert isinstance(gateway, DryRunExchangeGateway)

    def test_live_gateway_is_wired_with_credentials(self) -> None:
        gateway = _build_exchange_gateway(
            _settings(mode="live", hyperliquid_testnet=False), TradingMode.LIVE
        )
        assert isinstance(gateway, HyperliquidExchangeGateway)
        # Credentials must flow through from settings, not be dropped.
        # The key is stored as a redacting PrivateKey value object (S4/M5);
        # ``.raw`` exposes the value at the signing boundary.
        assert gateway._private_key.raw == "0x" + "ab" * 32
        assert "0x" + "ab" * 32 not in repr(gateway)
        assert gateway._account_address == "0xabc"
        assert gateway._base_url == "https://api.hyperliquid.xyz"

    def test_testnet_gateway_uses_testnet_url(self) -> None:
        gateway = _build_exchange_gateway(
            _settings(mode="testnet", hyperliquid_testnet=True), TradingMode.TESTNET
        )
        assert isinstance(gateway, HyperliquidExchangeGateway)
        assert gateway._base_url == "https://api.hyperliquid-testnet.xyz"


class TestLiveRuntimeGateChain:
    """C2: the runtime planner must carry the full risk-gate chain."""

    @pytest.fixture
    def runtime(self) -> object:
        from finbot.startup.service_factory import create_live_trading_runtime_use_case

        return create_live_trading_runtime_use_case(
            "tests/fixtures/strategies/amt_dip_buyer_final.yaml",
            "BTC",
            "1h",
            mode="dry_run",
            live_data=False,
        )

    def test_full_gate_chain_is_wired(self, runtime: object) -> None:
        planner = runtime._order_planner  # type: ignore[attr-defined]
        gate_names = [type(g).__name__ for g in planner._gates]  # type: ignore[attr-defined]
        # Every safety gate must be present — none silently dropped.
        assert gate_names == [
            "ModeGate",
            "StaleDataGate",
            "MaxPositionGate",
            "MaxLeverageGate",
            "MaxOpenOrdersGate",
            "DailyLossGate",
            "ReduceOnlyGate",
            "DuplicateSignalGate",
        ]

    def test_gate_chain_enforces_max_position(self, runtime: object) -> None:
        """A clearly oversized entry is rejected by the wired chain."""
        from finbot.core.domain.entities.signal_action import SignalAction
        from finbot.core.domain.entities.signal_decision import (
            SignalDecision,
        )

        planner = runtime._order_planner  # type: ignore[attr-defined]
        signal = SignalDecision(
            action=SignalAction.LONG_ENTRY,
            symbol="BTC",
            interval="1h",
            candle_timestamp=1,
            strategy_hash="h",
        )
        # 1 BTC at ~50000 → notional 50000 >> max_position_usd (100).
        result = planner.plan(
            signal,
            {
                "bar": {"close": 50000.0, "timestamp": 9999999999},
                "proposed_size": Decimal("1"),
            },
        )
        assert not result.accepted
        assert result.gate_name == "max_position"
