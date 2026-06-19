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
from datetime import UTC
from datetime import datetime as _dt
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
from finbot.core.domain.dto.validate_strategy_request import (
    ValidateStrategyRequest,
)
from finbot.core.domain.entities.audit_log_entry import AuditLogEntry
from finbot.core.domain.entities.bot_config import BotConfig
from finbot.core.domain.entities.bot_run import BotRun
from finbot.core.domain.entities.enrichment_validation_result import (
    EnrichmentValidationResult,
)
from finbot.core.domain.entities.order_lifecycle import OrderLifecycle
from finbot.core.domain.entities.order_state import OrderState
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
from finbot.core.domain.events.runtime_events import RiskTriggeredEvent
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
        submission_strategy: Any,
        event_emitter: Any,
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
        live_state: Any | None = None,
    ) -> None:
        self._exchange = exchange_gateway
        self._evaluator = strategy_evaluator
        self._repo = state_repository
        self._indicator_calc = indicator_calculator
        self._enrichment_validator = enrichment_validator
        self._bar_converter = bar_frame_converter
        self._mode = mode
        self._submission_strategy = submission_strategy
        self._event_emitter = event_emitter
        self._order_planner = order_planner
        self._metadata_provider = market_metadata_provider
        self._order_normalizer = order_normalizer
        self._cloid_gen = cloid_generator
        self._bot_loop = bot_loop
        self._strategy_validator = strategy_validator
        self._account_handler = account_event_handler
        self._trade_ledger = trade_ledger or TradeLedger(self._repo)
        self._live_state = live_state
        self._required_columns: set[str] = required_columns or set()
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
            private_key=config.private_key.raw,
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
        # Build blockers deterministically: parse errors first, then features
        # in sorted order. Avoids the prior append-then-insert pattern that
        # could duplicate the parse entry (M6).
        blockers: list[str] = []
        if mode_info.get("parse") == "error":
            blockers.append("strategy parsing failed")
        for feature in sorted(mode_info):
            if feature == "parse":
                continue
            status = mode_info[feature]
            if status not in ("supported", "parse"):
                blockers.append(f"{feature}: {status}")
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
        """Fetch exchange position + open orders; reconcile against the DB.

        Called once at the start of ``run_forever()``. Two reconciliations
        run:

        * **Position** — if the exchange reports an open position but the
          DB has no Trade for it (e.g. crash mid-session), an open Trade is
          reconstructed with unknown entry price.
        * **Open orders** — exchange open orders are fetched and any oid the
          DB doesn't know about is persisted as a stub ``OrderLifecycle``
          in the ``OPEN`` state (so ``MaxOpenOrdersGate`` and duplicate-cloid
          tracking see them). ``open_orders_match`` reflects whether the two
          sides agreed; mismatches are enumerated in ``details``.
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

        open_orders_match, order_details = self._reconcile_open_orders()

        record = ReconciliationRecord(
            bot_run_id=self._bot_run_id,
            position_matches=(
                existing is not None or position.direction == PositionDirection.FLAT
            ),
            open_orders_match=open_orders_match,
            details=(
                f"startup: exchange={position.direction.value} "
                f"db_open={'yes' if existing else 'no'}; {order_details}"
            ),
        )
        self._repo.record_reconciliation(record)
        return record

    def _reconcile_open_orders(self) -> tuple[bool, str]:
        """Diff exchange open orders against DB lifecycles.

        Upserts a stub ``OrderLifecycle`` (state=OPEN) for every exchange oid
        the DB doesn't already track. Existing lifecycles are left untouched
        so their transition history is preserved.

        Returns ``(match, details)`` where ``match`` is False when the two
        sides disagreed **before** reconcile (either side had an oid the
        other didn't) and ``details`` enumerates the unmatched oids for
        operator diagnosis. Newly-persisted stubs count as a mismatch —
        the DB was genuinely missing them.
        """
        try:
            exchange_orders = self._exchange.list_open_orders(self._symbol)
        except Exception:
            logger.warning(
                "open-orders reconcile: list_open_orders failed", exc_info=True
            )
            return True, "open-orders reconcile skipped (exchange read failed)"

        exchange_oids: set[str] = set()
        newly_persisted: list[str] = []
        for order in exchange_orders or []:
            oid = str(order.get("oid", ""))
            if not oid:
                continue
            exchange_oids.add(oid)
            if self._repo.get_order_lifecycle(oid) is None:
                self._repo.save_order_lifecycle(
                    OrderLifecycle(
                        order_id=oid,
                        symbol=self._symbol,
                        side=_normalise_order_side(order.get("side", "")),
                        original_size=_parse_decimal(order.get("sz")),
                        state=OrderState.OPEN,
                    )
                )
                newly_persisted.append(oid)

        # Diff against DB oids the exchange reports as open. Stale local
        # rows (DB has them, exchange doesn't) are the other mismatch source.
        db_open_oids = {
            lc.order_id
            for lc in self._repo.list_open_order_lifecycles(symbol=self._symbol)
        }
        only_db = db_open_oids - exchange_oids
        match = not newly_persisted and not only_db
        if match:
            return True, f"open-orders match ({len(exchange_oids)})"
        parts: list[str] = []
        if newly_persisted:
            parts.append(f"newly-persisted={sorted(newly_persisted)}")
        if only_db:
            parts.append(f"db-only={sorted(only_db)}")
        return False, "open-orders mismatch: " + "; ".join(parts)

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

        Delegates to the injected :class:`AccountEventHandler`. The handler
        is a required constructor dependency (H8) — it is no longer lazily
        constructed so a fake can be injected for testing.
        """
        if self._account_handler is None:
            raise RuntimeError(
                "No AccountEventHandler injected — cannot process account events"
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
        """Build the OHLCV frame and recompute indicators for the latest candle.

        The frame is cached and appended to (one row) per candle instead of
        being rebuilt from the warmup list, then trimmed to the warmup max
        length so it cannot grow unbounded over a long session.

        Cost note: per-candle work is ``O(max_length)`` — the append+trim
        copies the frame and the indicator calculator recomputes *every*
        requested indicator over the full frame each call (the package
        calculator is stateless). The indicator recompute dominates; making
        it ``O(1)`` per bar needs a streaming indicator engine, tracked
        separately. ``max_length`` (default 500) is the bounding knob.
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
        """Cap the enriched frame to the warmup max length to bound memory.

        No copy is made when the frame is already within the limit.
        """
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
        self._emit_risk("enrichment_validation", validation.reason, bot_stopped=False)
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
            "leverage": self._read_leverage(),
            "open_order_count": len(
                self._exchange.list_open_orders(self._symbol or "")
            ),
            "daily_loss_usd": self._trade_ledger.realized_loss_on(_dt.now(UTC).date()),
        }

    def _read_leverage(self) -> int:
        """Return the active symbol's leverage, falling back to 1 when unknown.

        ``ExchangeGateway.get_leverage`` returns ``None`` when the exchange
        has no position yet for the symbol (Hyperliquid only reports
        leverage on an open position). The fallback matches the
        ``MaxLeverageGate`` documented default of 1x.
        """
        try:
            reported = self._exchange.get_leverage(self._symbol or "")
        except Exception:
            logger.debug("get_leverage failed", exc_info=True)
            return 1
        if reported is None:
            return 1
        return int(reported[0])

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
        # Notify for actionable risk events (skip noise like duplicate signals)
        if gate_name not in ("duplicate_signal",):
            self._emit_risk(
                gate_name,
                plan.reason or f"Order blocked by {gate_name}",
                bot_stopped=(gate_name in ("daily_loss", "mode")),
            )

    def _dispatch_submission(self, plan) -> tuple[str, bool]:
        """Delegate order submission to the mode-specific strategy."""
        intent = plan.intent
        if intent is None:
            return "", False

        if self._cloid_gen is not None:
            intent = intent.with_cloid(self._cloid_gen.generate(plan.signal_key))

        return self._submission_strategy.submit(
            intent, self._bot_run_id, self._warmup.latest_bar
        )

    # -- event emission -----------------------------------------------------

    def _emit_risk(self, event_type: str, reason: str, *, bot_stopped: bool) -> None:
        """Emit a risk-triggered event to all registered observers."""
        try:
            self._event_emitter.emit(
                RiskTriggeredEvent(
                    run_id=self._bot_run_id,
                    event_type=event_type,
                    reason=reason,
                    bot_stopped=bot_stopped,
                )
            )
        except Exception:
            logger.debug("Failed to emit risk event", exc_info=True)


# -- module-level helpers -----------------------------------------------------


def _normalize_ts(candle: dict[str, Any]) -> int:
    ts = candle.get("timestamp", 0)
    if isinstance(ts, float):
        return int(ts)
    return int(ts)


def _normalise_order_side(raw: Any) -> str:
    """Normalise a Hyperliquid open-order ``side`` field to a lifecycle side.

    The exchange uses "B"/"S" (and occasionally "buy"/"sell"); lifecycles
    store the lowercase word. Falls back to "unknown" so an unexpected
    payload never crashes reconciliation.
    """
    s = str(raw).strip().lower()
    if s in ("b", "buy", "long"):
        return "buy"
    if s in ("s", "sell", "short"):
        return "sell"
    return "unknown"


def _parse_decimal(value: Any) -> Decimal:
    """Parse an exchange numeric field into a Decimal (0 on failure).

    Used for ``sz`` fields in open-order payloads. Never raises — a
    malformed size shouldn't abort reconciliation.
    """
    try:
        return Decimal(str(value))
    except Exception:
        return Decimal("0")
