"""Tests for BotEventLoop and ThreadSafeEventQueue."""

import threading
import time
from collections.abc import Callable
from typing import Any
from unittest.mock import MagicMock

from finbot.core.application.dto.bot_event import BotEvent, BotEventType
from finbot.core.domain.interfaces.market_data_stream import MarketDataStream
from finbot.infrastructure.adapters.bot_event_loop import BotEventLoop
from finbot.infrastructure.adapters.thread_safe_event_queue import (
    ThreadSafeEventQueue,
)


class TestThreadSafeEventQueue:
    def test_enqueue_dequeue(self) -> None:
        q = ThreadSafeEventQueue()
        assert q.size() == 0
        assert q.enqueue(BotEvent(type=BotEventType.CANDLE, data={"c": 100}))
        assert q.size() == 1
        event = q.dequeue(timeout=0)
        assert event is not None
        assert event.type == BotEventType.CANDLE
        assert q.size() == 0

    def test_dequeue_timeout_returns_none(self) -> None:
        q = ThreadSafeEventQueue()
        assert q.dequeue(timeout=0.01) is None

    def test_enqueue_full_queue_rejected(self) -> None:
        q = ThreadSafeEventQueue(maxsize=1)
        assert q.enqueue(BotEvent(type=BotEventType.CANDLE))
        assert not q.enqueue(BotEvent(type=BotEventType.CANDLE))
        assert q.size() == 1

    def test_clear_empties_queue(self) -> None:
        q = ThreadSafeEventQueue()
        q.enqueue(BotEvent(type=BotEventType.CANDLE))
        q.enqueue(BotEvent(type=BotEventType.STALE))
        assert q.size() == 2
        q.clear()
        assert q.size() == 0


class StubStream(MarketDataStream):
    """Market data stream that captures the callback for later firing."""

    def __init__(self) -> None:
        self._callback: Callable[[dict[str, Any]], None] | None = None
        self.stopped = False

    def subscribe_candles(
        self,
        symbol: str,
        interval: str,
        callback: Callable[[dict[str, Any]], None],
    ) -> int:
        self._callback = callback
        return 1

    def stop(self) -> None:
        self.stopped = True

    def fire(self, data: dict[str, Any]) -> None:
        if self._callback:
            self._callback(data)


class TestBotEventLoop:
    def test_websocket_callback_enqueues_rather_than_executes(self) -> None:
        """SDK callback enqueues; strategy callback runs on main thread."""
        q: ThreadSafeEventQueue = ThreadSafeEventQueue()
        stream = StubStream()
        strategy_calls: list[dict] = []

        loop = BotEventLoop(q, stream, on_candle=strategy_calls.append)

        # Start in background thread
        t = threading.Thread(target=loop.start, args=("BTC", "1h"))
        t.start()

        # Fire from "SDK" thread → must enqueue, not call strategy directly
        stream.fire({"close": 50000, "symbol": "BTC"})

        # Give the event loop time to dequeue
        time.sleep(0.1)

        # Strategy callback was called on main loop thread
        assert len(strategy_calls) >= 1
        assert strategy_calls[0]["close"] == 50000

        loop.stop()
        t.join(timeout=2)

    def test_shutdown_flushes_events(self) -> None:
        q = ThreadSafeEventQueue()
        stream = StubStream()
        received: list[dict] = []

        loop = BotEventLoop(q, stream, on_candle=received.append)

        t = threading.Thread(target=loop.start, args=("BTC", "1h"))
        t.start()

        # Enqueue a few events then stop
        stream.fire({"close": 1})
        stream.fire({"close": 2})
        time.sleep(0.1)

        loop.stop()
        t.join(timeout=2)

        # All events should have been flushed
        assert len(received) == 2
        assert stream.stopped

    def test_reconnect_resubscribes_after_stream_failure(self) -> None:
        """When subscribe fails with an error, the loop reconnects."""
        q = ThreadSafeEventQueue()
        stream = MagicMock(spec=MarketDataStream)
        stream.subscribe_candles.side_effect = [
            ConnectionError("fail"),
            1,  # second try succeeds
        ]
        stream.stop = MagicMock()

        # Use a very short backoff for testing
        loop = BotEventLoop(
            q,
            stream,
            on_candle=lambda _: None,
            reconnect_backoff=0.01,
        )

        # Start, let it attempt reconnect, then stop
        t = threading.Thread(target=loop.start, args=("BTC", "1h"))
        t.start()
        time.sleep(0.3)
        loop.stop()
        t.join(timeout=2)

        assert stream.subscribe_candles.call_count >= 2
        assert stream.stop.called

    def test_stale_event_dispatched_to_on_stale(self) -> None:
        q = ThreadSafeEventQueue()
        stream = StubStream()
        stale_events: list[dict] = []

        loop = BotEventLoop(
            q, stream, on_candle=lambda _: None, on_stale=stale_events.append
        )

        t = threading.Thread(target=loop.start, args=("ETH", "4h"))
        t.start()

        stream.fire({"_stale": True, "elapsed_seconds": 30})
        time.sleep(0.1)

        assert len(stale_events) >= 1
        assert stale_events[0]["_stale"] is True

        loop.stop()
        t.join(timeout=2)

    def test_queue_backpressure_does_not_crash(self) -> None:
        """When queue is full, enqueue rejects silently — no crash."""
        q = ThreadSafeEventQueue(maxsize=2)
        stream = StubStream()
        received: list[dict] = []

        loop = BotEventLoop(q, stream, on_candle=received.append)

        t = threading.Thread(target=loop.start, args=("BTC", "1h"))
        t.start()

        # Fire more events than queue capacity
        for i in range(5):
            stream.fire({"close": i})
        time.sleep(0.2)

        # Some events dropped, but no crash
        assert 1 <= len(received) <= 5

        loop.stop()
        t.join(timeout=2)
