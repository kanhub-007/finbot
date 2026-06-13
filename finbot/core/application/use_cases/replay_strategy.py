"""Use case for replaying a strategy over historical bar data."""

from __future__ import annotations

import hashlib
from decimal import Decimal

from finbot.core.application.dto.replay_strategy_result import ReplayStrategyResult
from finbot.core.application.dto.signal_event import SignalEvent
from finbot.core.domain.dto.replay_strategy_request import ReplayStrategyRequest
from finbot.core.domain.entities.position_direction import PositionDirection
from finbot.core.domain.entities.position_snapshot import PositionSnapshot
from finbot.core.domain.entities.signal_action import SignalAction
from finbot.core.domain.interfaces.bar_loader import BarLoader
from finbot.core.domain.interfaces.strategy_definition_loader import (
    StrategyDefinitionLoader,
)
from finbot.core.domain.interfaces.strategy_evaluator_factory import (
    StrategyEvaluatorFactory,
)
from finbot.core.domain.services.warmup_window import WarmupWindow


class ReplayStrategyUseCase:
    """Replay a strategy against historical bar data without network access.

    Bars are loaded from a ``BarLoader`` and optionally pre-warmed
    through a ``WarmupWindow``.  When warmup is configured the evaluator
    skips bars until the minimum bar count is reached.
    """

    DEFAULT_MIN_WARMUP = 20

    def __init__(
        self,
        loader: StrategyDefinitionLoader,
        bar_loader: BarLoader,
        evaluator_factory: StrategyEvaluatorFactory,
        warmup: WarmupWindow | None = None,
    ):
        self._loader = loader
        self._bar_loader = bar_loader
        self._evaluator_factory = evaluator_factory
        self._warmup = warmup

    # -- public API --------------------------------------------------------

    def execute(self, request: ReplayStrategyRequest) -> ReplayStrategyResult:
        errors: list[str] = []
        definition = self._load_definition(request, errors)
        if definition is None:
            return ReplayStrategyResult(status="error", errors=errors)

        bars = self._load_bars(request, errors)
        if not bars:
            return ReplayStrategyResult(status="error", errors=errors)

        evaluator = self._evaluator_factory.create(
            definition,
            symbol=request.symbol,
            interval=request.interval,
            strategy_hash=_hash_content(request.strategy_content),
        )

        warmup = self._warmup
        signals: list[SignalEvent] = []
        position = PositionSnapshot(
            symbol=request.symbol,
            direction=PositionDirection.FLAT,
            size=Decimal("0"),
        )

        for i, bar in enumerate(bars):
            # Feed every bar into warmup so indicators have full history.
            if warmup is not None:
                warmup.append(bar)
                if not warmup.is_ready():
                    continue

            signal = evaluator.evaluate(bar, position)
            if signal.action == SignalAction.HOLD:
                continue

            signals.append(
                SignalEvent(
                    action=signal.action,
                    symbol=request.symbol,
                    bar_index=i,
                    warmup_ready=(warmup.is_ready() if warmup else True),
                    close=_float_bar(bar, "close"),
                    stop_price=(
                        float(signal.stop_price)
                        if signal.stop_price is not None
                        else None
                    ),
                    target_price=(
                        float(signal.target_price)
                        if signal.target_price is not None
                        else None
                    ),
                    confidence=signal.confidence,
                )
            )
            position = self._update_position(position, signal.action, bar)

        return ReplayStrategyResult(
            status="complete", signal_count=len(signals), signals=signals
        )

    # -- internal -----------------------------------------------------------

    def _load_definition(self, request, errors):
        try:
            return self._loader.load_from_text(request.strategy_content)
        except Exception as exc:
            errors.append(str(exc))
            return None

    def _load_bars(self, request, errors):
        csv = request.bars_csv
        if csv:
            bars = self._bar_loader.load_bars(csv)
            if bars:
                return bars
            return [{"timestamp": 0}]  # headers-only → no signals
        errors.append("No bar data provided (bars_csv required)")
        return []

    @staticmethod
    def _update_position(
        position: PositionSnapshot,
        action: SignalAction,
        bar: dict,
    ) -> PositionSnapshot:
        if action in (SignalAction.LONG_ENTRY, SignalAction.SHORT_ENTRY):
            return PositionSnapshot(
                symbol=position.symbol,
                direction=(
                    PositionDirection.LONG
                    if action == SignalAction.LONG_ENTRY
                    else PositionDirection.SHORT
                ),
                size=Decimal("1"),
                entry_price=Decimal(str(_float_bar(bar, "close"))),
            )
        if action in (SignalAction.LONG_EXIT, SignalAction.SHORT_EXIT):
            return PositionSnapshot(
                symbol=position.symbol,
                direction=PositionDirection.FLAT,
                size=Decimal("0"),
            )
        return position


# -- helpers --------------------------------------------------------------


def _float_bar(bar: dict, key: str) -> float:
    val = bar.get(key, 0)
    if val is None:
        return 0.0
    try:
        return float(val)
    except (TypeError, ValueError):
        return 0.0


def _hash_content(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()[:12]
