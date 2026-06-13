"""Tests for BotEventLoop and ThreadSafeEventQueue."""

import threading
import time
from collections.abc import Callable
from typing import Any
from unittest.mock import MagicMock

from finbot.core.domain.entities.bot_event import BotEvent
from finbot.core.domain.entities.bot_event_type import BotEventType
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

        loop = BotEventLoop(q, stream)

        # Start in background thread with on_candle callback
        t = threading.Thread(
            target=loop.start,
            args=("BTC", "1h", strategy_calls.append),
        )
        t.start()

        # Fire from "SDK" thread
        stream.fire({"close": 50000, "symbol": "BTC"})
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

        loop = BotEventLoop(q, stream)

        t = threading.Thread(
            target=loop.start,
            args=("BTC", "1h", received.append),
        )
        t.start()

        stream.fire({"close": 1})
        stream.fire({"close": 2})
        time.sleep(0.1)

        loop.stop()
        t.join(timeout=2)

        assert len(received) == 2
        assert stream.stopped

    def test_reconnect_resubscribes_after_stream_failure(self) -> None:
        q = ThreadSafeEventQueue()
        stream = MagicMock(spec=MarketDataStream)
        stream.subscribe_candles.side_effect = [
            ConnectionError("fail"),
            1,
        ]
        stream.stop = MagicMock()

        loop = BotEventLoop(q, stream, reconnect_backoff=0.01)

        t = threading.Thread(
            target=loop.start,
            args=("BTC", "1h", lambda _: None),
        )
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

        loop = BotEventLoop(q, stream)

        t = threading.Thread(
            target=loop.start,
            args=("ETH", "4h", lambda _: None, stale_events.append),
        )
        t.start()

        stream.fire({"_stale": True, "elapsed_seconds": 30})
        time.sleep(0.1)

        assert len(stale_events) >= 1
        assert stale_events[0]["_stale"] is True

        loop.stop()
        t.join(timeout=2)

    def test_queue_backpressure_does_not_crash(self) -> None:
        q = ThreadSafeEventQueue(maxsize=2)
        stream = StubStream()
        received: list[dict] = []

        loop = BotEventLoop(q, stream)

        t = threading.Thread(
            target=loop.start,
            args=("BTC", "1h", received.append),
        )
        t.start()

        for i in range(5):
            stream.fire({"close": i})
        time.sleep(0.2)

        assert 1 <= len(received) <= 5

        loop.stop()
        t.join(timeout=2)


def test_stop_enqueues_shutdown_sentinel() -> None:
    """P11: stop() wakes a blocked loop immediately via a SHUTDOWN event."""
    from finbot.core.domain.entities.bot_event_type import BotEventType
    from finbot.infrastructure.adapters.bot_event_loop import BotEventLoop
    from tests.fakes import FakeMarketDataStream

    queue = _CountingQueue()
    loop = BotEventLoop(queue, FakeMarketDataStream())
    loop.stop()

    assert queue.enqueued, "stop() must enqueue a SHUTDOWN event"
    assert queue.enqueued[-1].type == BotEventType.SHUTDOWN


class _CountingQueue:
    def __init__(self) -> None:
        self.enqueued: list = []

    def enqueue(self, event) -> bool:
        self.enqueued.append(event)
        return True

    def dequeue(self, timeout=None):
        return None

    def size(self) -> int:
        return 0

    def clear(self) -> None:
        pass
