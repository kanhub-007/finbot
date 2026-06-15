"""Tests for replay strategy use case."""

from pathlib import Path

from finbot.core.application.use_cases.replay_strategy import ReplayStrategyUseCase
from finbot.core.domain.dto.replay_strategy_request import ReplayStrategyRequest
from finbot.core.domain.services.warmup_window import WarmupWindow
from finbot.infrastructure.adapters.shared_runtime_strategy_evaluator_factory import (
    SharedRuntimeStrategyEvaluatorFactory,
)
from finbot.infrastructure.strategy.csv_bar_loader import CsvBarLoader
from finbot.infrastructure.strategy.yaml_strategy_definition_loader import (
    YamlStrategyDefinitionLoader,
)

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures"


def _use_case(warmup: WarmupWindow | None = None) -> ReplayStrategyUseCase:
    return ReplayStrategyUseCase(
        loader=YamlStrategyDefinitionLoader(),
        bar_loader=CsvBarLoader(),
        evaluator_factory=SharedRuntimeStrategyEvaluatorFactory(),
        warmup=warmup,
    )


def _read_strategy(name: str) -> str:
    return (FIXTURES_DIR / "strategies" / name).read_text(encoding="utf-8")


def _sample_bars_csv() -> str:
    return (FIXTURES_DIR / "bars" / "amt_sample_bars.csv").read_text(encoding="utf-8")


class TestReplayStrategy:
    def test_replay_runs_without_exchange_gateway(self) -> None:
        uc = _use_case()
        request = ReplayStrategyRequest(
            strategy_path="amt_dip_buyer_final.yaml",
            strategy_content=_read_strategy("amt_dip_buyer_final.yaml"),
            bars_csv=_sample_bars_csv(),
            symbol="BTC",
            interval="1h",
        )
        result = uc.execute(request)
        assert result.status == "complete"

    def test_replay_produces_signal_events(self) -> None:
        uc = _use_case()
        request = ReplayStrategyRequest(
            strategy_path="amt_dip_buyer_final.yaml",
            strategy_content=_read_strategy("amt_dip_buyer_final.yaml"),
            bars_csv=_sample_bars_csv(),
            symbol="BTC",
            interval="1h",
        )
        result = uc.execute(request)
        assert result.signal_count > 0
        assert len(result.signals) == result.signal_count

    def test_replay_uses_closed_bars_only(self) -> None:
        uc = _use_case()
        csv_bars = (
            "timestamp,open,high,low,close,volume,atr,acceptance_into_value\n"
            "2025-01-02T09:30,100,102,99,101,1000,2.0,False\n"
            "2025-01-02T10:30,101,103,100,102,1000,2.0,True\n"
        )
        request = ReplayStrategyRequest(
            strategy_path="test.yaml",
            strategy_content=_read_strategy("amt_dip_buyer_final.yaml"),
            bars_csv=csv_bars,
            symbol="BTC",
        )
        result = uc.execute(request)
        assert result.signal_count == 1
        assert result.signals[0].bar_index == 1

    def test_replay_prevents_duplicate_signal_keys(self) -> None:
        uc = _use_case()
        csv_bars = (
            "timestamp,open,high,low,close,volume,atr,acceptance_into_value\n"
            "2025-01-02T09:30,100,102,99,101,1000,2.0,True\n"
            "2025-01-02T10:30,101,103,100,102,1000,2.0,True\n"
        )
        request = ReplayStrategyRequest(
            strategy_path="test.yaml",
            strategy_content=_read_strategy("amt_dip_buyer_final.yaml"),
            bars_csv=csv_bars,
            symbol="BTC",
        )
        result = uc.execute(request)
        assert result.signal_count == 1

    def test_replay_reports_indicator_warmup_errors(self) -> None:
        uc = _use_case()
        request = ReplayStrategyRequest(
            strategy_path="test.yaml",
            strategy_content=_read_strategy("amt_dip_buyer_final.yaml"),
            bars_csv="timestamp,open,high,low,close,volume\n",
            symbol="BTC",
        )
        result = uc.execute(request)
        assert result.status == "complete"
        assert result.signal_count == 0


class TestReplayWithWarmup:
    def test_warmup_skips_early_bars(self) -> None:
        warmup = WarmupWindow(min_bars=3, max_length=10)
        uc = _use_case(warmup=warmup)
        request = ReplayStrategyRequest(
            strategy_path="t.yaml",
            strategy_content=_read_strategy("amt_dip_buyer_final.yaml"),
            bars_csv=_sample_bars_csv(),
            symbol="BTC",
        )
        result = uc.execute(request)
        # With warmup_min=3, first 3 bars are skipped; bar 3+ may trigger.
        assert result.signal_count >= 1
        for sig in result.signals:
            assert sig.bar_index >= 2, f"bar {sig.bar_index} emitted before warmup"

    def test_warmup_not_ready_blocks_all(self) -> None:
        warmup = WarmupWindow(min_bars=500, max_length=1000)
        uc = _use_case(warmup=warmup)
        request = ReplayStrategyRequest(
            strategy_path="t.yaml",
            strategy_content=_read_strategy("amt_dip_buyer_final.yaml"),
            bars_csv=_sample_bars_csv(),
            symbol="BTC",
        )
        result = uc.execute(request)
        assert result.signal_count == 0
