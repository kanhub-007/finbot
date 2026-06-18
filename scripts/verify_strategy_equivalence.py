"""
verify_strategy_equivalence.py

Validates that Finbot's SharedRuntimeStrategyEvaluator produces the same
signals as the finbar_strategy_runtime package when fed identical bars.

This is a correctness-critical test: if these diverge, live trading will
not match backtest expectations.

Usage:
    cd C:/HAL/Github/finbot
    python scripts/verify_strategy_equivalence.py

Output: PASS/FAIL with detailed comparison of every signal per bar.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# ── Path setup ───────────────────────────────────────────────────────────
FINBOT_ROOT = Path(__file__).resolve().parent.parent

sys.path.insert(0, str(FINBOT_ROOT))


def load_strategy_yaml(path: str) -> str:
    """Read a strategy YAML/JSON file as string content."""
    return Path(path).read_text(encoding="utf-8")


def load_bars_csv(csv_path: str) -> list[dict]:
    """Load enriched bars from a CSV file, coercing types."""
    import csv
    import io

    content = Path(csv_path).read_text(encoding="utf-8")
    reader = csv.DictReader(io.StringIO(content))
    bars = []
    for row in reader:
        bar: dict = {}
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


def run_package_strategy(
    strategy_content: str,
    bars: list[dict],
) -> list[dict]:
    """Feed bars through the finbar_strategy_runtime package directly.

    Returns a list of {bar_index, action, direction, confidence, ...} dicts
    for every non-HOLD signal.
    """
    from finbar_strategy_runtime.parser.strategy_definition_parser import (
        StrategyDefinitionParser,
    )
    from finbar_strategy_runtime.evaluation.strategy_definition_factory import (
        StrategyDefinitionFactory,
    )

    parser = StrategyDefinitionParser()
    result = parser.parse(strategy_content)
    if not result.valid or result.definition is None:
        errors = "; ".join(e.message for e in result.errors)
        raise ValueError(f"Strategy validation failed: {errors}")

    strategy = StrategyDefinitionFactory().create(result.definition)
    signals = []
    position = {"size": 0, "direction": ""}

    for i, bar in enumerate(bars):
        signal = strategy.on_bar(bar, position)
        if signal.action == "hold":
            continue

        signals.append({
            "bar_index": i,
            "action": signal.action,
            "direction": signal.direction,
            "confidence": signal.confidence,
            "stop_price": signal.stop_price,
            "target_price": signal.target_price,
            "close": bar.get("close"),
        })

        # Update position tracking
        if signal.direction == "exit":
            position = {"size": 0, "direction": ""}
        elif signal.action == "buy" and signal.direction == "long":
            position = {"size": 1, "direction": "long"}
        elif signal.action == "sell" and signal.direction == "short":
            position = {"size": 1, "direction": "short"}

    return signals


def run_finbot_evaluator(
    strategy_content: str,
    bars: list[dict],
    symbol: str,
    interval: str,
) -> list[dict]:
    """Feed bars through Finbot's SharedRuntimeStrategyEvaluator.

    Returns a list of {bar_index, action, ...} dicts for every non-HOLD signal.
    """
    from finbot.infrastructure.strategy.yaml_strategy_definition_loader import (
        YamlStrategyDefinitionLoader,
    )
    from finbot.infrastructure.adapters.shared_runtime_strategy_evaluator_factory import (
        SharedRuntimeStrategyEvaluatorFactory,
    )
    from finbot.core.domain.entities.position_snapshot import PositionSnapshot
    from finbot.core.domain.entities.position_direction import PositionDirection
    from finbot.core.domain.entities.signal_action import SignalAction
    from decimal import Decimal
    import hashlib

    loader = YamlStrategyDefinitionLoader()
    definition = loader.load_from_text(strategy_content)

    strategy_hash = hashlib.sha256(strategy_content.encode()).hexdigest()[:12]
    factory = SharedRuntimeStrategyEvaluatorFactory()
    evaluator = factory.create(definition, symbol=symbol, interval=interval, strategy_hash=strategy_hash)

    position = PositionSnapshot(
        symbol=symbol, direction=PositionDirection.FLAT, size=Decimal("0")
    )

    signals = []
    for i, bar in enumerate(bars):
        decision = evaluator.evaluate(bar, position)
        if decision.action == SignalAction.HOLD:
            continue

        signals.append({
            "bar_index": i,
            "action": decision.action.value,
            "confidence": decision.confidence,
            "stop_price": float(decision.stop_price) if decision.stop_price else None,
            "target_price": float(decision.target_price) if decision.target_price else None,
            "close": bar.get("close"),
        })

        # Update position tracking
        if decision.action in (SignalAction.LONG_ENTRY, SignalAction.SHORT_ENTRY):
            direction = (
                PositionDirection.LONG
                if decision.action == SignalAction.LONG_ENTRY
                else PositionDirection.SHORT
            )
            position = PositionSnapshot(
                symbol=symbol, direction=direction, size=Decimal("1"),
                entry_price=Decimal(str(bar.get("close", 0)))
            )
        elif decision.action in (SignalAction.LONG_EXIT, SignalAction.SHORT_EXIT):
            position = PositionSnapshot(
                symbol=symbol, direction=PositionDirection.FLAT, size=Decimal("0")
            )

    return signals


def map_package_to_finbot_action(pkg_action: str, pkg_direction: str) -> str:
    """Map package (action, direction) to finbot SignalAction."""
    if pkg_action == "hold":
        return "hold"
    if pkg_action == "buy" and pkg_direction == "long":
        return "long_entry"
    if pkg_action == "sell" and pkg_direction == "short":
        return "short_entry"
    if pkg_direction == "exit":
        # NOTE: in the package evaluator we track position state and resolve
        # exit side from that. Here we use a heuristic since we know our
        # position tracking matches.
        return "exit"  # resolved by context below
    raise ValueError(f"Unknown: action={pkg_action!r} direction={pkg_direction!r}")


def compare(package_signals: list[dict], finbot_signals: list[dict]) -> dict:
    """Compare signal sequences bar-by-bar."""
    issues = []

    # Map package signals to finbot action names for comparison
    pkg_mapped = []
    pos = "flat"
    for s in package_signals:
        mapped = map_package_to_finbot_action(s["action"], s["direction"])
        if mapped == "exit":
            mapped = "long_exit" if pos == "long" else "short_exit"
        pkg_mapped.append({**s, "mapped_action": mapped})
        if "entry" in mapped:
            pos = "long" if "long" in mapped else "short"
        elif "exit" in mapped:
            pos = "flat"

    if len(pkg_mapped) != len(finbot_signals):
        issues.append(
            f"SIGNAL COUNT MISMATCH: package={len(pkg_mapped)}, "
            f"finbot={len(finbot_signals)}"
        )

    max_len = max(len(pkg_mapped), len(finbot_signals))
    match_count = 0
    mismatch_count = 0

    for i in range(max_len):
        pkg = pkg_mapped[i] if i < len(pkg_mapped) else None
        fbt = finbot_signals[i] if i < len(finbot_signals) else None

        if pkg is None:
            issues.append(f"  Extra finbot signal at idx {i}: {fbt}")
            mismatch_count += 1
            continue
        if fbt is None:
            issues.append(f"  Extra package signal at idx {i}: {pkg}")
            mismatch_count += 1
            continue

        pkg_action = pkg["mapped_action"]
        fbt_action = fbt["action"]

        bar_ok = pkg["bar_index"] == fbt["bar_index"]
        action_ok = pkg_action == fbt_action

        if bar_ok and action_ok:
            match_count += 1
        else:
            mismatch_count += 1
            issues.append(
                f"  MISMATCH @ bar {pkg['bar_index']} vs {fbt['bar_index']}: "
                f"pkg={pkg_action} finbot={fbt_action} "
                f"(close={pkg.get('close')})"
            )

    passed = len(issues) == 0
    return {
        "passed": passed,
        "issues": issues,
        "summary": {
            "total_package_signals": len(package_signals),
            "total_finbot_signals": len(finbot_signals),
            "matches": match_count,
            "mismatches": mismatch_count,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify Finbot strategy evaluator matches finbar_strategy_runtime package"
    )
    parser.add_argument(
        "--strategy",
        default=str(
            FINBOT_ROOT / "tests/fixtures/strategies/amt_dip_buyer_final.yaml"
        ),
        help="Path to strategy YAML/JSON file",
    )
    parser.add_argument(
        "--bars",
        default=str(FINBOT_ROOT / "tests/fixtures/bars/amt_dip_buyer_100_bars.csv"),
        help="Path to enriched bars CSV",
    )
    parser.add_argument("--symbol", default="BTC", help="Trading symbol")
    parser.add_argument("--interval", default="1h", help="Bar interval")
    args = parser.parse_args()

    print(f"Strategy: {args.strategy}")
    print(f"Bars:     {args.bars}")
    print()

    strategy_content = load_strategy_yaml(args.strategy)
    bars = load_bars_csv(args.bars)
    print(f"Loaded {len(bars)} bars")

    # ── Run package strategy ─────────────────────────────────────────
    print("\n=== finbar_strategy_runtime (package) ===")
    try:
        package_signals = run_package_strategy(strategy_content, bars)
        print(f"Signals: {len(package_signals)}")
        for s in package_signals:
            print(
                f"  bar[{s['bar_index']}]: {s['action']}/{s['direction']} "
                f"@ close={s['close']} conf={s['confidence']:.2f}"
            )
    except Exception as e:
        print(f"  ERROR: {e}")
        import traceback
        traceback.print_exc()
        return 1

    # ── Run Finbot evaluator ─────────────────────────────────────────
    print("\n=== Finbot SharedRuntimeStrategyEvaluator ===")
    try:
        finbot_signals = run_finbot_evaluator(
            strategy_content, bars, args.symbol, args.interval
        )
        print(f"Signals: {len(finbot_signals)}")
        for s in finbot_signals:
            print(
                f"  bar[{s['bar_index']}]: {s['action']} "
                f"@ close={s['close']} conf={s['confidence']:.2f}"
            )
    except Exception as e:
        print(f"  ERROR: {e}")
        import traceback
        traceback.print_exc()
        return 1

    # ── Compare ──────────────────────────────────────────────────────
    result = compare(package_signals, finbot_signals)
    print(f"\n=== Comparison ===")
    print(f"Matches:   {result['summary']['matches']}")
    print(f"Mismatches: {result['summary']['mismatches']}")

    if result["issues"]:
        print("\nIssues:")
        for issue in result["issues"]:
            print(issue)

    if result["passed"]:
        print("\nPASS: All signals match between package and Finbot evaluator")
        return 0
    else:
        print("\nFAIL: Signal mismatches detected")
        return 1


if __name__ == "__main__":
    sys.exit(main())
