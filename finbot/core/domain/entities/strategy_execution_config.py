"""StrategyExecutionConfig — leverage/margin declared in a strategy YAML.

Optional ``execution`` block parsed from the strategy file. When present,
starting the bot syncs these values to the exchange via set_leverage.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class StrategyExecutionConfig:
    """Leverage and margin mode declared by a strategy's execution block.

    Attributes:
        leverage: Integer leverage (e.g. 3). Required when the block is present.
        margin_mode: "isolated" (default) or "cross".
    """

    leverage: int
    margin_mode: str = "isolated"
