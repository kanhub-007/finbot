"""Run counts DTO — signal/order/fill counts for a bot run.

Returned by :meth:`BotStateRepository.get_run_counts` so list endpoints can
fetch counts for many runs without an N+1 query (one GROUP BY per table
instead of three fetchall-per-run).
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class RunCounts:
    """Per-run counts for a list endpoint."""

    signals: int = 0
    orders: int = 0
    fills: int = 0
