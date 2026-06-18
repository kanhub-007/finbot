"""DotEnvConfigWriter — persists runtime config to a .env file.

Updates ``FINBOT_<KEY>`` lines in-place or appends new ones. Used by the
``/config save`` command so runtime changes survive restarts.
"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# Short config key (Telegram-friendly) → .env variable name.
_ENV_KEY_MAP: dict[str, str] = {
    "max_position": "FINBOT_MAX_POSITION_USD",
    "daily_loss": "FINBOT_MAX_DAILY_LOSS_USD",
    "max_orders": "FINBOT_MAX_OPEN_ORDERS",
    "stale_data": "FINBOT_STALE_DATA_SECONDS",
}


class DotEnvConfigWriter:
    """Persist config changes to a ``.env`` file.

    Read-modify-write: existing ``FINBOT_<KEY>`` lines are replaced; new keys
    are appended. Missing file is created. Failures are logged and swallowed
    so a config-save never breaks the running bot.
    """

    def __init__(self, env_path: str = ".env") -> None:
        self._path = Path(env_path)

    def write(self, key: str, value: str) -> None:
        """Update or append the matching FINBOT_ variable in the .env file."""
        env_var = _ENV_KEY_MAP.get(key)
        if env_var is None:
            logger.warning("Unknown config key %r — not persisted", key)
            return

        try:
            lines = self._read_lines()
            updated, lines = self._update_or_append(lines, env_var, value)
            self._path.write_text(
                "".join(lines), encoding="utf-8"
            )
            logger.info("Persisted %s=%s to %s", env_var, value, self._path)
        except Exception:
            logger.exception("Failed to persist %s to %s", env_var, self._path)

    def _read_lines(self) -> list[str]:
        """Read .env lines, returning [] if the file doesn't exist."""
        if not self._path.exists():
            return []
        return self._path.read_text(encoding="utf-8").splitlines(keepends=True)

    @staticmethod
    def _update_or_append(
        lines: list[str], env_var: str, value: str
    ) -> tuple[bool, list[str]]:
        """Replace the first matching line or append a new one.

        Returns (updated_existing, new_lines).
        """
        prefix = f"{env_var}="
        for i, line in enumerate(lines):
            if line.startswith(prefix):
                lines[i] = f"{env_var}={value}\n"
                return True, lines
        # Not found — append
        need_newline = lines and not lines[-1].endswith("\n")
        if need_newline:
            lines[-1] = lines[-1] + "\n"
        lines.append(f"{env_var}={value}\n")
        return False, lines
