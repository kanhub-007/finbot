"""Live trading runtime use case — orchestrates the trading pipeline.

Iterates over closed-candle events, enriches indicators, validates
enriched bar quality, evaluates YAML-defined strategies, plans orders,
runs risk gates, and persists decisions.

Constructor-inject every dependency. The use case owns orchestration
but delegates to domain services and infrastructure adapters.  Account
websocket events (fills / order updates) are delegated to a dedicated
:class:`AccountEventHandler`.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime as _dt
from decimal import Decimal
from pathlib import Path
from typing import Any

from finbot.core.application.dto.candle_processing_result import (
    CandleProcessingResult,
)
from finbot.core.application.dto.run_bot_result import RunBotResult
from finbot.core.application.use_cases.account_event_handler import (
    AccountEventHandler,
)
from finbot.core.application.use_cases.order_submitter import OrderSubmitter
from finbot.core.domain.dto.validate_strategy_request import (
    ValidateStrategyRequest,
)
from finbot.core.domain.entities.audit_log_entry import AuditLogEntry
from finbot.core.domain.entities.bot_config import BotConfig
from finbot.core.domain.entities.bot_run import BotRun
from finbot.core.domain.entities.enrichment_validation_result import (
    EnrichmentValidationResult,
)
from finbot.core.domain.entities.fill_record import FillRecord
from finbot.core.domain.entities.position_direction import PositionDirection
from finbot.core.domain.entities.position_snapshot import PositionSnapshot
from finbot.core.domain.entities.processed_signal import ProcessedSignal
from finbot.core.domain.entities.reconciliation_record import (
    ReconciliationRecord,
)
from finbot.core.domain.entities.risk_event_record import RiskEventRecord
from finbot.core.domain.entities.signal_action import SignalAction
from finbot.core.domain.entities.signal_decision import SignalDecision
from finbot.core.domain.entities.trading_mode import TradingMode
from finbot.core.domain.interfaces.bar_frame_converter import (
    BarFrameConverter,
)
from finbot.core.domain.interfaces.bot_loop import BotLoop
from finbot.core.domain.interfaces.bot_state_repository import (
    BotStateRepository,
)
from finbot.core.domain.interfaces.cloid_generator import CloidGenerator
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
from finbot.core.domain.interfaces.order_normalizer import OrderNormalizer
from finbot.core.domain.interfaces.order_planner import OrderPlanner
from finbot.core.domain.interfaces.strategy_evaluator import (
    StrategyEvaluator,
)
from finbot.core.domain.interfaces.strategy_validator import (
    StrategyValidator,
)
from finbot.core.domain.services.live_mode_guard import check_live_mode
from finbot.core.domain.services.trade_ledger import TradeLedger
from finbot.core.domain.services.warmup_window import WarmupWindow

logger = logging.getLogger(__name__)


class LiveTradingRuntimeUseCase:
    """Orchestrates the live trading pipeline.

    Dependencies are constructor-injected. The same use case instance
    handles the full pipeline: warmup → enrichment → validation →
    evaluation → risk → planning → persistence.  Branching between
    dry-run, testnet, and live happens at the submission boundary.

    The market data stream is intentionally NOT a dependency of this use
    case: it is owned by the injected :class:`BotLoop`, which feeds
    closed candles via ``process_closed_candle``.
    """

    def __init__(
        self,
        exchange_gateway: ExchangeGateway,
        strategy_evaluator: StrategyEvaluator,
        state_repository: BotStateRepository,
        indicator_calculator: IndicatorCalculator,
        enrichment_validator: EnrichmentValidator,
        bar_frame_converter: BarFrameConverter,
        mode: TradingMode,
        warmup_bars: list[dict[str, Any]] | None = None,
        required_columns: set[str] | None = None,
        required_indicators: list[str] | None = None,
        order_planner: OrderPlanner | None = None,
        market_metadata_provider: MarketMetadataProvider | None = None,
        order_normalizer: OrderNormalizer | None = None,
        cloid_generator: CloidGenerator | None = None,
        bot_loop: BotLoop | None = None,
        strategy_validator: StrategyValidator | None = None,
        account_event_handler: AccountEventHandler | None = None,
        trade_ledger: TradeLedger | None = None,
        notification_sender: object | None = None,
        live_state: Any | None = None,
    ) -> None:
        self._exchange = exchange_gateway
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
        self._bot_loop = bot_loop
        self._strategy_validator = strategy_validator
        self._account_handler = account_event_handler
        self._trade_ledger = trade_ledger or TradeLedger(self._repo)
        self._notification_sender = notification_sender
        self._live_state = live_state
        self._submitter = OrderSubmitter(
            exchange_gateway, order_normalizer, state_repository
        )
        self._required_columns: set[str] = required_columns or set()
        # Ordered: the package calculator computes indicators in the given
        # order, so composites (above_value) must follow their intermediates
        # (vp_vah/vp_val). A set would scramble order and yield NaN composites.
        self._required_indicators: list[str] = (
            list(required_indicators) if required_indicators else []
        )
        self._bot_run_id: str = ""
        self._strategy_name: str = ""
        self._strategy_hash: str = ""
        self._symbol: str = ""
        self._interval: str = ""
        self._started: bool = False

        # Warmup
        self._warmup = WarmupWindow()
        self._warmup_needed = True
        if warmup_bars:
            for bar in warmup_bars:
                self._warmup.append(bar)
        # Cached enriched frame so each candle appends one row instead of
        # rebuilding the whole frame from the warmup window.
        self._enriched_frame: Any = None

    # -- public API ----------------------------------------------------------

    def set_live_state(self, state: object) -> None:
        """Attach a BotLiveState for MCP status updates.

        Called by :class:`BotManager` after construction so the runtime
        thread can update live state fields on each candle/signal/order.
        """
        self._live_state = state

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

    def start_live(
        self,
        strategy_path: str,
        symbol: str,
        interval: str,
        config: BotConfig,
    ) -> RunBotResult:
        """Start with live-mode safety gates plus strategy compatibility."""
        check = check_live_mode(
            mode=config.mode.value,
            live_trading_ack=config.live_trading_ack,
            private_key=config.private_key,
            max_position_usd=float(config.max_position_usd),
            database_path=config.db_path,
        )

        if not check.allowed:
            return RunBotResult(
                status="rejected",
                message="; ".join(check.reasons),
            )

        # Strategy compatibility gate — reject unsupported features.
        # Fail closed: any error while checking rejects the run rather than
        # silently allowing an unverified strategy into live/testnet mode.
        compat = self._check_strategy_compat(strategy_path, config.mode.value)
        if compat is not None:
            return compat

        self._start_session(
            strategy_name=strategy_path,
            strategy_hash="",
            symbol=symbol,
            interval=interval,
        )
        return RunBotResult(status="running", message=self._bot_run_id)

    def _check_strategy_compat(
        self, strategy_path: str, mode: str
    ) -> RunBotResult | None:
        """Return a rejection result if the strategy has unsupported features.

        Returns ``None`` when the strategy is acceptable.  In live/testnet
        mode a check failure (parse error, missing file, etc.) is treated
        as a rejection rather than silently permitted.
        """
        if self._strategy_validator is None:
            return None
        try:
            content = Path(strategy_path).read_text(encoding="utf-8")
            result = self._strategy_validator.compatibility(
                ValidateStrategyRequest(
                    strategy_path=strategy_path, strategy_content=content
                )
            )
        except OSError as e:
            return RunBotResult(
                status="rejected",
                message=f"strategy compatibility: cannot read strategy file ({e})",
            )
        except Exception as e:  # noqa: BLE001 - fail closed on any check error
            logger.warning("Strategy compatibility check failed: %s", e)
            if mode in ("testnet", "live"):
                return RunBotResult(
                    status="rejected",
                    message=f"strategy compatibility: check failed ({e})",
                )
            return None

        mode_info = result.modes.get(mode, {})
        blockers: list[str] = []
        for feature, status in mode_info.items():
            if status not in ("supported", "parse"):
                blockers.append(f"{feature}: {status}")
        if "parse" in mode_info and mode_info["parse"] == "error":
            blockers.insert(0, "strategy parsing failed")
        if blockers:
            return RunBotResult(
                status="rejected",
                message="strategy compatibility: " + "; ".join(blockers),
            )
        return None

    def stop(self) -> None:
        """Stop the runtime session and persist the end marker."""
        if self._started:
            if self._bot_loop:
                self._bot_loop.stop()
            self._repo.end_bot_run(self._bot_run_id)
            self._started = False

    def reconcile_on_startup(self) -> ReconciliationRecord:
        """Fetch the exchange position; reconstruct an open Trade if needed.

        Called once at the start of ``run_forever()``.  If the exchange
        reports an open position but the DB has no Trade for it (e.g. crash
        mid-session), an open Trade is reconstructed with unknown entry
        price and a :class:`ReconciliationRecord` is persisted.
        """
        position = self._exchange.get_position(self._symbol)
        existing = self._repo.get_open_trade(self._symbol)
        if position.direction != PositionDirection.FLAT and existing is None:
            trade = self._trade_ledger.reconstruct_open(
                position,
                bot_run_id=self._bot_run_id,
                strategy_hash=self._strategy_hash,
            )
            self._repo.open_trade(trade)
        record = ReconciliationRecord(
            bot_run_id=self._bot_run_id,
            position_matches=(
                existing is not None
                or position.direction == PositionDirection.FLAT
            ),
            open_orders_match=True,  # placeholder; full order reconcile later
            details=f"startup: exchange={position.direction.value} "
            f"db_open={'yes' if existing else 'no'}",
        )
        self._repo.record_reconciliation(record)
        return record

    def run_forever(self) -> None:
        """Start the event loop and block until stopped.

        Requires a ``BotLoop`` to be injected.  The loop subscribes to
        market data and calls ``process_closed_candle`` for each candle.
        """
        if self._bot_loop is None:
            raise RuntimeError("No BotLoop injected — cannot run forever")
        if not self._started:
            raise RuntimeError(
                "Session not started — call start() or start_live() first"
            )
        self.reconcile_on_startup()
        self._bot_loop.start(
            symbol=self._symbol,
            interval=self._interval,
            on_candle=self.process_closed_candle,
            on_account_event=self.process_account_event,
        )

    def process_closed_candle(self, candle: dict[str, Any]) -> CandleProcessingResult:
        """Process a single closed candle through the full pipeline."""
        ts = _normalize_ts(candle)

        # 1. Warmup
        self._warmup.append(candle)
        if not self._warmup.is_ready():
            if self._warmup_needed:
                logger.info(
                    "Warmup %d/%d — waiting for more candles",
                    self._warmup.count,
                    self._warmup.min_bars,
                )
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
        logger.info(
            "Candle %s: action=%s symbol=%s",
            ts,
            signal.action.value,
            signal.symbol,
        )

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

        Delegates to :class:`AccountEventHandler`, lazily constructed from
        the state repository so callers that never receive account events
        pay no setup cost.
        """
        if self._account_handler is None:
            self._account_handler = AccountEventHandler(
                self._repo, self._trade_ledger,
                notification_sender=self._notification_sender,
            )
        return self._account_handler.handle(
            event,
            bot_run_id=self._bot_run_id,
            symbol=self._symbol,
        )

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
        """Append the latest bar to the cached frame and recompute indicators.

        On the first ready candle the frame is built once from the warmup
        window; subsequent candles append a single row and recompute.  This
        keeps frame construction O(1) amortised instead of rebuilding an
        n-bar DataFrame every candle.  The frame is capped to the warmup
        window length so it does not grow unbounded over a long session.
        """
        if self._enriched_frame is None or self._bar_converter.is_empty(
            self._enriched_frame
        ):
            df = self._bar_converter.bars_to_frame(self._warmup.bars)
        else:
            df = self._bar_converter.append_bar(
                self._enriched_frame, self._warmup.latest_bar
            )
            df = self._trim_frame(df)
        enriched = self._indicator_calc.calculate(
            df, self._required_indicators or list(self._required_columns)
        )
        self._enriched_frame = enriched
        return enriched

    def _trim_frame(self, df: Any) -> Any:
        """Cap the enriched frame to the warmup max length to bound memory."""
        max_len = self._warmup.max_length
        try:
            if hasattr(df, "iloc") and len(df) > max_len:
                return df.iloc[-max_len:]
        except TypeError:
            pass
        return df

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
        if self._order_planner is None:
            return CandleProcessingResult(
                candle_timestamp=candle_ts,
                enrichment_valid=True,
                signal_action=signal.action.value,
                message="processed — no order planner wired",
            )

        # The enriched bar dict omits the timestamp (it is the DataFrame
        # index), so inject the normalized candle timestamp for any gate
        # (e.g. StaleDataGate) that needs it.
        bar_with_ts = {**bar, "timestamp": candle_ts}
        ctx = self._build_risk_context(bar_with_ts, position)
        plan = self._order_planner.plan(signal, ctx)

        self._persist_risk_decision(plan)
        if not plan.accepted:
            return CandleProcessingResult(
                candle_timestamp=candle_ts,
                enrichment_valid=True,
                signal_action=signal.action.value,
                risk_decision="rejected",
                message=plan.reason,
            )

        # Batch all per-candle writes into one transaction so SQLite commits
        # (fsync) once per candle instead of once per write (P7).
        intent_id, submitted = self._with_persistence_transaction(
            lambda: self._commit_accepted_plan(plan, signal.action.value, candle_ts)
        )

        return CandleProcessingResult(
            candle_timestamp=candle_ts,
            enrichment_valid=True,
            signal_action=signal.action.value,
            risk_decision="accepted",
            intent_id=intent_id,
            submitted=submitted,
            message="processed — order planned",
        )

    def _commit_accepted_plan(
        self, plan, action: str, candle_ts: int
    ) -> tuple[str, bool]:
        """Persist signal + intent and submit, assuming an accepted plan."""
        self._mark_signal_processed(plan, action, candle_ts)
        return self._dispatch_submission(plan)

    def _with_persistence_transaction(self, fn):
        """Run *fn* inside a repo transaction if the repo supports one.

        Falls back to direct execution for in-memory repos that don't expose
        ``transaction`` (they have no fsync cost to avoid).
        """
        tx = getattr(self._repo, "transaction", None)
        if tx is None:
            return fn()
        with tx():
            return fn()

    def _build_risk_context(
        self, bar: dict[str, Any], position: PositionSnapshot
    ) -> dict[str, Any]:
        """Assemble the context dict consumed by the risk gates."""
        return {
            "bar": bar,
            "symbol": self._symbol,
            "bot_run_id": self._bot_run_id,
            "mode": self._mode.value,
            "position_size": position.size,
            "open_order_count": len(
                self._exchange.list_open_orders(self._symbol or "")
            ),
            "daily_loss_usd": self._trade_ledger.realized_loss_on(
                _dt.now(UTC).date()
            ),
        }

    def _mark_signal_processed(self, plan, action: str, candle_ts: int) -> None:
        """Record the signal key so replays are treated as duplicates."""
        self._repo.mark_signal_processed(
            ProcessedSignal(
                signal_key=plan.signal_key,
                bot_run_id=self._bot_run_id,
                signal_action=action,
                bar_timestamp=str(candle_ts),
            )
        )

    def _persist_risk_decision(self, plan) -> None:
        """Record the planner's accept/reject decision as a risk event."""
        gate_name = plan.gate_name or "risk"
        if plan.accepted:
            self._repo.record_risk_event(
                RiskEventRecord(
                    bot_run_id=self._bot_run_id,
                    event_type=gate_name,
                    signal_key=plan.signal_key,
                    decision="accepted",
                )
            )
            return
        self._repo.record_risk_event(
            RiskEventRecord(
                bot_run_id=self._bot_run_id,
                event_type=gate_name,
                signal_key=plan.signal_key,
                decision="rejected",
                reason=plan.reason,
            )
        )

    def _dispatch_submission(self, plan) -> tuple[str, bool]:
        """Persist the order intent and submit it according to the run mode."""
        intent = plan.intent
        if intent is None:
            return "", False

        if self._cloid_gen is not None:
            intent = intent.with_cloid(self._cloid_gen.generate(plan.signal_key))
        intent_id = self._repo.record_order_intent(intent)

        if self._mode == TradingMode.DRY_RUN:
            self._exchange.submit_order(intent)
            # Synthesize a fill so the TradeLedger tracks the position
            # in dry-run mode, keeping parity with live/testnet where
            # real fills arrive via the account stream (ADR-8).
            fill = self._synthesize_fill(intent, intent_id)
            if fill is not None:
                self._trade_ledger.apply_fill(fill)
            return intent_id, False

        if self._mode in (TradingMode.TESTNET, TradingMode.LIVE):
            bar = self._warmup.latest_bar
            ref_price = Decimal(str(bar.get("close", 0)))
            submitted = self._submitter.submit(
                intent, intent_id, self._bot_run_id, ref_price
            )
            return intent_id, submitted

        return intent_id, False

    def _synthesize_fill(
        self, intent, intent_id: str
    ) -> FillRecord | None:
        """Build a synthetic FillRecord from an OrderIntent for dry-run.

        Uses the latest bar's close as the fill price.  The fill_id is
        derived from the intent_id for idempotency.

        Returns None when the warmup window has no latest bar.
        """
        bar = self._warmup.latest_bar
        if bar is None:
            return None
        ref_price = Decimal(str(bar.get("close", "0")))
        if ref_price <= 0:
            return None
        return FillRecord(
            bot_run_id=self._bot_run_id,
            order_id=intent_id,
            symbol=intent.symbol,
            side=intent.side.value,
            size=intent.size,
            price=ref_price,
            fee=Decimal("0"),
            fill_id=f"dry:{intent_id}",
            filled_at=_dt.now(UTC),
        )


# -- module-level helpers -----------------------------------------------------


def _normalize_ts(candle: dict[str, Any]) -> int:
    ts = candle.get("timestamp", 0)
    if isinstance(ts, float):
        return int(ts)
    return int(ts)
