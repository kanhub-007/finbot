"""Use case for replaying a strategy over historical bar data."""

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


class ReplayStrategyUseCase:
    """Replay a strategy against historical bar data without network access."""

    def __init__(
        self,
        loader: StrategyDefinitionLoader,
        bar_loader: BarLoader,
        evaluator_factory: StrategyEvaluatorFactory,
    ):
        self._loader = loader
        self._bar_loader = bar_loader
        self._evaluator_factory = evaluator_factory

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

        signals: list[SignalEvent] = []
        position = PositionSnapshot(
            symbol=request.symbol,
            direction=PositionDirection.FLAT,
            size=Decimal("0"),
        )

        for i, bar in enumerate(bars):
            signal = evaluator.evaluate(bar, position)
            if signal.action == SignalAction.HOLD:
                continue

            signals.append(
                SignalEvent(
                    action=signal.action,
                    symbol=request.symbol,
                    bar_index=i,
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

    def _load_definition(self, request, errors):
        try:
            return self._loader.load_from_text(request.strategy_content)
        except Exception as exc:
            errors.append(str(exc))
            return None

    @staticmethod
    def _load_bars(request, errors):
        if request.bars_csv:
            bars = _parse_csv_bars(request.bars_csv)
            if bars:
                return bars
            # Headers-only CSV is allowed — just no signals produced.
            return [{"timestamp": "0"}]
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


def _float_bar(bar: dict, key: str) -> float:
    val = bar.get(key, 0)
    if val is None:
        return 0.0
    try:
        return float(val)
    except (TypeError, ValueError):
        return 0.0


def _parse_csv_bars(csv_text: str) -> list[dict]:
    import csv
    import io

    reader = csv.DictReader(io.StringIO(csv_text))
    bars = []
    for row in reader:
        bar: dict = {}
        for key, val in row.items():
            bar[key] = _coerce_csv_value(val)
        bars.append(bar)
    bars.sort(key=lambda b: str(b.get("timestamp", "")))
    return bars


def _coerce_csv_value(val: str):
    stripped = val.strip()
    if stripped.lower() in ("true", "false"):
        return stripped.lower() == "true"
    try:
        return int(stripped)
    except ValueError:
        pass
    try:
        return float(stripped)
    except ValueError:
        pass
    return stripped


def _hash_content(content: str) -> str:
    import hashlib

    return hashlib.sha256(content.encode("utf-8")).hexdigest()[:12]
