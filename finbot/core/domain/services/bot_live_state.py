"""Thread-safe container for live bot state.

The runtime thread writes to this container on each candle/signal/order
event. The MCP status thread reads from it.  A single lock protects the
entire struct — status reads are infrequent so contention is negligible.

This is a plain class, NOT a dataclass — it holds mutable state and a
threading.Lock, so value-equality semantics would be misleading.
"""

import threading


class BotLiveState:
    """Thread-safe mutable container shared by runtime + MCP threads."""

    def __init__(self) -> None:
        self.running: bool = False
        self.bot_run_id: str = ""
        self.strategy_name: str = ""
        self.symbol: str = ""
        self.interval: str = ""
        self.mode: str = ""
        self.uptime_start: float = 0.0
        self.current_candle_timestamp: int = 0
        self.last_signal_action: str = ""
        self.last_signal_timestamp: str = ""
        self.last_order_status: str = ""
        self.warmup_ready: bool = False
        self.open_position_size: float = 0.0
        self.position_direction: str = "flat"
        self.open_order_count: int = 0
        self.total_signals: int = 0
        self.total_orders: int = 0
        self.total_fills: int = 0
        self._lock: threading.Lock = threading.Lock()

    def update(self, **kwargs: object) -> None:
        """Thread-safe batch update of one or more fields.

        Unknown field names are silently ignored.
        """
        with self._lock:
            for key, value in kwargs.items():
                if hasattr(self, key) and not key.startswith("_"):
                    setattr(self, key, value)

    def snapshot(self) -> dict[str, object]:
        """Return a thread-safe copy of all public fields as a dict."""
        with self._lock:
            return {
                k: v
                for k, v in self.__dict__.items()
                if not k.startswith("_")
            }
