"""Strategy evaluation interface."""

from abc import ABC, abstractmethod
from typing import Any

from finbot.core.domain.entities.position_snapshot import PositionSnapshot
from finbot.core.domain.entities.signal_decision import SignalDecision


class StrategyEvaluator(ABC):
    """Abstracts Finbar-backed strategy evaluation."""

    @abstractmethod
    def evaluate(
        self,
        enriched_bar: dict[str, Any],
        position: PositionSnapshot,
    ) -> SignalDecision:
        """Evaluate a strategy against one enriched closed bar."""
