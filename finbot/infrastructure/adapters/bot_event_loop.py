"""Bot event loop — dequeues events and dispatches to the strategy pipeline.

All SDK callbacks enqueue events into a thread-safe queue.  This
event loop runs on the main thread and processes events sequentially,
keeping SDK threads isolated from strategy execution.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any, Protocol

from finbot.core.domain.entities.bot_event import BotEvent
from finbot.core.domain.entities.bot_event_type import BotEventType
from finbot.core.domain.interfaces.bot_loop import BotLoop
from finbot.core.domain.interfaces.event_queue import EventQueue
from finbot.core.domain.interfaces.market_data_stream import MarketDataStream

logger = logging.getLogger(__name__)


class AccountStream(Protocol):
    """Minimal protocol for an account websocket stream."""

    def start(self) -> None: ...

    def stop(self) -> None: ...


class BotEventLoop(BotLoop):
    """Main event loop for the live trading bot.

    Parameters
    ----------
    queue:
        Thread-safe event queue shared with SDK callbacks.
    stream:
        Market data stream that feeds candle events.
    reconnect_backoff:
        Initial backoff seconds for reconnect attempts.
    """

    MAX_BACKOFF = 60.0
    #: Seconds a candle may take before its processing is logged as a stall
    #: (P12 — tail-latency observability for account events queued behind it).
    CANDLE_STALL_WARN_SECONDS = 1.0

    def __init__(
        self,
        queue: EventQueue,
        stream: MarketDataStream,
        account_stream: AccountStream | None = None,
        reconnect_backoff: float = 2.0,
    ) -> None:
        self._queue = queue
        self._stream = stream
        self._account_stream = account_stream
        self._reconnect_backoff = reconnect_backoff
        self._running = False
        self._symbol: str = ""
        self._interval: str = ""
        self._on_candle: Callable[[dict[str, Any]], None] | None = None
        self._on_stale: Callable[[dict[str, Any]], None] | None = None
        self._on_account: Callable[[dict[str, Any]], None] | None = None

    # -- public API --------------------------------------------------------

    def start(
        self,
        symbol: str,
        interval: str,
        on_candle: Callable[[dict[str, Any]], None],
        on_stale: Callable[[dict[str, Any]], None] | None = None,
        on_account_event: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        """Subscribe to candles and begin processing events.  Blocks until stop()."""
        self._symbol = symbol
        self._interval = interval
        self._on_candle = on_candle
        self._on_stale = on_stale
        self._on_account = on_account_event
        self._running = True

        try:
            self._subscribe()
        except Exception as exc:
            logger.warning("Initial subscribe failed: %s", exc)
            self._reconnect()

        if self._account_stream is not None:
            try:
                self._account_stream.start()
            except Exception as exc:  # noqa: BLE001 - keep market data flowing
                logger.warning("Account stream start failed: %s", exc)

        while self._running:
            event = self._queue.dequeue(timeout=1.0)
            if event is None:
                continue
            # Before any (potentially slow) candle work, drain account events
            # that have arrived so fills / order updates are not starved by a
            # long candle enrichment (P12 — tail-latency amplification).
            self._drain_account_events()
            self._dispatch_with_deadline(event)

        self._flush()

    def _drain_account_events(self) -> None:
        """Process any already-queued account events without blocking.

        Non-account events (e.g. queued candles) are re-enqueued at the tail.
        If the queue is full and a re-enqueue fails, the event is dispatched
        immediately rather than silently dropped — losing a candle would skip
        a strategy evaluation.
        """
        for _ in range(self._queue.size()):
            event = self._queue.dequeue(timeout=0)
            if event is None:
                break
            if event.type in (BotEventType.FILL, BotEventType.ORDER_UPDATE):
                self._dispatch(event)
            else:
                # Put non-account events back at the tail; dispatch on failure
                # (e.g. queue full) so the event is never silently lost.
                if not self._queue.enqueue(event):
                    self._dispatch(event)

    def _dispatch_with_deadline(self, event: BotEvent) -> None:
        """Dispatch an event, logging a warning if candle work stalls the loop."""
        import time

        started = time.monotonic()
        self._dispatch(event)
        elapsed = time.monotonic() - started
        if (
            event.type == BotEventType.CANDLE
            and elapsed > self.CANDLE_STALL_WARN_SECONDS
        ):
            logger.warning(
                "Candle processing took %.1fs (>%.1fs) — account events may lag",
                elapsed,
                self.CANDLE_STALL_WARN_SECONDS,
            )

    def stop(self) -> None:
        """Signal the event loop to shut down gracefully.

        Enqueues a sentinel ``SHUTDOWN`` event so a loop blocked on
        ``dequeue(timeout=1.0)`` wakes immediately instead of waiting up
        to 1 second for the next poll.
        """
        self._running = False
        from finbot.core.domain.entities.bot_event import BotEvent
        from finbot.core.domain.entities.bot_event_type import BotEventType

        self._queue.enqueue(BotEvent(type=BotEventType.SHUTDOWN, data={}))

    # -- internal -----------------------------------------------------------

    def _subscribe(self) -> None:
        self._stream.subscribe_candles(
            self._symbol,
            self._interval,
            callback=self._enqueue_from_callback,
        )

    def _reconnect(self) -> None:
        backoff = self._reconnect_backoff
        while self._running:
            try:
                self._stream.stop()
            except Exception:
                pass
            logger.info("Reconnecting in %.1f s …", backoff)
            time.sleep(backoff)
            backoff = min(backoff * 2, self.MAX_BACKOFF)
            try:
                self._subscribe()
                return
            except Exception as exc:
                logger.warning("Reconnect failed: %s", exc)

    def _enqueue_from_callback(self, raw: dict[str, Any]) -> None:
        if raw.get("_stale"):
            event = BotEvent(type=BotEventType.STALE, data=raw)
        else:
            event = BotEvent(type=BotEventType.CANDLE, data=raw)
        if not self._queue.enqueue(event):
            logger.warning("Event queue full — dropping %s event", event.type)

    def _dispatch(self, event: BotEvent) -> None:
        logger.debug("Dispatching event type=%s", event.type)
        if event.type == BotEventType.CANDLE and self._on_candle:
            self._on_candle(event.data)
        elif event.type == BotEventType.STALE and self._on_stale:
            self._on_stale(event.data)
        elif event.type in (BotEventType.FILL, BotEventType.ORDER_UPDATE):
            if self._on_account:
                self._on_account(event.data)
        elif event.type == BotEventType.SHUTDOWN:
            self._running = False

    def _flush(self) -> None:
        for _ in range(self._queue.size()):
            event = self._queue.dequeue(timeout=0)
            if event is not None:
                self._dispatch(event)
        self._queue.clear()
        if self._account_stream is not None:
            try:
                self._account_stream.stop()
            except Exception:  # noqa: BLE001
                pass
        try:
            self._stream.stop()
        except Exception:
            pass
