"""DotEnvConfigWriter — persists runtime config to a .env file.

Updates ``FINBOT_<KEY>`` lines in-place or appends new ones. Used by the
``/config save`` command so runtime changes survive restarts.

Concurrency & atomicity (M7):
  * All read-modify-write work is serialised by a per-instance
    :class:`threading.Lock` so two concurrent ``/config save`` calls cannot
    lose each other's update.
  * The new content is written to ``<path>.env.tmp`` and swapped in with
    :func:`os.replace`, which is atomic on POSIX and Windows — a crash
    mid-write leaves the previous ``.env`` intact rather than truncated.
  * A value containing a newline is rejected (raises ``ValueError``) before
    any I/O, to prevent ``.env`` injection.
"""

from __future__ import annotations

import logging
import os
import threading
from pathlib import Path

logger = logging.getLogger(__name__)

# Short config key (Telegram-friendly) → .env variable name.
_ENV_KEY_MAP: dict[str, str] = {
    "max_position": "FINBOT_MAX_POSITION_USD",
    "daily_loss": "FINBOT_MAX_DAILY_LOSS_USD",
    "max_orders": "FINBOT_MAX_OPEN_ORDERS",
    "stale_data": "FINBOT_STALE_DATA_SECONDS",
}

# Suffix for the temporary file used by the atomic replace.
_TMP_SUFFIX = ".env.tmp"


class DotEnvConfigWriter:
    """Persist config changes to a ``.env`` file.

    Read-modify-write: existing ``FINBOT_<KEY>`` lines are replaced; new keys
    are appended. Missing file is created. I/O failures are logged and
    swallowed so a config-save never breaks the running bot; input-validation
    failures (e.g. a multi-line value) raise to the caller.
    """

    def __init__(self, env_path: str = ".env") -> None:
        self._path = Path(env_path)
        self._lock = threading.Lock()

    def write(self, key: str, value: str) -> None:
        """Update or append the matching FINBOT_ variable in the .env file.

        Raises
        ------
        ValueError
            If ``value`` contains a newline (``.env`` injection guard) or if
            ``key`` is empty.
        """
        env_var = _ENV_KEY_MAP.get(key)
        if env_var is None:
            logger.warning("Unknown config key %r — not persisted", key)
            return
        _validate_value(value)

        try:
            with self._lock:
                self._write_locked(env_var, value)
            logger.info("Persisted %s=%s to %s", env_var, value, self._path)
        except Exception:
            logger.exception("Failed to persist %s to %s", env_var, self._path)

    # -- internal -----------------------------------------------------------

    def _write_locked(self, env_var: str, value: str) -> None:
        """Read-modify-write under ``self._lock``, then atomic-replace.

        Holding the lock across the whole read-modify-write serialises
        concurrent ``write`` calls; the tmp+``os.replace`` makes the visible
        file swap atomic so a crash never leaves a truncated ``.env``.
        """
        lines = self._read_lines()
        _updated, lines = self._update_or_append(lines, env_var, value)
        content = "".join(lines)
        tmp_path = self._path.with_name(self._path.name + _TMP_SUFFIX)
        tmp_path.write_text(content, encoding="utf-8")
        os.replace(tmp_path, self._path)

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


def _validate_value(value: str) -> None:
    """Reject values that would corrupt the .env file format.

    A newline in the value would start a new line and could overwrite an
    unrelated variable (``.env`` injection). Raises ``ValueError`` before
    any I/O so the caller learns of the bad input.
    """
    if "\n" in value or "\r" in value:
        raise ValueError("Config value may not contain newlines (.env injection guard)")
