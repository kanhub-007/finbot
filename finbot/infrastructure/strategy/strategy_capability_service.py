"""StrategyCapabilityService — compose SDK capability metadata."""

from finbot.core.domain.interfaces.indicator_capability_provider import (
    IndicatorCapabilityProvider,
)
from finbot.infrastructure.strategy.strategy_indicator_catalog import (
    StrategyIndicatorCatalog,
)

_FEATURE_TYPES = [
    "rolling_max",
    "rolling_min",
    "rolling_mean",
    "rolling_std",
    "shift",
    "body_pct",
    "range_pct",
    "typical_price",
    "ohlc4",
    "formula",
]
_OPERATORS = [
    "<",
    ">",
    "<=",
    ">=",
    "==",
    "!=",
    "crosses_above",
    "crosses_below",
    "between",
    "not_between",
    "is_true",
    "is_false",
    "exists",
    "missing",
]


class StrategyCapabilityService:
    """Return machine-readable capabilities for strategy authoring."""

    def __init__(self, catalog: IndicatorCapabilityProvider | None = None):
        """Create the service with injectable indicator capabilities."""
        self._catalog = catalog or StrategyIndicatorCatalog()

    def get_capabilities(self) -> dict:
        """Return the current strategy SDK capabilities."""
        return {
            "schema_version": "2.0",
            "orchestration": [
                "validate_strategy_definition",
                "fetch/query prices",
                "apply_indicators separately",
                "features auto-computed by backtest_strategy_definition",
                "backtest_strategy_definition with enriched bars",
            ],
            "backtest_calculates_indicators": False,
            "backtest_calculates_features": True,
            "fields": ["timestamp", "open", "high", "low", "close", "volume"],
            "features": {"supported_types": _FEATURE_TYPES},
            "execution_controls": {
                "risk_per_trade": "Fraction of equity risked at protective stop.",
                "leverage": "Buying-power multiplier; default 1.0 spot.",
                "risk_mode": ["fixed_equity_risk", "leverage_scaled_risk"],
                "commission_pct": "Per-side commission percentage as decimal.",
                "slippage_pct": "Directional fill slippage percentage as decimal.",
                "cap_explicit_size": "Cap explicit position_size to buying power.",
                "reject_oversized_explicit_orders": (
                    "Reject oversized explicit orders instead of capping."
                ),
                "allow_negative_cash": (
                    "Allow cash overdrafts only for advanced simulations."
                ),
                "market_calendar": ["equity_regular_hours", "crypto_24_7"],
            },
            "result_diagnostics": {
                "trust_diagnostics": "Execution model and assumption metadata.",
                "diagnostics": "Structured order capping/rejection diagnostics.",
                "reconciliation_error": "Final value reconciliation check.",
                "annualization_warning": "Metric annualization fallback warning.",
            },
            "side_rules_format": {
                "canonical": {
                    "entry": {"condition": {"operator": "is_true", "left": "signal"}},
                    "exit": {"condition": {"operator": "is_true", "left": "signal"}},
                },
                "shorthand_accepted": {
                    "entry": {"operator": "<", "left": "rsi_14", "right": 30},
                    "exit": {
                        "operator": "crosses_above",
                        "left": "rsi_14",
                        "right": 55,
                    },
                },
                "condition_operators": [
                    "<",
                    ">",
                    "<=",
                    ">=",
                    "==",
                    "!=",
                    "crosses_above",
                    "crosses_below",
                    "between",
                    "not_between",
                    "is_true",
                    "is_false",
                    "exists",
                    "missing",
                ],
                "group_kinds": ["all", "any", "not"],
            },
            "parameters_format": {
                "keys": {
                    "type": "int | float | bool | string",
                    "default": "required",
                    "minimum": "optional lower bound (not 'min')",
                    "maximum": "optional upper bound (not 'max')",
                    "description": "optional human-readable string",
                }
            },
            "multi_timeframe": {
                "supported": True,
                "max_informative_timeframes": 3,
                "primary_alias": "primary",
                "column_naming": "{indicator}_{informative_interval}",
                "example_column": "sma_50_1d",
                "workflow": [
                    "fetch primary bars",
                    "fetch informative bars",
                    "apply primary indicators to primary bars",
                    "apply informative indicators to informative bars",
                    "call backtest_strategy_definition with informative_bars_json",
                ],
            },
            "risk": {
                "stop_loss_types": ["none", "atr", "fixed_pct"],
                "take_profit_types": ["none", "atr", "fixed_pct", "risk_reward"],
            },
            "operators": _OPERATORS,
            "indicators": self._catalog.as_dict(),
        }
