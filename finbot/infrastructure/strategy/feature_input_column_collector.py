"""FeatureInputColumnCollector — collect columns needed to calculate features."""

from finbot.core.domain.entities.feature_spec import FeatureSpec

_OHLC_COLUMNS = ("open", "high", "low", "close")
_RANGE_COLUMNS = ("high", "low", "close")
_SOURCE_FEATURE_TYPES = {
    "rolling_max",
    "rolling_min",
    "rolling_mean",
    "rolling_std",
    "shift",
}


class FeatureInputColumnCollector:
    """Collect input bar columns required before feature calculation."""

    def collect(self, features: list[FeatureSpec]) -> list[str]:
        """Return source columns required to calculate the supplied features."""
        columns: list[str] = []
        for feature in features:
            for column in _feature_inputs(feature):
                if column not in columns:
                    columns.append(column)
        return columns


def _feature_inputs(feature: FeatureSpec) -> tuple[str, ...]:
    if feature.type in _SOURCE_FEATURE_TYPES:
        return (feature.source,)
    if feature.type in ("body_pct", "ohlc4"):
        return _OHLC_COLUMNS
    if feature.type in ("range_pct", "typical_price"):
        return _RANGE_COLUMNS
    return ()
