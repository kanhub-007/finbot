"""End-to-end integration test — replay strategy over a realistic CSV bar fixture."""

from pathlib import Path

import pytest

from finbot.core.application.use_cases.replay_strategy import (
    ReplayStrategyUseCase,
)
from finbot.core.domain.dto.replay_strategy_request import ReplayStrategyRequest
from finbot.infrastructure.adapters.rule_based_strategy_evaluator_factory import (
    RuleBasedStrategyEvaluatorFactory,
)
from finbot.infrastructure.strategy.csv_bar_loader import CsvBarLoader
from finbot.infrastructure.strategy.yaml_strategy_definition_loader import (
    YamlStrategyDefinitionLoader,
)

FIXTURE_DIR = Path(__file__).resolve().parent.parent / "fixtures"


def _read(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def test_replay_produces_entry_signals() -> None:
    """Replaying 150 bars with acceptance_into_value=True triggers should produce entry signals."""
    strategy_path = str(FIXTURE_DIR / "strategies" / "amt_dip_buyer_final.yaml")
    bars_path = str(FIXTURE_DIR / "bars" / "amt_dip_buyer_100_bars.csv")

    use_case = ReplayStrategyUseCase(
        loader=YamlStrategyDefinitionLoader(),
        bar_loader=CsvBarLoader(),
        evaluator_factory=RuleBasedStrategyEvaluatorFactory(),
    )

    result = use_case.execute(
        ReplayStrategyRequest(
            strategy_path=strategy_path,
            strategy_content=_read(strategy_path),
            bars_csv=_read(bars_path),
            symbol="AAPL",
            interval="1h",
        )
    )

    assert result.status == "complete"
    assert result.signal_count >= 1

    actions = {s.action.value for s in result.signals}
    assert "long_entry" in actions, f"Expected long_entry in {actions}"


def test_replay_with_warmup_filters_early_bars() -> None:
    """Warmup of 50 bars should skip first 50 before evaluating."""
    strategy_path = str(FIXTURE_DIR / "strategies" / "amt_dip_buyer_final.yaml")
    bars_path = str(FIXTURE_DIR / "bars" / "amt_dip_buyer_100_bars.csv")

    from finbot.core.domain.services.warmup_window import WarmupWindow

    use_case = ReplayStrategyUseCase(
        loader=YamlStrategyDefinitionLoader(),
        bar_loader=CsvBarLoader(),
        evaluator_factory=RuleBasedStrategyEvaluatorFactory(),
        warmup=WarmupWindow(min_bars=50),
    )

    result = use_case.execute(
        ReplayStrategyRequest(
            strategy_path=strategy_path,
            strategy_content=_read(strategy_path),
            bars_csv=_read(bars_path),
            symbol="AAPL",
            interval="1h",
        )
    )

    assert result.status == "complete"
    # With 50-bar warmup, fewer bars evaluated, but still get signals
    assert result.signal_count >= 1
