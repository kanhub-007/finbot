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
from decimal import Decimal
from typing import Any

from finbot.core.application.dto.candle_processing_result import (
    CandleProcessingResult,
)
from finbot.core.domain.entities.audit_log_entry import AuditLogEntry
from finbot.core.domain.entities.bot_run import BotRun
from finbot.core.domain.entities.enrichment_validation_result import (
    EnrichmentValidationResult,
)
from finbot.core.domain.entities.order_intent import OrderIntent
from finbot.core.domain.entities.order_response_record import (
    OrderResponseRecord,
)
from finbot.core.domain.entities.position_snapshot import PositionSnapshot
from finbot.core.domain.entities.processed_signal import ProcessedSignal
from finbot.core.domain.entities.reconciliation_record import (
    ReconciliationRecord,
)
from finbot.core.domain.entities.risk_event_record import RiskEventRecord
from finbot.core.domain.entities.signal_action import SignalAction
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
from finbot.core.domain.interfaces.market_metadata_provider import (
    MarketMetadataProvider,
)
from finbot.core.domain.interfaces.market_data_stream import MarketDataStream
from finbot.core.domain.interfaces.strategy_evaluator import (
    StrategyEvaluator,
)
from finbot.core.domain.interfaces.cloid_generator import CloidGenerator
from finbot.core.domain.interfaces.order_normalizer import OrderNormalizer
from finbot.core.domain.interfaces.order_planner import OrderPlanner
from finbot.core.domain.services.order_normalizer import (
    OrderNormalizationError,
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
        order_planner: OrderPlanner | None = None,
        market_metadata_provider: MarketMetadataProvider | None = None,
        order_normalizer: OrderNormalizer | None = None,
        cloid_generator: CloidGenerator | None = None,
    ) -> None:
        self._exchange = exchange_gateway
        self._stream = market_data_stream
        self._evaluator = strategy_evaluator
        self._repo = state_repository
        self._indicator_calc = indicator_calculator
        self._enrichment_validator = enrichment_validator
        self._bar_converter = bar_frame_converter
        self._mode = mode
        self._order_planner = order_planner
        self._metadata_provider = market_metadata_provider
        self._order_normalizer = order_normalizer
        self._cloid_gen = cloid_generator
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
        if self._bar_converter.is_empty(enriched):
            return CandleProcessingResult(
                candle_timestamp=ts,
                enrichment_valid=False,
                enrichment_errors=["indicator engine returned empty result"],
                message="enrichment failed — empty result",
            )
        latest = self._bar_converter.latest_bar(enriched)

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

        # 5. If HOLD, no further processing
        if signal.action == SignalAction.HOLD:
            return CandleProcessingResult(
                candle_timestamp=ts,
                enrichment_valid=True,
                signal_action=signal.action.value,
                message="processed — HOLD",
            )

        # 6. Risk gates + order planning (delegated to OrderPlanner)
        return self._plan_and_persist(signal, latest, position, ts)

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

    def _plan_and_persist(
        self,
        signal: SignalDecision,
        bar: dict[str, Any],
        position: PositionSnapshot,
        candle_ts: int,
    ) -> CandleProcessingResult:
        """Run risk gates, persist signal/intent, submit if mode allows."""
        # If no order planner is wired, skip ordering (backward compat).
        if self._order_planner is None:
            return CandleProcessingResult(
                candle_timestamp=candle_ts,
                enrichment_valid=True,
                signal_action=signal.action.value,
                message="processed — no order planner wired",
            )

        ctx = {
            "bar": bar,
            "symbol": self._symbol,
            "bot_run_id": self._bot_run_id,
            "mode": self._mode.value,
            "position_size": position.size,
        }

        plan = self._order_planner.plan(signal, ctx)

        # Persist risk decision
        if plan.accepted:
            self._repo.record_risk_event(
                RiskEventRecord(
                    bot_run_id=self._bot_run_id,
                    event_type=plan.gate_name or "risk",
                    signal_key=plan.signal_key,
                    decision="accepted",
                )
            )
        else:
            self._repo.record_risk_event(
                RiskEventRecord(
                    bot_run_id=self._bot_run_id,
                    event_type=plan.gate_name or "risk",
                    signal_key=plan.signal_key,
                    decision="rejected",
                    reason=plan.reason,
                )
            )
            return CandleProcessingResult(
                candle_timestamp=candle_ts,
                enrichment_valid=True,
                signal_action=signal.action.value,
                risk_decision="rejected",
                message=plan.reason,
            )

        # Mark signal processed
        self._repo.mark_signal_processed(
            ProcessedSignal(
                signal_key=plan.signal_key,
                bot_run_id=self._bot_run_id,
                signal_action=signal.action.value,
                bar_timestamp=str(candle_ts),
            )
        )

        # Persist order intent
        intent = plan.intent
        intent_id = ""
        submitted = False
        if intent is not None:
            # Generate cloid and stamp onto intent
            if self._cloid_gen is not None:
                cloid = self._cloid_gen.generate(plan.signal_key)
                intent = intent.with_cloid(cloid)

            intent_id = self._repo.record_order_intent(intent)

            # Branch on mode for submission
            if self._mode == TradingMode.DRY_RUN:
                self._exchange.submit_order(intent)

            elif self._mode in (TradingMode.TESTNET, TradingMode.LIVE):
                submitted = self._submit_to_exchange(intent, intent_id, candle_ts)

        return CandleProcessingResult(
            candle_timestamp=candle_ts,
            enrichment_valid=True,
            signal_action=signal.action.value,
            risk_decision="accepted",
            intent_id=intent_id,
            submitted=submitted,
            message="processed — order planned",
        )

    # -- submission helpers ---------------------------------------------------

    def _submit_to_exchange(
        self,
        intent: OrderIntent,
        intent_id: str,
        candle_ts: int,
    ) -> bool:
        """Normalize intent, submit to exchange, persist response and reconcile."""
        if self._order_normalizer is None:
            return False
        if not intent.cloid:
            return False

        # Normalize to exchange precision
        bar = self._warmup.bars[-1] if self._warmup.bars else {}
        ref_price = Decimal(str(bar.get("close", 0)))
        try:
            normalized = self._order_normalizer.normalize(intent, ref_price)
        except OrderNormalizationError as e:
            logger.warning(
                "Order normalization failed for intent %s: %s", intent_id, e
            )
            return False

        # Submit
        response = self._exchange.submit_order(normalized)

        # Persist response
        status = str(response.get("status", "unknown"))
        self._repo.record_order_response(
            OrderResponseRecord(
                intent_id=intent_id,
                bot_run_id=self._bot_run_id,
                response_json=json.dumps(response, default=str),
                status=status,
            )
        )

        # Reconcile — placeholder until actual exchange state comparison
        self._repo.record_reconciliation(
            ReconciliationRecord(
                bot_run_id=self._bot_run_id,
                position_matches=False,
                open_orders_match=False,
                details=f"post-submit for {intent_id} (not yet reconciled)",
            )
        )

        return True


# -- module-level helpers -----------------------------------------------------


def _normalize_ts(candle: dict[str, Any]) -> int:
    ts = candle.get("timestamp", 0)
    if isinstance(ts, float):
        return int(ts)
    return int(ts)
