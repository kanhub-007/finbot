"""Optional parity tests comparing Finbot runtime against Finbar.

These tests require a local Finbar checkout. Set the environment variable
to enable them:

    FINBOT_FINBAR_PARITY_PATH=/path/to/finbar pytest -m finbar_parity

Without the env var, all tests in this file are skipped.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

if not os.environ.get("FINBOT_FINBAR_PARITY_PATH"):
    pytest.skip(
        "FINBOT_FINBAR_PARITY_PATH not set — skipping parity tests",
        allow_module_level=True,
    )

_FINBAR_PATH = Path(os.environ["FINBOT_FINBAR_PARITY_PATH"]).resolve()
if not _FINBAR_PATH.is_dir():
    pytest.skip(
        f"FINBOT_FINBAR_PARITY_PATH={_FINBAR_PATH} is not a directory",
        allow_module_level=True,
    )

# Add Finbar to sys.path for imports.
sys.path.insert(0, str(_FINBAR_PATH))

# Lazy imports — only resolve when tests run.
_finbar_loader = None
_finbar_evaluator = None
_finbar_risk_calc = None


def _get_finbar_loader():
    global _finbar_loader
    if _finbar_loader is None:
        from finbar.core.application.services.strategy_definition_parser import (
            StrategyDefinitionParser,
        )

        _finbar_loader = StrategyDefinitionParser()
    return _finbar_loader


def _get_finbar_evaluator():
    global _finbar_evaluator
    if _finbar_evaluator is None:
        from finbar.infrastructure.services.condition_evaluator import (
            ConditionEvaluator,
        )

        _finbar_evaluator = ConditionEvaluator()
    return _finbar_evaluator


def _get_finbar_risk_calc():
    global _finbar_risk_calc
    if _finbar_risk_calc is None:
        from finbar.infrastructure.services.json_risk_price_calculator import (
            JsonRiskPriceCalculator,
        )

        _finbar_risk_calc = JsonRiskPriceCalculator()
    return _finbar_risk_calc


# --- Finbot imports (always available) ---
from finbot.core.domain.entities.condition import Condition  # noqa: E402
from finbot.core.domain.entities.condition_group import ConditionGroup  # noqa: E402
from finbot.core.domain.entities.operand import Operand  # noqa: E402
from finbot.infrastructure.strategy.yaml_strategy_definition_loader import (  # noqa: E402
    YamlStrategyDefinitionLoader,
)

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "strategies"


@pytest.mark.finbar_parity
class TestFinbarStrategyParity:
    """Compare Finbot outputs against the same inputs in Finbar."""

    def test_parse_target_strategy_matches_finbar(self) -> None:
        """Both should parse the AMT dip buyer strategy with identical name
        and indicator count."""
        finbot_loader = YamlStrategyDefinitionLoader()
        finbot_def = finbot_loader.load_from_file(
            str(FIXTURES_DIR / "amt_dip_buyer_final.yaml")
        )

        finbar_loader = _get_finbar_loader()
        content = (FIXTURES_DIR / "amt_dip_buyer_final.yaml").read_text(
            encoding="utf-8"
        )
        finbar_result = finbar_loader.parse(content)
        assert (
            finbar_result.valid
        ), f"Finbar rejected its own strategy: {finbar_result.errors}"
        finbar_def = finbar_result.definition

        assert finbot_def.name == finbar_def.name
        assert len(finbot_def.indicators) == len(finbar_def.indicators)
        assert finbot_def.schema_version == finbar_def.schema_version

    def test_condition_signal_matches_finbar_on_synthetic_bar(
        self,
    ) -> None:
        """Both evaluators should produce identical results on the same
        condition tree and bar."""
        fb_eval = _get_finbar_evaluator()
        from finbot.infrastructure.strategy.condition_evaluator import (
            ConditionEvaluator as FinbotEvaluator,
        )

        fbot_eval = FinbotEvaluator()

        # Simple condition: acceptance_into_value is true
        cond = Condition(
            left=Operand(kind="indicator", value="acceptance_into_value"),
            operator="is_true",
        )
        group = ConditionGroup(kind="condition", condition=cond)
        bar = {"acceptance_into_value": True}

        fb_result = fb_eval.evaluate(group, bar, {})
        fbot_result = fbot_eval.evaluate(group, bar, {})

        assert fb_result == fbot_result, f"Finbar={fb_result}, Finbot={fbot_result}"

        bar2 = {"acceptance_into_value": False}
        fb2 = fb_eval.evaluate(group, bar2, {})
        fbot2 = fbot_eval.evaluate(group, bar2, {})
        assert fb2 == fbot2

    def test_risk_stop_target_matches_finbar_on_synthetic_bar(
        self,
    ) -> None:
        """Both risk calculators should produce identical stop/target prices."""
        fb_calc = _get_finbar_risk_calc()
        from finbot.infrastructure.strategy.json_risk_price_calculator import (
            JsonRiskPriceCalculator as FinbotRiskCalc,
        )

        fbot_calc = FinbotRiskCalc()

        # Equivalent RiskSpec
        from finbot.core.domain.entities.risk_spec import RiskSpec

        risk = RiskSpec(
            stop_loss_type="atr",
            stop_indicator="atr",
            stop_multiplier=3.5,
            take_profit_type="risk_reward",
            risk_reward_ratio=1.5,
        )
        bar = {"close": 100.0, "atr": 2.0}

        fb_stop, fb_target = fb_calc.calculate(risk, bar, "long")
        fbot_stop, fbot_target = fbot_calc.calculate(risk, bar, "long")

        assert fb_stop == fbot_stop, f"Stop: Finbar={fb_stop}, Finbot={fbot_stop}"
        assert (
            fb_target == fbot_target
        ), f"Target: Finbar={fb_target}, Finbot={fbot_target}"
