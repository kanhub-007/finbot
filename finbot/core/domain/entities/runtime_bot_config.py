"""RuntimeBotConfig — mutable, thread-safe runtime risk limits.

Distinct from the frozen :class:`BotConfig` (validated run config). This is the
live, adjustable config that /config mutates and both strategy gates and manual
gates read. Changes affect only NEW orders.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation


@dataclass
class _ConfigData:
    """Plain holder so the outer class can swap instances atomically."""

    max_position_usd: Decimal = Decimal("100")
    max_daily_loss_usd: Decimal = Decimal("25")
    max_open_orders: int = 3
    stale_data_seconds: int = 120


# Short key (Telegram-friendly) → (attribute, parser, validator)
_KEY_MAP: dict[str, tuple[str, object]] = {
    "max_position": ("max_position_usd", Decimal),
    "daily_loss": ("max_daily_loss_usd", Decimal),
    "max_orders": ("max_open_orders", int),
    "stale_data": ("stale_data_seconds", int),
}


class RuntimeBotConfig:
    """Thread-safe mutable runtime configuration.

    Reads return plain values; writes validate and swap the internal data
    atomically. Both strategy gates and manual gates hold a reference to one
    instance so /config changes are visible everywhere immediately.
    """

    AVAILABLE_KEYS = tuple(_KEY_MAP.keys())

    def __init__(self, data: _ConfigData | None = None) -> None:
        self._data = data or _ConfigData()
        self._lock = threading.Lock()

    # -- read accessors ----------------------------------------------------

    @property
    def max_position_usd(self) -> Decimal:
        with self._lock:
            return self._data.max_position_usd

    @property
    def max_daily_loss_usd(self) -> Decimal:
        with self._lock:
            return self._data.max_daily_loss_usd

    @property
    def max_open_orders(self) -> int:
        with self._lock:
            return self._data.max_open_orders

    @property
    def stale_data_seconds(self) -> int:
        with self._lock:
            return self._data.stale_data_seconds

    def snapshot(self) -> _ConfigData:
        """Return a copy of the current values."""
        with self._lock:
            return _ConfigData(
                max_position_usd=self._data.max_position_usd,
                max_daily_loss_usd=self._data.max_daily_loss_usd,
                max_open_orders=self._data.max_open_orders,
                stale_data_seconds=self._data.stale_data_seconds,
            )

    # -- mutation ----------------------------------------------------------

    def set(self, key: str, value: str) -> None:
        """Set a config value by short key.

        Raises KeyError if the key is unknown, ValueError if the value is
        invalid (non-numeric, negative, etc.).
        """
        if key not in _KEY_MAP:
            raise KeyError(key)
        attr, parser = _KEY_MAP[key]
        try:
            parsed = parser(value)
        except (InvalidOperation, ValueError) as exc:
            raise ValueError(f"{key} must be a number") from exc

        if isinstance(parsed, (Decimal, int)) and parsed < 0:
            raise ValueError(f"{key} must be non-negative")

        with self._lock:
            setattr(self._data, attr, parsed)
