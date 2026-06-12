"""Content hash helpers for indicator artifact reuse."""

import hashlib
import json


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
