"""Pure parser for the optional strategy ``execution`` block.

Reads leverage and margin_mode from raw YAML/JSON text. Returns None when the
strategy has no execution block. Domain-pure: no file I/O, no framework deps
beyond PyYAML (a domain-appropriate library for config parsing).
"""

from __future__ import annotations

import yaml

from finbot.core.domain.entities.strategy_execution_config import (
    StrategyExecutionConfig,
)


def parse_strategy_execution(content: str) -> StrategyExecutionConfig | None:
    """Parse the execution block from strategy YAML/JSON text.

    Returns None when the strategy has no ``execution`` key, or when leverage
    is absent/invalid. ``margin_mode`` defaults to "isolated" when omitted.
    """
    try:
        data = yaml.safe_load(content)
    except yaml.YAMLError:
        return None

    if not isinstance(data, dict):
        return None

    block = data.get("execution")
    if not isinstance(block, dict):
        return None

    leverage = block.get("leverage")
    if leverage is None:
        return None

    try:
        lev_int = int(leverage)
    except (TypeError, ValueError):
        return None

    margin_mode = str(block.get("margin_mode", "isolated")).lower()
    if margin_mode not in ("isolated", "cross"):
        margin_mode = "isolated"

    return StrategyExecutionConfig(leverage=lev_int, margin_mode=margin_mode)
