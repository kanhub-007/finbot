"""Regression tests for StaleDataGate timestamp handling (H1/H2)."""

import time

import numpy as np

from finbot.core.domain.entities.signal_action import SignalAction
from finbot.core.domain.entities.signal_decision import SignalDecision
from finbot.core.domain.services.risk_gates.stale_data_gate import StaleDataGate


def _sig() -> SignalDecision:
    return SignalDecision(
        action=SignalAction.LONG_ENTRY,
        symbol="BTC",
        interval="1h",
        candle_timestamp=0,
        strategy_hash="h",
    )


def test_gate_rejects_when_bar_has_explicit_int_timestamp() -> None:
    """H1: with a real timestamp in the bar, a stale bar is rejected."""
    stale_ts = int(time.time()) - 10000
    gate = StaleDataGate(max_age_seconds=120)
    d = gate.check(_sig(), {"bar": {"close": 100, "timestamp": stale_ts}})
    assert d.accepted is False
    assert "exceeds" in d.reason


def test_gate_rejects_numpy_int64_timestamp() -> None:
    """H2: numpy int64 timestamps must not bypass the staleness check."""
    stale_ts = np.int64(int(time.time()) - 10000)
    gate = StaleDataGate(max_age_seconds=120)
    d = gate.check(_sig(), {"bar": {"close": 100, "timestamp": stale_ts}})
    assert d.accepted is False


def test_gate_accepts_fresh_bar() -> None:
    fresh_ts = int(time.time()) - 10
    gate = StaleDataGate(max_age_seconds=120)
    d = gate.check(_sig(), {"bar": {"close": 100, "timestamp": fresh_ts}})
    assert d.accepted is True


def test_gate_accepts_when_timestamp_missing() -> None:
    """No timestamp => cannot prove staleness => accept (safe default)."""
    gate = StaleDataGate(max_age_seconds=120)
    d = gate.check(_sig(), {"bar": {"close": 100}})
    assert d.accepted is True
