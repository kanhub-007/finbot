"""Pure function to extract :class:`StrategyTimeframes` from a parsed strategy.

Domain service — no I/O, no framework dependencies.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from finbot.core.domain.entities.strategy_timeframes import StrategyTimeframes

if TYPE_CHECKING:
    from finbar_strategy_runtime.domain.entities.strategy_definition import (
        StrategyDefinition,
    )


def parse_timeframes(
    definition: StrategyDefinition | None,
) -> StrategyTimeframes | None:
    """Extract the ``timeframes`` block from a parsed strategy definition.

    Returns ``None`` when *definition* has no ``timeframes`` block (single-TF
    strategy) or when *definition* is ``None``.

    Paramters
    ---------
    definition:
        Parsed strategy definition from ``YamlStrategyDefinitionLoader``.

    Returns
    -------
    StrategyTimeframes | None
        Parsed timeframes value object, or ``None`` for single-TF strategies.
    """
    if definition is None:
        return None
    if definition.timeframes is None:
        return None

    tf = definition.timeframes
    aliases: dict[str, str] = {}
    symbols: dict[str, str | None] = {}
    intervals: list[str] = []
    for item in tf.informative:
        intervals.append(item.interval)
        aliases[item.alias] = item.interval
        # Cross-asset: read optional symbol per informative.
        item_symbol: str | None = getattr(item, "symbol", None) or None
        symbols[item.alias] = item_symbol

    return StrategyTimeframes(
        primary=tf.primary or None,
        informative_intervals=tuple(intervals),
        informative_aliases=aliases,
        informative_symbols=symbols,
    )
