"""RuntimeConfigService — mutable runtime risk limits + profiles + default size.

Owns the :class:`RuntimeBotConfig` (shared with risk gates), named config
profiles, and the default order size. All mutations go through validation
on :class:`RuntimeBotConfig`.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from finbot.core.domain.entities.runtime_bot_config import RuntimeBotConfig
from finbot.core.domain.interfaces.config_writer_port import ConfigWriterPort
from finbot.core.domain.services.bot_manager.bot_manager_lock import (
    BotManagerLock,
)
from finbot.core.domain.services.bot_manager.bot_manager_state import (
    BotManagerState,
)

# Short config key → .env variable name (mirrors DotEnvConfigWriter).
_SAVE_KEYS = (
    ("max_position", "max_position_usd"),
    ("daily_loss", "max_daily_loss_usd"),
    ("max_orders", "max_open_orders"),
    ("stale_data", "stale_data_seconds"),
)


class RuntimeConfigService:
    """Get/set/save runtime config, manage profiles, and default order size."""

    def __init__(
        self,
        state: BotManagerState,
        lock: BotManagerLock,
        config_writer: ConfigWriterPort | None,
    ) -> None:
        self._state = state
        self._lock = lock
        self._config_writer = config_writer

    def get_bot_config(self) -> RuntimeBotConfig:
        """Return the mutable runtime config (shared with risk gates)."""
        return self._state.runtime_config

    def update_bot_config(self, key: str, value: str) -> dict[str, str]:
        """Update a runtime config key by short name."""
        try:
            self._state.runtime_config.set(key, value)
        except KeyError:
            available = ", ".join(RuntimeBotConfig.AVAILABLE_KEYS)
            return {
                "status": "rejected",
                "message": f"Unknown setting. Available: {available}",
            }
        except ValueError as exc:
            return {"status": "rejected", "message": str(exc)}
        return {"status": "ok", "key": key, "value": value}

    def save_config_to_env(self) -> dict[str, str]:
        """Persist the current RuntimeBotConfig to durable storage."""
        if self._config_writer is None:
            return {
                "status": "rejected",
                "message": "Config persistence is not configured.",
            }
        snapshot = self._state.runtime_config.snapshot()
        for key, attr in _SAVE_KEYS:
            self._config_writer.write(key, str(getattr(snapshot, attr)))
        return {"status": "ok", "saved": len(_SAVE_KEYS)}

    def set_default_size(self, size: Decimal) -> dict[str, str]:
        """Set the default order size for /long /short without explicit size."""
        size_dec = Decimal(str(size))
        if size_dec <= 0:
            return {"status": "rejected", "message": "Size must be positive."}
        with self._lock:
            self._state.default_size = size_dec
        return {"status": "ok", "default_size": str(size_dec)}

    def get_default_size(self) -> Decimal | None:
        """Return the default order size, or None if unset."""
        with self._lock:
            return self._state.default_size

    def clear_default_size(self) -> None:
        """Clear the default order size."""
        with self._lock:
            self._state.default_size = None

    def save_config_profile(self, name: str) -> dict[str, Any]:
        """Snapshot the current RuntimeBotConfig under a profile name."""
        with self._lock:
            self._state.config_profiles[name] = self._state.runtime_config.snapshot()
        return {"status": "ok", "profile": name}

    def load_config_profile(self, name: str) -> dict[str, Any]:
        """Restore a named profile. Rejected if the profile is unknown."""
        with self._lock:
            snapshot = self._state.config_profiles.get(name)
            if snapshot is None:
                saved = ", ".join(sorted(self._state.config_profiles)) or "none"
                return {
                    "status": "rejected",
                    "message": f"Unknown profile '{name}'. Saved: {saved}",
                }
        for key, attr in _SAVE_KEYS:
            self._state.runtime_config.set(key, str(getattr(snapshot, attr)))
        return {"status": "ok", "profile": name}

    def list_config_profiles(self) -> dict[str, Any]:
        """Return the saved profile names."""
        with self._lock:
            names = sorted(self._state.config_profiles.keys())
        return {"status": "ok", "profiles": names}
