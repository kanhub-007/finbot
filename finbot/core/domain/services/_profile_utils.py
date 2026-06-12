"""Shared profile utilities — value area expansion algorithm.

Extracted from Volume Profile and Market Profile modules to eliminate
duplication. The expansion algorithm greedily extends outward from the
POC bucket until 68% of the total distribution is captured.
"""

from __future__ import annotations

import numpy as np


def expand_value_area(
    profile: np.ndarray,
    poc_idx: int,
    total: float,
    target_fraction: float = 0.68,
) -> tuple[int, int, float]:
    """Expand outward from POC until ``target_fraction`` of total is captured.

    Greedily picks the side (below or above POC) with the larger value
    at each step, maintaining the shape of the distribution.

    Args:
        profile: 1-D array of values per price bucket (volume or TPO count).
        poc_idx: Index of the Point of Control bucket.
        total: Total sum of all values in the profile.
        target_fraction: Fraction of total to capture (default 0.68).

    Returns:
        Tuple of (lower_idx, upper_idx, accumulated) — the inclusive
        bucket indices of the value area and the accumulated value.
    """
    target = total * target_fraction
    accumulated = profile[poc_idx]
    lower_idx = poc_idx
    upper_idx = poc_idx
    num_buckets = len(profile)

    while accumulated < target and (lower_idx > 0 or upper_idx < num_buckets - 1):
        val_below = profile[lower_idx - 1] if lower_idx > 0 else -1.0
        val_above = profile[upper_idx + 1] if upper_idx < num_buckets - 1 else -1.0

        if val_below > val_above:
            lower_idx -= 1
            accumulated += profile[lower_idx]
        elif val_above >= val_below and upper_idx < num_buckets - 1:
            upper_idx += 1
            accumulated += profile[upper_idx]
        elif lower_idx > 0:
            lower_idx -= 1
            accumulated += profile[lower_idx]
        else:
            break

    return lower_idx, upper_idx, float(accumulated)
