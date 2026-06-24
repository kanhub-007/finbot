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
import math
from datetime import UTC
from datetime import datetime as _dt
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
from finbot.core.domain.interfaces.bar_enricher import (
    BarEnricher,
)
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
from finbot.core.domain.interfaces.order_submission_strategy import (
    OrderSubmissionStrategy,
)
from finbot.core.domain.interfaces.required_data_validator import (
    RequiredDataValidator,
)
from finbot.core.domain.interfaces.runtime_event_emitter import RuntimeEventEmitter
from finbot.core.domain.interfaces.strategy_definition_loader import (
    StrategyDefinitionLoader,
)
from finbot.core.domain.interfaces.strategy_evaluator import (
    StrategyEvaluator,
)
from finbot.core.domain.interfaces.strategy_validator import (
    StrategyValidator,
)
from finbot.core.domain.interfaces.causal_streaming_enricher import (
    CausalStreamingEnricher,
)
from finbar_strategy_runtime.domain.entities.causal_enriched_bar import (
    CausalEnrichedBar,
)

from finbot.core.domain.services.live_mode_guard import check_live_mode
from finbot.core.domain.services.order_helpers import (
    normalize_order_side,
    parse_decimal,
)
from finbot.core.domain.services.trade_ledger import TradeLedger
from finbot.core.domain.services.transactional import transactional
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
        submission_strategy: OrderSubmissionStrategy,
        event_emitter: RuntimeEventEmitter,
        warmup_bars: list[dict[str, Any]] | None = None,
        required_columns: set[str] | None = None,
        required_indicators: list[str] | None = None,
        order_planner: OrderPlanner | None = None,
        market_metadata_provider: MarketMetadataProvider | None = None,
        order_normalizer: OrderNormalizer | None = None,
        cloid_generator: CloidGenerator | None = None,
        bot_loop: BotLoop | None = None,
        strategy_validator: StrategyValidator | None = None,
        strategy_loader: StrategyDefinitionLoader | None = None,
        account_event_handler: AccountEventHandler | None = None,
        trade_ledger: TradeLedger | None = None,
        live_state: Any | None = None,
        strategy_log_writer: Any | None = None,
        interval: str = "",
        informative_intervals: list[str] | None = None,
        bar_enricher: BarEnricher | None = None,
        required_data_validator: RequiredDataValidator | None = None,
        causal_streaming_enricher: CausalStreamingEnricher | None = None,
        informative_warmup_bars: dict[str, list[dict[str, Any]]] | None = None,
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
        self._strategy_loader = strategy_loader
        self._account_handler = account_event_handler
        self._trade_ledger = trade_ledger or TradeLedger(self._repo)
        self._live_state = live_state
        self._log_writer = strategy_log_writer
        self._required_columns: set[str] = required_columns or set()
        self._required_indicators: list[str] = (
            list(required_indicators) if required_indicators else []
        )
        self._bot_run_id: str = ""
        self._strategy_name: str = ""
        self._strategy_hash: str = ""
        self._symbol: str = ""
        self._interval: str = interval or ""
        self._started: bool = False
        self._informative_intervals: list[str] = list(informative_intervals or [])
        # Cache of latest bar per informative timeframe (MTF).
        # Dict of alias → bar; initialized on first informative candle.
        self._informative_cache: dict[str, dict[str, Any]] = {}

        # Slice-1 shared primitives (optional; when wired they replace the
        # legacy single-TF indicator + fixed-count warmup gate). See this
        # spec's ADR-1 / ADR-4.
        self._bar_enricher = bar_enricher
        self._required_data_validator = required_data_validator
        # Causal streaming enricher (Slice 2 parity — replaces batch
        # recompute with stateful causal MTF enrichment). When wired,
        # the runtime feeds each bar to the streaming engine and reads
        # the latest causal enriched row directly — no DataFrame rebuild.
        self._causal_streaming_enricher = causal_streaming_enricher
        if causal_streaming_enricher is not None and warmup_bars:
            for bar in warmup_bars:
                causal_streaming_enricher.update_primary(bar)
        if causal_streaming_enricher is not None and informative_warmup_bars:
            for alias, bars in informative_warmup_bars.items():
                for bar in bars:
                    causal_streaming_enricher.update_informative(alias, bar)
        self._required_data_validator = required_data_validator
        self._informative_warmups: dict[str, WarmupWindow] = {}
        if informative_warmup_bars:
            for alias, bars in informative_warmup_bars.items():
                window = WarmupWindow()
                for bar in bars:
                    window.append(bar)
                self._informative_warmups[alias] = window
        # Cached first-tradable index from the data-driven validator.
        self._first_tradable_index: int | None = None

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

    def get_resolved_intervals(self) -> dict[str, object]:
        """Return the resolved primary + informative intervals.

        Public accessor so callers (``BotLifecycleService``) don't need
        to reach into private ``_interval`` / ``_informative_intervals``
        via ``hasattr``.  Returns a dict suitable for JSON-serialisation
        in MCP/Telegram status responses.
        """
        result: dict[str, object] = {"interval": self._interval}
        if self._informative_intervals:
            result["informative_intervals"] = ",".join(self._informative_intervals)
        return result

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
        # Delegate file I/O to the injected strategy loader (domain interface)
        # so this use case has no filesystem dependency.
        if self._strategy_loader is None:
            return RunBotResult(
                status="rejected",
                message="strategy compatibility: no strategy loader available",
            )
        try:
            content = self._strategy_loader.load_content(strategy_path)
        except Exception as e:  # noqa: BLE001 - fail closed
            logger.warning("Strategy content load failed: %s", e)
            if mode in ("testnet", "live"):
                return RunBotResult(
                    status="rejected",
                    message=f"strategy compatibility: cannot read strategy ({e})",
                )
            return None
        try:
            result = self._strategy_validator.compatibility(
                ValidateStrategyRequest(
                    strategy_path=strategy_path, strategy_content=content
                )
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
                        side=normalize_order_side(order.get("side", "")),
                        original_size=parse_decimal(order.get("sz")),
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
        """Process a single closed candle through the full pipeline.

        Dispatches to the shared-primitives path (Slice 1: ``MultiTimeframeBarEnricher``
        + data-driven ``RequiredDataValidator``) when both are wired, otherwise
        falls back to the legacy single-TF indicator + fixed-count warmup path.
        """
        ts = _normalize_ts(candle)
        self._warmup.append(candle)
        if self._causal_streaming_enricher is not None:
            return self._process_candle_causal_streaming(candle, ts)
        if self._bar_enricher is not None and self._required_data_validator is not None:
            return self._process_candle_shared(candle, ts)
        return self._process_candle_legacy(candle, ts)

    def _process_candle_legacy(
        self, candle: dict[str, Any], ts: int
    ) -> CandleProcessingResult:
        """Legacy path: single-TF indicator calc + fixed ``min_bars`` warmup gate.

        Preserved for runtimes that do not wire the shared enricher/validator
        (e.g. some unit tests). Production wires both via the composition root.
        """
        # 1. Warmup
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

        # First candle after warmup — log completion.
        if self._warmup_needed:
            self._warmup_needed = False
            logger.info(
                "Warmup complete — %d bars loaded, strategy evaluation starting",
                self._warmup.count,
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
            logger.warning(
                "\u26a0 %s/%s candle=%s enrichment INVALID: %s",
                self._symbol,
                self._interval,
                ts,
                validation.reason,
            )
            self._log_decision(ts, candle, latest, validation=validation)
            return self._handle_enrichment_rejection(ts, validation)

        # 4. Evaluate strategy
        position = self._exchange.get_position(self._symbol or "DEFAULT")
        signal = self._evaluator.evaluate(latest, position)
        close_price = latest.get("close", "?")

        # 5. If HOLD, no further processing
        if signal.action == SignalAction.HOLD:
            logger.info(
                "\u25b3 %s/%s candle=%s close=%s action=HOLD",
                self._symbol,
                self._interval,
                ts,
                close_price,
            )
            self._log_decision(ts, candle, latest, signal=signal)
            return CandleProcessingResult(
                candle_timestamp=ts,
                enrichment_valid=True,
                signal_action=signal.action.value,
                message="processed — HOLD",
            )

        # 6. Risk gates + order planning (delegated to OrderPlanner)
        result = self._plan_and_persist(signal, latest, position, ts)
        risk = result.risk_decision or "accepted"
        intent_info = ""
        if result.intent_id:
            side = signal.action.value
            intent_info = f" {side}"
        if result.submitted:
            intent_info += " submitted"
        logger.info(
            "\u25b6 %s/%s candle=%s close=%s action=%s risk=%s%s",
            self._symbol,
            self._interval,
            ts,
            close_price,
            signal.action.value,
            risk,
            intent_info,
        )
        return result

    def _process_candle_causal_streaming(
        self, candle: dict[str, Any], ts: int
    ) -> CandleProcessingResult:
        """Causal streaming path: stateful MTF enricher + row-based readiness.

        Each bar is fed to the package ``CausalMultiTimeframeStreamingEnricher``
        which maintains per-timeframe state and returns the latest causal enriched
        row. No full-window recomputation — O(session) bounded, not O(n²).

        Readiness is gated by the enricher's ``is_ready`` flag AND a check that
        all required columns are non-NaN in the latest values. Bars before
        readiness feed ``on_bar`` for state-building only.
        """
        self._tick_submission_on_bar(candle)
        result = self._causal_streaming_enricher.update_primary(candle)
        latest = result.values

        # Row-level readiness: enricher warmup + all required cols non-NaN.
        ready = result.is_ready
        if ready and self._required_columns:
            ready = all(
                c in latest
                and not (isinstance(latest.get(c), float) and math.isnan(latest[c]))
                for c in self._required_columns
            )

        if not ready:
            return self._handle_warmup_state_building(
                candle, latest, ts,
                current_idx=self._warmup.count,
                first_tradable=0,  # data-driven readiness; count is informational
            )

        if self._warmup_needed:
            self._warmup_needed = False
            logger.info(
                "Warmup complete — causal streaming enricher ready (%d bars)",
                self._warmup.count,
            )

        return self._evaluate_and_plan(candle, latest, ts)

    def _process_candle_shared(
        self, candle: dict[str, Any], ts: int
    ) -> CandleProcessingResult:
        """Shared-primitives path: MTF enricher + data-driven warmup.

        Enrichment goes through the package ``MultiTimeframeBarEnricher``;
        readiness is gated by ``RequiredDataValidator`` (first row where all
        required columns are non-NaN), not a fixed ``min_bars`` count. Bars
        before ``first_tradable`` feed ``on_bar`` for **state-building only**
        — no orders are generated (this spec's ADR-4 / parity rule).
        """
        # Let a bar-aware submission strategy (e.g. ReplayFillExchange) process
        # pending entries / intrabar stops before this bar's signal evaluation.
        self._tick_submission_on_bar(candle)
        enriched = self._enrich_bars()
        if self._bar_converter.is_empty(enriched):
            return CandleProcessingResult(
                candle_timestamp=ts,
                enrichment_valid=False,
                enrichment_errors=["indicator engine returned empty result"],
                message="enrichment failed — empty result",
            )
        latest = self._bar_converter.latest_bar(enriched)

        readiness = self._required_data_validator.validate(
            enriched, list(self._required_columns)
        )
        first_tradable = int(readiness.get("warmup_bars", 0))
        current_idx = max(len(enriched) - 1, 0)
        if current_idx < first_tradable or readiness.get("no_tradable_bars", False):
            return self._handle_warmup_state_building(
                candle, latest, ts, current_idx, first_tradable
            )

        if self._warmup_needed:
            # When warmup bars are pre-seeded (warmup_bars param), the
            # runtime's window may already contain bars up to (and past)
            # first_tradable before the first live candle arrives. In that
            # case we must batch-call on_bar on the warmup prefix so the
            # strategy's crossover state mirrors what a bar-by-bar warmup
            # would have produced. Without this, the first tradable bar
            # evaluates with an empty PreviousValues dict and the signal
            # diverges from the backtest.
            if current_idx >= first_tradable:
                self._build_crossover_state_from_seed(enriched, first_tradable)
            self._warmup_needed = False
            logger.info(
                "Warmup complete — first_tradable at index %d (%d bars loaded)",
                first_tradable,
                self._warmup.count,
            )

        return self._evaluate_and_plan(candle, latest, ts)

    def _tick_submission_on_bar(self, candle: dict[str, Any]) -> None:
        """Forward the bar to a bar-aware submission strategy if present.

        ``ReplayFillExchange`` (dry-run/replay) uses this to fill pending
        entries at the open and resolve intrabar stop/target exits between
        signal bars. Live submission strategies do not implement ``on_bar``
        and are unaffected.
        """
        strategy = self._submission_strategy
        if strategy is None:
            return
        on_bar = getattr(strategy, "on_bar", None)
        if callable(on_bar):
            on_bar(candle)

    def _build_crossover_state_from_seed(
        self, enriched: Any, first_tradable: int
    ) -> None:
        """Call ``on_bar`` on warmup rows 0..first_tradable-1 to build crossover
        state from pre-seeded warmup bars.

        Mirrors what the incremental warmup path (``_handle_warmup_state_building``)
        achieves one bar at a time. All rows are evaluated against a flat position
        — no trades are generated during this phase.
        """
        position = self._exchange.get_position(self._symbol or "DEFAULT")
        try:
            n_rows = len(enriched)
        except TypeError:
            n_rows = 0
        limit = min(first_tradable, n_rows)
        for i in range(limit):
            row = enriched.iloc[i].to_dict()
            self._evaluator.evaluate(row, position)

    def _handle_warmup_state_building(
        self,
        candle: dict[str, Any],
        latest: dict[str, Any],
        ts: int,
        current_idx: int,
        first_tradable: int,
    ) -> CandleProcessingResult:
        """Feed the bar to ``on_bar`` for state, suppress order generation."""
        if self._warmup_needed:
            logger.info(
                "Warmup %d/%d — state building (no orders)",
                current_idx + 1,
                first_tradable,
            )
        # Build strategy state (crossover/profile tracking) so the first
        # tradable bar sees warm state — mirrors finbar's `_update_warmup_state`.
        if not self._warmup.has_gap:
            position = self._exchange.get_position(self._symbol or "DEFAULT")
            self._evaluator.evaluate(latest, position)
        self._log_decision(ts, candle, latest)
        return CandleProcessingResult(
            candle_timestamp=ts,
            enrichment_valid=False,
            enrichment_errors=["warmup not ready"],
            message=f"warmup — state building ({current_idx + 1}/{first_tradable})",
        )

    def _evaluate_and_plan(
        self, candle: dict[str, Any], latest: dict[str, Any], ts: int
    ) -> CandleProcessingResult:
        """Bar-level validation, evaluate, and plan/persist for a tradable bar."""
        validation = self._enrichment_validator.validate(
            enriched_bar=latest,
            required_columns=self._required_columns,
            warmup_ready=True,
            has_gap=self._warmup.has_gap,
        )
        if not validation.valid:
            logger.warning(
                "\u26a0 %s/%s candle=%s enrichment INVALID: %s",
                self._symbol,
                self._interval,
                ts,
                validation.reason,
            )
            self._log_decision(None, latest, validation=validation)
            return self._handle_enrichment_rejection(ts, validation)

        position = self._exchange.get_position(self._symbol or "DEFAULT")
        signal = self._evaluator.evaluate(latest, position)
        close_price = latest.get("close", "?")
        if signal.action == SignalAction.HOLD:
            logger.info(
                "\u25b3 %s/%s candle=%s close=%s action=HOLD",
                self._symbol,
                self._interval,
                ts,
                close_price,
            )
            self._log_decision(ts, candle, latest, signal=signal)
            return CandleProcessingResult(
                candle_timestamp=ts,
                enrichment_valid=True,
                signal_action=signal.action.value,
                message="processed — HOLD",
            )
        result = self._plan_and_persist(signal, latest, position, ts)
        risk = result.risk_decision or "accepted"
        intent_info = ""
        if result.intent_id:
            intent_info = f" {signal.action.value}"
        if result.submitted:
            intent_info += " submitted"
        logger.info(
            "\u25b6 %s/%s candle=%s close=%s action=%s risk=%s%s",
            self._symbol,
            self._interval,
            ts,
            close_price,
            signal.action.value,
            risk,
            intent_info,
        )
        return result

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

    def process_informative_candle(self, alias: str, bar: dict[str, Any]) -> None:
        """Process a candle from an informative (non-primary) timeframe.

        Forwards to the causal streaming enricher when wired; otherwise
        appends to the per-alias warmup window for the batch enricher.
        """
        self._informative_cache[alias] = dict(bar)
        if self._causal_streaming_enricher is not None:
            self._causal_streaming_enricher.update_informative(alias, bar)
            return
        window = self._informative_warmups.get(alias)
        if window is None:
            window = WarmupWindow()
            self._informative_warmups[alias] = window
        window.append(bar)
        close_price = bar.get("close", "?")
        logger.debug(
            "\u2139 %s/%s informative=%s close=%s",
            self._symbol,
            alias,
            bar.get("timestamp", "?"),
            close_price,
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
        """Build the OHLCV frame and compute indicators for the latest candle.

        On the shared-primitives path (``bar_enricher`` wired), the frame is
        rebuilt from the warmup windows each candle and the shared
        ``MultiTimeframeBarEnricher`` does per-TF indicators + merge +
        features. The enricher is stateless (recomputes all columns from the
        full frame each call), so per-candle work is ``O(max_length)``; the
        warmup ``max_length`` bounds memory.

        On the legacy path, the frame is cached and appended to (one row)
        per candle, then the single-TF indicator calculator runs.
        """
        if self._bar_enricher is not None:
            informative = {
                alias: window.bars
                for alias, window in self._informative_warmups.items()
            }
            enriched = self._bar_enricher.enrich(self._warmup.bars, informative)
            return self._trim_frame(enriched)
        return self._enrich_bars_legacy()

    def _enrich_bars_legacy(self) -> Any:
        """Legacy: append one row to the cached frame and run single-TF indicators."""
        if self._enriched_frame is None or self._bar_converter.is_empty(
            self._enriched_frame
        ):
            df = self._bar_converter.bars_to_frame(self._warmup.bars)
        else:
            df = self._bar_converter.append_bar(
                self._enriched_frame, self._warmup.latest_bar
            )
            df = self._trim_frame(df)
        enriched = self._indicator_calc.calculate(df, self._required_indicators)
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
            self._log_decision(
                candle_ts,
                None,
                bar,
                signal=signal,
                risk={
                    "accepted": False,
                    "gate": plan.gate_name,
                    "reason": plan.reason,
                },
            )
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
        if plan.intent is not None:
            self._log_decision(
                candle_ts,
                None,
                bar,
                signal=signal,
                risk={"accepted": True},
                intent={
                    "symbol": plan.intent.symbol,
                    "side": plan.intent.side.value,
                    "size": str(plan.intent.size),
                    "type": plan.intent.order_type.value,
                    "reduce_only": plan.intent.reduce_only,
                    "limit_price": (
                        str(plan.intent.limit_price)
                        if plan.intent.limit_price
                        else None
                    ),
                    "submitted": submitted,
                    "intent_id": intent_id,
                },
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
        """Run *fn* inside a repo transaction if the repo supports one."""
        return transactional(self._repo, fn)

    def _build_risk_context(
        self, bar: dict[str, Any], position: PositionSnapshot
    ) -> dict[str, Any]:
        """Assemble the context dict consumed by the risk gates."""
        # Use cache-only count to avoid a blocking REST call on every
        # non-HOLD candle.  Falls back to 0 when the cache is stale
        # (the StaleDataGate already covers that case).
        cached_count = self._exchange.count_open_orders_cached(self._symbol or "")
        open_order_count = 0 if cached_count is None else cached_count

        return {
            "bar": bar,
            "symbol": self._symbol,
            "bot_run_id": self._bot_run_id,
            "mode": self._mode.value,
            "position_size": position.size,
            "leverage": self._read_leverage(),
            "open_order_count": open_order_count,
            "daily_loss_usd": self._trade_ledger.realized_loss_on(_dt.now(UTC).date()),
        }

    def _read_leverage(self) -> int | None:
        """Return active leverage, failing closed when live risk data is unknown.

        Dry-run and no-position accounts may safely assume 1x. Testnet/live
        return ``None`` only when the exchange read fails; the
        ``MaxLeverageGate`` rejects explicit unknown leverage instead of
        pretending failed risk-data reads are safe.
        """
        try:
            reported = self._exchange.get_leverage(self._symbol or "")
        except Exception:
            logger.warning("get_leverage failed", exc_info=True)
            return 1 if self._mode == TradingMode.DRY_RUN else None
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

    def _log_decision(
        self,
        ts: int,
        candle: dict[str, Any] | None = None,
        enriched_bar: dict[str, Any] | None = None,
        *,
        validation: Any | None = None,
        signal: SignalDecision | None = None,
        risk: dict[str, Any] | None = None,
        intent: dict[str, Any] | None = None,
    ) -> None:
        """Write one evaluation log entry if a writer is configured."""
        if self._log_writer is None:
            return
        indicators: dict[str, Any] | None = None
        if enriched_bar:
            indicators = {
                k: enriched_bar[k]
                for k in self._required_indicators
                if k in enriched_bar
            }
        validation_dict: dict[str, Any] | None = None
        if validation is not None:
            validation_dict = {
                "valid": getattr(validation, "valid", False),
                "reason": getattr(validation, "reason", ""),
            }
        signal_dict: dict[str, Any] | None = None
        if signal is not None:
            signal_dict = {
                "action": signal.action.value,
            }
        self._log_writer.log_candle(
            strategy_file=self._strategy_name,
            symbol=self._symbol,
            interval=self._interval,
            timestamp=ts,
            candle=candle,
            indicators=indicators,
            validation=validation_dict,
            signal=signal_dict,
            risk=risk,
            intent=intent,
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
