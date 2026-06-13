"""Live trading runtime use case — orchestrates the trading pipeline.

Iterates over closed-candle events, enriches indicators, validates
enriched bar quality, evaluates YAML-defined strategies, plans orders,
runs risk gates, and persists decisions.

Constructor-inject every dependency. The use case owns orchestration
but delegates to domain services and infrastructure adapters.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from finbot.core.application.dto.candle_processing_result import (
    CandleProcessingResult,
)
from finbot.core.domain.entities.audit_log_entry import AuditLogEntry
from finbot.core.domain.entities.bot_run import BotRun
from finbot.core.domain.entities.enrichment_validation_result import (
    EnrichmentValidationResult,
)
from finbot.core.domain.entities.risk_event_record import RiskEventRecord
from finbot.core.domain.entities.trading_mode import TradingMode
from finbot.core.domain.interfaces.bar_frame_converter import (
    BarFrameConverter,
)
from finbot.core.domain.interfaces.bot_state_repository import (
    BotStateRepository,
)
from finbot.core.domain.interfaces.enrichment_validator import (
    EnrichmentValidator,
)
from finbot.core.domain.interfaces.exchange_gateway import ExchangeGateway
from finbot.core.domain.interfaces.indicator_calculator import (
    IndicatorCalculator,
)
from finbot.core.domain.interfaces.market_data_stream import MarketDataStream
from finbot.core.domain.interfaces.strategy_evaluator import (
    StrategyEvaluator,
)
from finbot.core.domain.services.warmup_window import WarmupWindow

logger = logging.getLogger(__name__)


class LiveTradingRuntimeUseCase:
    """Orchestrates the live trading pipeline.

    Dependencies are constructor-injected. The same use case instance
    handles the full pipeline: warmup → enrichment → validation →
    evaluation → risk → planning → persistence.  Branching between
    dry-run, testnet, and live happens at the submission boundary.
    """

    def __init__(
        self,
        exchange_gateway: ExchangeGateway,
        market_data_stream: MarketDataStream,
        strategy_evaluator: StrategyEvaluator,
        state_repository: BotStateRepository,
        indicator_calculator: IndicatorCalculator,
        enrichment_validator: EnrichmentValidator,
        bar_frame_converter: BarFrameConverter,
        mode: TradingMode,
        warmup_bars: list[dict[str, Any]] | None = None,
        required_columns: set[str] | None = None,
    ) -> None:
        self._exchange = exchange_gateway
        self._stream = market_data_stream
        self._evaluator = strategy_evaluator
        self._repo = state_repository
        self._indicator_calc = indicator_calculator
        self._enrichment_validator = enrichment_validator
        self._bar_converter = bar_frame_converter
        self._mode = mode
        self._required_columns: set[str] = required_columns or set()
        self._bot_run_id: str = ""
        self._strategy_name: str = ""
        self._strategy_hash: str = ""
        self._symbol: str = ""
        self._interval: str = ""
        self._started: bool = False

        # Warmup
        self._warmup = WarmupWindow()
        if warmup_bars:
            for bar in warmup_bars:
                self._warmup.append(bar)

    # -- public API ----------------------------------------------------------

    def start(
        self,
        strategy_path: str,
        symbol: str,
        interval: str,
        strategy_hash: str = "",
    ) -> str:
        """Start the runtime session. Returns the bot run id."""
        self._start_session(
            strategy_name=strategy_path,
            strategy_hash=strategy_hash,
            symbol=symbol,
            interval=interval,
        )
        return self._bot_run_id

    def stop(self) -> None:
        """Stop the runtime session and persist the end marker."""
        if self._started:
            self._repo.end_bot_run(self._bot_run_id)
            self._started = False

    def process_closed_candle(self, candle: dict[str, Any]) -> CandleProcessingResult:
        """Process a single closed candle through the full pipeline."""
        ts = _normalize_ts(candle)

        # 1. Warmup
        self._warmup.append(candle)
        if not self._warmup.is_ready():
            return CandleProcessingResult(
                candle_timestamp=ts,
                enrichment_valid=False,
                enrichment_errors=["warmup not ready"],
                message="warmup not ready — candle skipped",
            )

        # 2. Enrich
        enriched = self._enrich_bars()
        if enriched.empty:
            return CandleProcessingResult(
                candle_timestamp=ts,
                enrichment_valid=False,
                enrichment_errors=["indicator engine returned empty result"],
                message="enrichment failed — empty result",
            )
        latest = enriched.iloc[-1].to_dict()

        # 3. Validate enrichment
        validation = self._enrichment_validator.validate(
            enriched_bar=latest,
            required_columns=self._required_columns,
            warmup_ready=self._warmup.is_ready(),
            has_gap=self._warmup.has_gap,
        )
        if not validation.valid:
            return self._handle_enrichment_rejection(ts, validation)

        # 4. Evaluate strategy
        position = self._exchange.get_position(self._symbol or "DEFAULT")
        signal = self._evaluator.evaluate(latest, position)

        return CandleProcessingResult(
            candle_timestamp=ts,
            enrichment_valid=True,
            signal_action=signal.action.value,
            message="processed",
        )

    def process_account_event(self, event: dict[str, Any]) -> dict[str, Any]:
        """Process an account websocket event (order update, fill, etc.).

        Placeholder — full account event processing in later slices.
        """
        return {"status": "acknowledged", "event": str(event)[:80]}

    # -- internal pipeline steps ---------------------------------------------

    def _start_session(
        self,
        strategy_name: str,
        strategy_hash: str,
        symbol: str,
        interval: str,
    ) -> None:
        self._strategy_name = strategy_name
        self._strategy_hash = strategy_hash
        self._symbol = symbol
        self._interval = interval

        bot_run = BotRun(
            strategy_name=strategy_name,
            strategy_hash=strategy_hash,
            symbol=symbol,
            interval=interval,
            mode=self._mode.value,
        )
        self._repo.create_bot_run(bot_run)
        self._bot_run_id = bot_run.run_id
        self._started = True

    def _enrich_bars(self) -> Any:
        """Convert warmup bars to a DataFrame and compute indicators."""
        bars = self._warmup.bars
        df = self._bar_converter.bars_to_frame(bars)
        return self._indicator_calc.calculate(df, list(self._required_columns))

    def _handle_enrichment_rejection(
        self,
        candle_ts: int,
        validation: EnrichmentValidationResult,
    ) -> CandleProcessingResult:
        """Persist rejection and return a failed processing result."""
        self._repo.record_risk_event(
            RiskEventRecord(
                bot_run_id=self._bot_run_id,
                event_type="enrichment_validation",
                signal_key="",
                decision="rejected",
                reason=validation.reason,
            )
        )
        self._repo.append_audit_log(
            AuditLogEntry(
                bot_run_id=self._bot_run_id,
                event_type="enrichment_validation_failed",
                event_data_json=json.dumps(
                    {
                        "candle_timestamp": candle_ts,
                        "reason": validation.reason,
                        "missing_columns": validation.missing_columns,
                        "non_finite_columns": validation.non_finite_columns,
                    },
                    default=str,
                ),
            )
        )
        return CandleProcessingResult(
            candle_timestamp=candle_ts,
            enrichment_valid=False,
            enrichment_errors=(
                validation.missing_columns
                + validation.non_finite_columns
                + validation.invalid_type_columns
            ),
            message=validation.reason,
        )


# -- module-level helpers -----------------------------------------------------


def _normalize_ts(candle: dict[str, Any]) -> int:
    ts = candle.get("timestamp", 0)
    if isinstance(ts, float):
        return int(ts)
    return int(ts)
