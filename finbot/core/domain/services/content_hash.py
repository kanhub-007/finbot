"""Content hash helpers for indicator artifact reuse and strategy fingerprinting."""

import hashlib
import json

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


def compute_artifact_hash(
    symbol: str,
    source: str,
    interval: str,
    indicators: list[str],
    timeframe_alias: str,
    start_date: str | None,
    end_date: str | None,
) -> str:
    """Return a stable hash for indicator job inputs so artifacts can be reused."""
    data = json.dumps(
        {
            "symbol": symbol.upper(),
            "source": source,
            "interval": interval,
            "indicators": sorted(indicators),
            "timeframe_alias": timeframe_alias,
            "start_date": start_date,
            "end_date": end_date,
        },
        sort_keys=True,
    )
    return hashlib.sha256(data.encode()).hexdigest()
