"""RequiredColumnCollector — collect bar columns needed by strategies."""

from finbot.core.domain.entities.condition import Condition
from finbot.core.domain.entities.operand import Operand
from finbot.core.domain.entities.strategy_definition import StrategyDefinition
from finbot.core.domain.interfaces.condition_tree_visitor import ConditionTreeVisitor

_ENGINE_REQUIRED_COLUMNS = ("open", "high", "low", "close")
_COLUMN_OPERAND_KINDS = {"field", "indicator", "feature", "column"}


class RequiredColumnCollector(ConditionTreeVisitor):
    """Collect concrete bar columns used by a strategy condition tree.

    The collector includes OHLC columns required by the backtest engine and all
    field/indicator/feature/column operands referenced by entry or exit rules.
    """

    def __init__(self) -> None:
        """Initialize an empty collector."""
        self._columns: list[str] = []

    def collect(self, definition: StrategyDefinition) -> list[str]:
        """Return required concrete bar columns for a strategy definition."""
        self._columns = []
        for column in _ENGINE_REQUIRED_COLUMNS:
            self._add(column)
        for rules in definition.sides.values():
            self.visit_group(rules.entry)
            self.visit_group(rules.exit)
        self._add_risk_columns(definition)
        self._add_formula_columns(definition)
        return list(self._columns)

    def visit_condition(self, condition: Condition) -> None:
        """Collect columns referenced by an atomic condition."""
        self._add_operand(condition.left)
        if condition.right is not None:
            self._add_operand(condition.right)

    def _add_operand(self, operand: Operand) -> None:
        if operand.kind in _COLUMN_OPERAND_KINDS:
            self._add(str(operand.value))

    def _add_risk_columns(self, definition: StrategyDefinition) -> None:
        risk = definition.risk
        if risk is None:
            return
        if risk.stop_loss_type == "atr" and risk.stop_indicator:
            self._add(risk.stop_indicator)
        if risk.take_profit_type == "atr" and risk.take_profit_indicator:
            self._add(risk.take_profit_indicator)

    def _add(self, column: str) -> None:
        if column not in self._columns:
            self._columns.append(column)

    def _add_formula_columns(self, definition: StrategyDefinition) -> None:
        """Collect indicator columns referenced inside formula features."""
        for feature in definition.features:
            if feature.type != "formula" or feature.raw_expr is None:
                continue
            _collect_formula_expr_columns(feature.raw_expr, self._add)


def _collect_formula_expr_columns(expr: dict, add) -> None:
    """Walk formula expression tree and collect indicator column names."""
    if not isinstance(expr, dict):
        return
    for key in ("left", "right", "operand"):
        val = expr.get(key)
        if isinstance(val, str) and not val.lstrip("-").replace(".", "").isdigit():
            add(val)
        elif isinstance(val, dict):
            _collect_formula_expr_columns(val, add)
    for child in expr.get("children", []):
        if isinstance(child, dict):
            _collect_formula_expr_columns(child, add)
        elif isinstance(child, str):
            add(child)
