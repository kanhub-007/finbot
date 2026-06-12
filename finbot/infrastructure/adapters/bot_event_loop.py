"""Bot event loop — dequeues events and dispatches to the strategy pipeline.

All SDK callbacks enqueue events into a thread-safe queue.  This
event loop runs on the main thread and processes events sequentially,
keeping SDK threads isolated from strategy execution.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any

from finbot.core.application.dto.bot_event import BotEvent, BotEventType
from finbot.core.domain.interfaces.event_queue import EventQueue
from finbot.core.domain.interfaces.market_data_stream import MarketDataStream

logger = logging.getLogger(__name__)


class BotEventLoop:
    """Main event loop for the live trading bot.

    Parameters
    ----------
    queue:
        Thread-safe event queue shared with SDK callbacks.
    stream:
        Market data stream that feeds candle events.
    on_candle:
        Called for each candle event (bar dict).
    on_stale:
        Called when stale data is detected.
    reconnect_backoff:
        Initial backoff seconds for reconnect attempts (doubles
        on each retry, capped at 60 s).
    """

    MAX_BACKOFF = 60.0

    def __init__(
        self,
        queue: EventQueue,
        stream: MarketDataStream,
        on_candle: Callable[[dict[str, Any]], None],
        on_stale: Callable[[dict[str, Any]], None] | None = None,
        reconnect_backoff: float = 2.0,
    ) -> None:
        self._queue = queue
        self._stream = stream
        self._on_candle = on_candle
        self._on_stale = on_stale
        self._reconnect_backoff = reconnect_backoff
        self._running = False
        self._symbol: str = ""
        self._interval: str = ""

    # -- public API --------------------------------------------------------

    def start(self, symbol: str, interval: str) -> None:
        """Subscribe to candles and begin processing events.

        Blocks the calling thread until :meth:`stop` is called.
        """
        self._symbol = symbol
        self._interval = interval
        self._running = True

        try:
            self._subscribe()
        except Exception as exc:
            logger.warning("Initial subscribe failed: %s", exc)
            self._reconnect()

        while self._running:
            event = self._queue.dequeue(timeout=1.0)
            if event is None:
                continue
            self._dispatch(event)

        # Graceful shutdown: flush remaining events.
        self._flush()

    def stop(self) -> None:
        """Signal the event loop to shut down gracefully."""
        self._running = False

    # -- internal -----------------------------------------------------------

    def _subscribe(self) -> None:
        """Subscribe to candles, routing events through the queue."""
        self._stream.subscribe_candles(
            self._symbol,
            self._interval,
            callback=self._enqueue_from_callback,
        )

    def _reconnect(self) -> None:
        """Stop the stream, back off, and re-subscribe."""
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
        """SDK callback — runs on websocket thread."""
        if raw.get("_stale"):
            self._queue.enqueue(BotEvent(type=BotEventType.STALE, data=raw))
            return
        self._queue.enqueue(BotEvent(type=BotEventType.CANDLE, data=raw))

    def _dispatch(self, event: BotEvent) -> None:
        if event.type == BotEventType.CANDLE:
            self._on_candle(event.data)
        elif event.type == BotEventType.STALE:
            if self._on_stale:
                self._on_stale(event.data)
        elif event.type == BotEventType.SHUTDOWN:
            self._running = False

    def _flush(self) -> None:
        """Process all remaining events before shutting down."""
        for _ in range(self._queue.size()):
            event = self._queue.dequeue(timeout=0)
            if event is not None:
                self._dispatch(event)
        self._queue.clear()
        try:
            self._stream.stop()
        except Exception:
            pass
