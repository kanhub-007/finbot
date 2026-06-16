"""Infrastructure helper: read supported capabilities from the package.

Keeps the ``finbar_strategy_runtime.parser`` import (infrastructure-tier)
out of the application/domain layers. The composition root calls this to
inject data-driven capability sets into use cases, so there is no
hand-maintained list to drift.
"""

from __future__ import annotations

from finbar_strategy_runtime.parser.strategy_capability_service import (
    StrategyCapabilityService,
)


def supported_indicator_types() -> frozenset[str]:
    """Return the indicator type names the installed package supports.

    Combines the fixed indicator types and the parameterized indicator
    families (sma/ema/rsi/...). When the package adds an indicator, it
    appears here automatically.
    """
    indicators = StrategyCapabilityService().get_capabilities()["indicators"]
    return frozenset(indicators["fixed_indicators"]) | frozenset(
        indicators["period_ranges"]
    )


def supported_stop_loss_types() -> frozenset[str]:
    """Return the stop-loss type names the installed package supports.

    Reads from the package's risk capabilities so Finbot never needs a
    hand-maintained list.  Excludes ``"none"`` (which means no stop
    configured) so the compatibility check can distinguish "missing"
    from "unsupported".
    """
    risk = StrategyCapabilityService().get_capabilities()["risk"]
    return frozenset(t for t in risk["stop_loss_types"] if t != "none")
