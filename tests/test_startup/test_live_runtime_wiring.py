"""Composition-root smoke tests for the live trading runtime (S1).

These tests exercise ``create_live_trading_runtime_use_case`` end-to-end
to catch wiring regressions that unit tests of individual components miss:

* **C1** — the testnet/live runtime must actually submit orders to the
  Hyperliquid SDK.  On ``main`` the factory wires
  ``order_normalizer=None``, ``cloid_generator=None`` and
  ``metadata_provider=None``, so ``OrderSubmitter.submit`` hits its
  early-return guard and the SDK is never called.
* **C5** — ``MaxLeverageGate`` must be constructed with
  ``Settings.max_leverage`` (not the disabled default ``0``), and the
  risk context must supply a ``leverage`` value for the gate to read.

The Hyperliquid SDK (``Info``, ``Exchange``) is the only external
boundary mocked — everything else (gateway, normalizer, cloid generator,
submission strategy, risk-gate chain) runs with real production wiring.
The strategy evaluator and indicator calculator are swapped for
deterministic fakes after construction because C1 is specifically about
*submission* wiring, not strategy correctness (which ``test_replay_*``
covers).
"""

from __future__ import annotations

import time
from decimal import Decimal

from finbot.config.settings import Settings
from finbot.core.domain.entities.position_direction import PositionDirection
from finbot.core.domain.entities.position_snapshot import PositionSnapshot
from finbot.core.domain.entities.signal_action import SignalAction
from finbot.core.domain.entities.signal_decision import SignalDecision
from finbot.startup.service_factory import create_live_trading_runtime_use_case
from tests.fakes import FakeStrategyEvaluator, InMemoryIndicatorEngine

STRATEGY_PATH = "tests/fixtures/strategies/amt_dip_buyer_final.yaml"


# ---------------------------------------------------------------------------
# Fake SDK — external boundary, records observable state (no call-count mocks)
# ---------------------------------------------------------------------------


class FakeHyperliquidInfo:
    """Fake ``hyperliquid.info.Info`` — canned position/meta/price state."""

    def __init__(self, *args, **kwargs) -> None:
        self.user_address = kwargs.get("user_address", "")

    def user_state(self, address: str) -> dict:
        return {
            "assetPositions": [],
            "marginSummary": {
                "accountValue": "10000",
                "initialMargin": "0",
                "availableMargin": "10000",
            },
        }

    def meta(self) -> dict:
        return {
            "universe": [
                {
                    "name": "BTC",
                    "szDecimals": 5,
                    "coinCdcDecimalPlaces": 0,
                    "maxLeverage": 50,
                }
            ]
        }

    def all_mids(self) -> dict:
        return {"BTC": "96000"}

    def open_orders(self, address: str) -> list:
        return []

    def perp_dexs(self) -> list:
        return []


class FakeHyperliquidExchange:
    """Fake ``hyperliquid.exchange.Exchange`` — records submitted orders."""

    def __init__(self) -> None:
        self.submitted_orders: list[dict] = []

    def market_open(self, **kwargs) -> dict:
        self.submitted_orders.append({"method": "market_open", **kwargs})
        return {"status": "ok", "response": {"type": "order", "data": {}}}

    def order(self, **kwargs) -> dict:
        self.submitted_orders.append({"method": "order", **kwargs})
        return {"status": "ok", "response": {"type": "order", "data": {}}}

    def update_leverage(self, **kwargs) -> dict:
        return {"status": "ok"}

    def bulk_cancel(self, cancels) -> dict:
        return {"status": "ok"}

    def cancel_by_cloid(self, symbol, cloid) -> dict:
        return {"status": "ok"}

    def cancel(self, symbol, oid) -> dict:
        return {"status": "ok"}

    def market_close(self, **kwargs) -> dict:
        return {"status": "ok"}


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _test_settings(**overrides) -> Settings:
    """Build a Settings instance with testnet-safe defaults."""
    base = {
        "mode": "testnet",
        "hyperliquid_testnet": True,
        "hyperliquid_private_key": "0x" + "ab" * 32,
        "hyperliquid_account_address": "0xabc",
        "hyperliquid_vault_address": "",
        "max_position_usd": Decimal("1000"),
        "max_daily_loss_usd": Decimal("25"),
        "max_open_orders": 3,
        "stale_data_seconds": 120,
        "max_leverage": 20,
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


def _recent_bars(count: int, *, base_ts: int) -> list[dict]:
    """Contiguous hourly bars ending at ``base_ts`` (no gap, not stale)."""
    return [
        {
            "timestamp": base_ts - (count - i) * 3600,
            "open": 95000.0 + i,
            "high": 95200.0 + i,
            "low": 94800.0 + i,
            "close": 95100.0 + i,
            "volume": 10.0,
        }
        for i in range(count)
    ]


# Monotonic counter ensures each test gets a unique candle timestamp so the
# DuplicateSignalGate (backed by the shared factory SQLite repo) never sees a
# collision between tests in the same class.
_ts_counter = [0]


def _fresh_timestamp() -> int:
    """Return a timestamp unique within this test process (recent + monotonic)."""
    _ts_counter[0] += 3600
    return int(time.time()) + _ts_counter[0]


def _recent_closed_candle(*, ts: int) -> dict:
    """A closed candle contiguous with ``_recent_bars`` and recent enough
    to pass the stale-data gate."""
    return {
        "timestamp": ts,
        "open": 95000.0,
        "high": 96500.0,
        "low": 94900.0,
        "close": 96000.0,
        "volume": 20.0,
    }


def _patch_sdk(monkeypatch, fake_exchange) -> None:
    """Patch the Hyperliquid SDK at the module boundary for the whole test.

    The gateway imports ``Info`` / ``Exchange`` lazily inside ``_ensure_*``,
    so the patches must persist beyond factory construction — otherwise the
    first ``process_closed_candle`` call hits the real network.
    """
    monkeypatch.setattr("hyperliquid.info.Info", FakeHyperliquidInfo)
    monkeypatch.setattr("hyperliquid.exchange.Exchange", lambda **kw: fake_exchange)


def _build_testnet_runtime(monkeypatch, *, fake_exchange, settings=None, base_ts):
    """Build a testnet runtime via the real composition root.

    Patches ``Settings`` and the two Hyperliquid SDK entry points so the
    factory's real wiring runs against fakes at the SDK boundary only.
    """
    settings = settings or _test_settings()
    monkeypatch.setattr("finbot.startup.runtime_factory.Settings", lambda: settings)
    _patch_sdk(monkeypatch, fake_exchange)
    return create_live_trading_runtime_use_case(
        STRATEGY_PATH,
        "BTC",
        "1h",
        mode="testnet",
        live_data=False,
        warmup_bars=_recent_bars(30, base_ts=base_ts),
    )


def _swap_to_deterministic_long_entry(runtime, *, ts: int) -> None:
    """Replace evaluator + indicator so a closed candle yields LONG_ENTRY.

    C1 is about submission wiring, not strategy correctness.  The real
    strategy + indicator engines are exercised by ``test_replay_*``.
    """
    runtime._evaluator = FakeStrategyEvaluator(
        signal=SignalDecision(
            action=SignalAction.LONG_ENTRY,
            symbol="BTC",
            interval="1h",
            candle_timestamp=ts,
            strategy_hash="h",
        )
    )
    runtime._indicator_calc = InMemoryIndicatorEngine(
        latest_bar={"close": 96000.0, "timestamp": ts}
    )
    runtime._required_columns = set()
    runtime._required_indicators = []


# ---------------------------------------------------------------------------
# S1 — Testnet/live orders actually reach the exchange (C1, C5)
# ---------------------------------------------------------------------------


class TestTestnetRuntimeSubmissionWiring:
    """C1: the factory-built testnet runtime submits real orders to the SDK."""

    def test_submission_components_are_wired(self, monkeypatch):
        """The runtime has a real normalizer, cloid generator, and metadata
        provider — none of which the factory wires on ``main``."""
        fake_exchange = FakeHyperliquidExchange()
        runtime = _build_testnet_runtime(
            monkeypatch, fake_exchange=fake_exchange, base_ts=_fresh_timestamp()
        )

        assert (
            runtime._order_normalizer is not None
        ), "OrderNormalizer not wired — orders will never reach the exchange"
        assert (
            runtime._cloid_gen is not None
        ), "CloidGenerator not wired — idempotent submission impossible"
        assert (
            runtime._metadata_provider is not None
        ), "MarketMetadataProvider not wired"

    def test_long_entry_signal_reaches_sdk_exchange(self, monkeypatch):
        """A long_entry signal causes the gateway to call the SDK Exchange
        with a cloid'd order."""
        ts = _fresh_timestamp()
        fake_exchange = FakeHyperliquidExchange()
        runtime = _build_testnet_runtime(
            monkeypatch, fake_exchange=fake_exchange, base_ts=ts
        )
        _swap_to_deterministic_long_entry(runtime, ts=ts)

        runtime.start("strat", "BTC", "1h")
        runtime.process_closed_candle(_recent_closed_candle(ts=ts))

        assert (
            fake_exchange.submitted_orders
        ), "no order reached the SDK — submission wiring is broken"
        order = fake_exchange.submitted_orders[-1]
        assert order.get("cloid") is not None, f"cloid missing: {order!r}"
        assert float(order.get("sz", 0)) > 0

    def test_order_response_persisted_with_ok_status(self, monkeypatch):
        """After submission, the runtime persists an order_response row."""
        ts = _fresh_timestamp()
        fake_exchange = FakeHyperliquidExchange()
        runtime = _build_testnet_runtime(
            monkeypatch, fake_exchange=fake_exchange, base_ts=ts
        )
        _swap_to_deterministic_long_entry(runtime, ts=ts)

        runtime.start("strat", "BTC", "1h")
        result = runtime.process_closed_candle(_recent_closed_candle(ts=ts))

        assert result.submitted is True
        response = runtime._repo.get_last_order_response()
        assert response is not None, "order_response not persisted"
        assert response.status == "ok"


class TestMaxLeverageGateWiring:
    """C5: MaxLeverageGate uses Settings.max_leverage and the risk context
    supplies ``leverage``."""

    def test_settings_max_leverage_defaults_to_20(self):
        settings = Settings(
            mode="dry_run",
            hyperliquid_private_key="0x" + "ab" * 32,
        )
        assert settings.max_leverage == 20

    def test_gate_wired_from_settings_max_leverage(self, monkeypatch):
        """The runtime's MaxLeverageGate carries Settings.max_leverage, not
        the disabled default of 0."""
        from finbot.core.domain.services.risk_gates.max_leverage_gate import (
            MaxLeverageGate,
        )

        fake_exchange = FakeHyperliquidExchange()
        runtime = _build_testnet_runtime(
            monkeypatch,
            fake_exchange=fake_exchange,
            settings=_test_settings(max_leverage=7),
            base_ts=_fresh_timestamp(),
        )

        leverage_gates = [
            g for g in runtime._order_planner._gates if isinstance(g, MaxLeverageGate)
        ]
        assert len(leverage_gates) == 1
        assert (
            leverage_gates[0]._max == 7
        ), "MaxLeverageGate not wired with Settings.max_leverage"

    def test_risk_context_includes_leverage(self, monkeypatch):
        """``_build_risk_context`` supplies a ``leverage`` int for the gate."""
        fake_exchange = FakeHyperliquidExchange()
        runtime = _build_testnet_runtime(
            monkeypatch, fake_exchange=fake_exchange, base_ts=_fresh_timestamp()
        )
        runtime._symbol = "BTC"
        runtime._bot_run_id = "test-run"
        pos = PositionSnapshot(
            symbol="BTC", direction=PositionDirection.FLAT, size=Decimal("0")
        )

        ctx = runtime._build_risk_context({"close": 96000.0}, pos)

        assert "leverage" in ctx, "risk context missing 'leverage' key"
        assert isinstance(ctx["leverage"], int)
        assert ctx["leverage"] >= 1

    def test_gate_rejects_when_leverage_exceeds_cap(self):
        """Characterisation: the gate rejects entries above its cap."""
        from finbot.core.domain.services.risk_gates.max_leverage_gate import (
            MaxLeverageGate,
        )

        gate = MaxLeverageGate(max_leverage=10)
        signal = SignalDecision(
            action=SignalAction.LONG_ENTRY,
            symbol="BTC",
            interval="1h",
            candle_timestamp=0,
            strategy_hash="h",
        )
        decision = gate.check(signal, {"leverage": 20})
        assert not decision.accepted
        assert decision.gate_name == "max_leverage"


# ---------------------------------------------------------------------------
# Multi-timeframe factory wiring (Scenario 2)
# ---------------------------------------------------------------------------


class TestMTFFactoryIntervalOverride:
    """Scenario 2: Runtime factory overrides interval from strategy YAML."""

    MTF_STRATEGY = "strategies/14_amt_value_reject_30m_1h_mtf.yaml"
    SINGLE_TF_STRATEGY = "tests/fixtures/strategies/amt_dip_buyer_final.yaml"

    def test_mtf_strategy_overrides_interval_to_yaml_primary(self, monkeypatch):
        """When the strategy declares MTF timeframes, the runtime factory
        overrides the caller's interval with the YAML primary."""
        settings = _test_settings(mode="dry_run")
        monkeypatch.setattr("finbot.startup.runtime_factory.Settings", lambda: settings)

        runtime = create_live_trading_runtime_use_case(
            self.MTF_STRATEGY,
            "BTC",
            "1h",  # caller passes 1h, but YAML says 30min
            mode="dry_run",
            live_data=False,
            warmup_bars=_recent_bars(30, base_ts=int(time.time())),
        )

        assert (
            runtime._interval == "30min"
        ), f"Expected 30min from YAML, got {runtime._interval}"

    def test_mtf_strategy_sets_informative_intervals(self, monkeypatch):
        """The runtime receives informative_intervals from the strategy YAML."""
        settings = _test_settings(mode="dry_run")
        monkeypatch.setattr("finbot.startup.runtime_factory.Settings", lambda: settings)

        runtime = create_live_trading_runtime_use_case(
            self.MTF_STRATEGY,
            "BTC",
            "1h",
            mode="dry_run",
            live_data=False,
            warmup_bars=_recent_bars(30, base_ts=int(time.time())),
        )

        assert hasattr(
            runtime, "_informative_intervals"
        ), "Runtime missing _informative_intervals attribute"
        assert runtime._informative_intervals == [
            "1h"
        ], f"Expected ['1h'], got {runtime._informative_intervals}"

    def test_single_tf_strategy_preserves_caller_interval(self, monkeypatch):
        """Single-TF strategies: the caller's interval is used unchanged."""
        settings = _test_settings(mode="dry_run")
        monkeypatch.setattr("finbot.startup.runtime_factory.Settings", lambda: settings)

        runtime = create_live_trading_runtime_use_case(
            self.SINGLE_TF_STRATEGY,
            "BTC",
            "4h",
            mode="dry_run",
            live_data=False,
            warmup_bars=_recent_bars(30, base_ts=int(time.time())),
        )

        assert (
            runtime._interval == "4h"
        ), f"Expected 4h (caller's), got {runtime._interval}"

    def test_single_tf_strategy_no_informative_intervals(self, monkeypatch):
        """Single-TF strategies have empty informative_intervals."""
        settings = _test_settings(mode="dry_run")
        monkeypatch.setattr("finbot.startup.runtime_factory.Settings", lambda: settings)

        runtime = create_live_trading_runtime_use_case(
            self.SINGLE_TF_STRATEGY,
            "BTC",
            "1h",
            mode="dry_run",
            live_data=False,
            warmup_bars=_recent_bars(30, base_ts=int(time.time())),
        )

        assert hasattr(runtime, "_informative_intervals")
        assert runtime._informative_intervals == []
