"""Strategy file hashing — filesystem I/O for strategy fingerprinting.

Moved from ``core/domain/services/content_hash.py`` because the domain layer
must not perform filesystem I/O.  The pure ``compute_artifact_hash`` remains
in the domain.
"""

from __future__ import annotations

import hashlib

from finbot.core.domain.entities.strategy_load_error import StrategyLoadError


def hash_strategy_file(path: str) -> str:
    """Return a hex digest of the strategy file contents (first 16 chars).

    Single canonical implementation used by both the runtime factory and
    the service factory to avoid duplicate hashing logic that could drift.
    """
    try:
        with open(path, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()[:16]
    except OSError as e:
        raise StrategyLoadError(f"Cannot read strategy file for hashing: {e}") from e
