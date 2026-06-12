"""Result of a Volume Profile computation for one trading session.

A pure dataclass — no behavior, no ORM, no domain logic beyond data
holding. Used as a return value from volume profile computation.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class VolumeProfileResult:
    """Result of a Volume Profile computation for one session.

    Intentionally **not frozen** — the pandas-based volume profile math
    in ``core/domain/services/volume_profile.py`` mutates these fields
    during computation. All other domain entities are frozen.
    """

    poc: float
    """Point of Control — price level with the most volume."""

    vah: float
    """Value Area High — upper bound of 68% volume zone."""

    val: float
    """Value Area Low — lower bound of 68% volume zone."""

    total_volume: float
    """Total volume in the session."""

    value_area_volume: float
    """Volume within the Value Area."""

    bucket_size: float
    """Price increment per bucket."""

    num_buckets: int
    """Number of price buckets in the profile."""

    profile: dict[float, float] = field(default_factory=dict)
    """Price → volume mapping for the full profile."""
