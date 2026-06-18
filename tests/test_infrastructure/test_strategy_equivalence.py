"""
Test that Finbot's SharedRuntimeStrategyEvaluator produces the same signals
as the finbar_strategy_runtime package when fed identical bars.

This is a correctness-critical test: if these diverge, live trading will
not match backtest expectations. The test is black-box: it feeds identical
bars to both the package strategy and the Finbot evaluator, then compares
every signal (action, bar index, confidence) for exact match.

Design:
  - Only mock external boundaries: none (pure domain comparison).
  - Real StrategyDefinitionParser, real StrategyDefinitionFactory,
    real SharedRuntimeStrategyEvaluatorFactory.
  - Assert on outcomes (signal actions), not interactions.
  - Survives refactoring: only breaks when signal output actually changes.
"""

from __future__ import annotations

import csv
import hashlib
import io
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from finbar_strategy_runtime.evaluation.strategy_definition_factory import (
    StrategyDefinitionFactory,
)
from finbar_strategy_runtime.parser.strategy_definition_parser import (
    StrategyDefinitionParser,
)

from finbot.core.domain.entities.position_direction import PositionDirection
from finbot.core.domain.entities.position_snapshot import PositionSnapshot
from finbot.core.domain.entities.signal_action import SignalAction
from finbot.core.domain.interfaces.strategy_evaluator import StrategyEvaluator
from finbot.infrastructure.adapters.shared_runtime_strategy_evaluator import (
    SharedRuntimeStrategyEvaluator,
)
from finbot.infrastructure.adapters.shared_runtime_strategy_evaluator_factory import (
    SharedRuntimeStrategyEvaluatorFactory,
)
from finbot.infrastructure.strategy.yaml_strategy_definition_loader import (
    YamlStrategyDefinitionLoader,
)

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"

# ── Helpers ──────────────────────────────────────────────────────────────


def _load_csv(path: Path) -> list[dict[str, object]]:
    """Load enriched bars CSV, coercing types."""
    content = path.read_text(encoding="utf-8")
    reader = csv.DictReader(io.StringIO(content))
    bars: list[dict[str, object]] = []
    for row in reader:
        bar: dict[str, object] = {}
        for key, val in row.items():
            stripped = val.strip()
            if stripped.lower() in ("true", "false"):
                bar[key] = stripped.lower() == "true"
            else:
                try:
                    bar[key] = int(stripped)
                except ValueError:
                    try:
                        bar[key] = float(stripped)
                    except ValueError:
                        bar[key] = stripped
        bars.append(bar)
    return bars


def _flat_position() -> PositionSnapshot:
    return PositionSnapshot(
        symbol="TEST", direction=PositionDirection.FLAT, size=Decimal("0")
    )


def _evaluate_with_package(
    strategy_content: str, bars: list[dict[str, object]]
) -> list[dict[str, Any]]:
    """Feed bars through the finbar_strategy_runtime package directly.

    Returns list of {bar_index, action, direction, ...} for non-HOLD signals.
    """
    parser = StrategyDefinitionParser()
    result = parser.parse(strategy_content)
    if not result.valid or result.definition is None:
        errors = "; ".join(e.message for e in result.errors)
        raise ValueError(f"Strategy validation failed: {errors}")

    strategy = StrategyDefinitionFactory().create(result.definition)
    signals: list[dict[str, Any]] = []
    position: dict[str, Any] = {"size": 0, "direction": ""}

    for i, bar in enumerate(bars):
        signal = strategy.on_bar(bar, position)
        if signal.action == "hold":
            continue

        signals.append(
            {
                "bar_index": i,
                "action": signal.action,
                "direction": signal.direction,
                "confidence": signal.confidence,
                "stop_price": signal.stop_price,
                "target_price": signal.target_price,
                "close": bar.get("close"),
            }
        )

        # Track position for exit-side resolution
        if signal.direction == "exit":
            position = {"size": 0, "direction": ""}
        elif signal.action == "buy" and signal.direction == "long":
            position = {"size": 1, "direction": "long"}
        elif signal.action == "sell" and signal.direction == "short":
            position = {"size": 1, "direction": "short"}

    return signals


def _evaluate_with_finbot(
    strategy_content: str, bars: list[dict[str, object]]
) -> list[dict[str, Any]]:
    """Feed bars through Finbot's SharedRuntimeStrategyEvaluator.

    Returns list of {bar_index, action, ...} for non-HOLD signals.
    """
    loader = YamlStrategyDefinitionLoader()
    definition = loader.load_from_text(strategy_content)

    strategy_hash = hashlib.sha256(strategy_content.encode()).hexdigest()[:12]
    evaluator = SharedRuntimeStrategyEvaluator(
        StrategyDefinitionFactory().create(definition),
        symbol="TEST",
        interval="1h",
        strategy_hash=strategy_hash,
    )

    position = _flat_position()
    signals: list[dict[str, Any]] = []

    for i, bar in enumerate(bars):
        decision = evaluator.evaluate(bar, position)
        if decision.action == SignalAction.HOLD:
            continue

        signals.append(
            {
                "bar_index": i,
                "action": decision.action.value,
                "confidence": decision.confidence,
                "stop_price": (
                    float(decision.stop_price)
                    if decision.stop_price is not None
                    else None
                ),
                "target_price": (
                    float(decision.target_price)
                    if decision.target_price is not None
                    else None
                ),
                "close": bar.get("close"),
            }
        )

        # Track position
        if decision.action in (SignalAction.LONG_ENTRY, SignalAction.SHORT_ENTRY):
            direction = (
                PositionDirection.LONG
                if decision.action == SignalAction.LONG_ENTRY
                else PositionDirection.SHORT
            )
            position = PositionSnapshot(
                symbol="TEST",
                direction=direction,
                size=Decimal("1"),
                entry_price=Decimal(str(bar.get("close", 0))),
            )
        elif decision.action in (SignalAction.LONG_EXIT, SignalAction.SHORT_EXIT):
            position = _flat_position()

    return signals


def _map_package_action(pkg_action: str, pkg_direction: str, pos: str) -> str:
    """Map package (action, direction) to Finbot action string."""
    if pkg_action == "buy" and pkg_direction == "long":
        return "long_entry"
    if pkg_action == "sell" and pkg_direction == "short":
        return "short_entry"
    if pkg_direction == "exit":
        return "long_exit" if pos == "long" else "short_exit"
    raise ValueError(f"Unknown: action={pkg_action!r} direction={pkg_direction!r}")


def _compare_signals(
    pkg_signals: list[dict[str, Any]], finbot_signals: list[dict[str, Any]]
) -> tuple[bool, str]:
    """Compare signal lists. Returns (passed, message)."""
    if len(pkg_signals) != len(finbot_signals):
        return False, (
            f"Signal count mismatch: package={len(pkg_signals)}, "
            f"finbot={len(finbot_signals)}"
        )

    pos = "flat"
    for i, (pkg, fbt) in enumerate(zip(pkg_signals, finbot_signals)):
        pkg_mapped = _map_package_action(pkg["action"], pkg["direction"], pos)

        # Update position tracking for next signal
        if "entry" in pkg_mapped:
            pos = "long" if "long" in pkg_mapped else "short"
        elif "exit" in pkg_mapped:
            pos = "flat"

        if pkg["bar_index"] != fbt["bar_index"]:
            return False, (
                f"Signal {i}: bar_index mismatch: "
                f"package={pkg['bar_index']}, finbot={fbt['bar_index']}"
            )
        if pkg_mapped != fbt["action"]:
            return False, (
                f"Signal {i}: action mismatch @ bar {pkg['bar_index']}: "
                f"package={pkg_mapped}, finbot={fbt['action']}"
            )
        if abs(pkg["confidence"] - fbt["confidence"]) > 0.001:
            return False, (
                f"Signal {i}: confidence mismatch @ bar {pkg['bar_index']}: "
                f"package={pkg['confidence']}, finbot={fbt['confidence']}"
            )

    return True, f"All {len(pkg_signals)} signals match"


# ── Fixtures ─────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def amt_strategy() -> str:
    """Load the AMT dip buyer strategy."""
    return (FIXTURES / "strategies" / "amt_dip_buyer_final.yaml").read_text(
        encoding="utf-8"
    )


@pytest.fixture(scope="module")
def amt_bars() -> list[dict[str, object]]:
    """Load the AMT dip buyer enriched bars."""
    return _load_csv(FIXTURES / "bars" / "amt_dip_buyer_100_bars.csv")


@pytest.fixture(scope="module")
def trend_strategy() -> str:
    """Load the trend momentum strategy."""
    return (FIXTURES / "strategies" / "trend_momentum_v2.yaml").read_text(
        encoding="utf-8"
    )


@pytest.fixture(scope="module")
def trend_bars() -> list[dict[str, object]]:
    """Load the trend momentum enriched bars."""
    return _load_csv(FIXTURES / "bars" / "trend_momentum_bars.csv")


# ── Tests ────────────────────────────────────────────────────────────────


class TestStrategyEquivalence:
    """Verify Finbot evaluator == package strategy for all fixtures."""

    def test_amt_dip_buyer_signals_match(
        self, amt_strategy: str, amt_bars: list[dict[str, object]]
    ) -> None:
        """AMT dip buyer: package signals must match Finbot signals exactly."""
        pkg = _evaluate_with_package(amt_strategy, amt_bars)
        fbt = _evaluate_with_finbot(amt_strategy, amt_bars)

        passed, msg = _compare_signals(pkg, fbt)
        assert passed, msg
        assert len(pkg) > 0, "Expected at least one signal from AMT dip buyer"

    def test_trend_momentum_signals_match(
        self, trend_strategy: str, trend_bars: list[dict[str, object]]
    ) -> None:
        """Trend momentum: package signals must match Finbot signals exactly."""
        pkg = _evaluate_with_package(trend_strategy, trend_bars)
        fbt = _evaluate_with_finbot(trend_strategy, trend_bars)

        assert len(pkg) > 0, "Expected at least one signal from trend momentum"
        passed, msg = _compare_signals(pkg, fbt)
        assert passed, msg

    def test_amt_dip_buyer_produces_entry_and_exit(
        self, amt_strategy: str, amt_bars: list[dict[str, object]]
    ) -> None:
        """AMT dip buyer should produce at least one entry AND exit."""
        pkg = _evaluate_with_package(amt_strategy, amt_bars)

        entries = sum(1 for s in pkg if "exit" not in s["direction"])
        exits = sum(1 for s in pkg if s["direction"] == "exit")
        assert entries > 0, "No entry signals produced"
        assert exits > 0, "No exit signals produced"
        assert entries == exits, f"Unbalanced: {entries} entries, {exits} exits"

    def test_confidence_in_range(
        self, amt_strategy: str, amt_bars: list[dict[str, object]]
    ) -> None:
        """All signals must have confidence in [0, 1]."""
        pkg = _evaluate_with_package(amt_strategy, amt_bars)
        for s in pkg:
            assert 0.0 <= s["confidence"] <= 1.0, (
                f"Confidence out of range: {s['confidence']} at bar {s['bar_index']}"
            )

    def test_stop_price_set_for_entries(
        self, amt_strategy: str, amt_bars: list[dict[str, object]]
    ) -> None:
        """Entry signals must have a stop price set."""
        pkg = _evaluate_with_package(amt_strategy, amt_bars)
        for s in pkg:
            if s["direction"] != "exit":
                assert s["stop_price"] is not None and s["stop_price"] > 0, (
                    f"Missing stop price at bar {s['bar_index']}"
                )

    def test_exit_signals_use_position_direction(
        self, amt_strategy: str, amt_bars: list[dict[str, object]]
    ) -> None:
        """Exit signals from the Finbot evaluator must resolve to the
        correct exit side based on the current position direction."""
        fbt = _evaluate_with_finbot(amt_strategy, amt_bars)

        exit_signals = [s for s in fbt if "exit" in s["action"]]
        assert len(exit_signals) > 0, "No exit signals to verify"

        for s in exit_signals:
            assert s["action"] in ("long_exit", "short_exit"), (
                f"Unexpected exit action: {s['action']}"
            )

    def test_signal_idempotency_keys_present(
        self, amt_strategy: str, amt_bars: list[dict[str, object]]
    ) -> None:
        """Every non-HOLD Finbot SignalDecision must carry a signal_key."""
        loader = YamlStrategyDefinitionLoader()
        definition = loader.load_from_text(amt_strategy)

        strategy_hash = hashlib.sha256(amt_strategy.encode()).hexdigest()[:12]
        evaluator = SharedRuntimeStrategyEvaluator(
            StrategyDefinitionFactory().create(definition),
            symbol="TEST",
            interval="1h",
            strategy_hash=strategy_hash,
        )

        position = _flat_position()
        signal_count = 0
        for bar in amt_bars:
            decision = evaluator.evaluate(bar, position)
            if decision.action != SignalAction.HOLD:
                signal_count += 1
                assert decision.signal_key, (
                    f"signal_key missing for {decision.action.value} "
                    f"at candle_timestamp={decision.candle_timestamp}"
                )
            # Track position
            if decision.action in (SignalAction.LONG_ENTRY, SignalAction.SHORT_ENTRY):
                direction = (
                    PositionDirection.LONG
                    if decision.action == SignalAction.LONG_ENTRY
                    else PositionDirection.SHORT
                )
                position = PositionSnapshot(
                    symbol="TEST",
                    direction=direction,
                    size=Decimal("1"),
                )
            elif decision.action in (
                SignalAction.LONG_EXIT,
                SignalAction.SHORT_EXIT,
            ):
                position = _flat_position()

        assert signal_count > 0, "No signals to check idempotency keys for"
