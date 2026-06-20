"""Tests for InformativeBarCache and runtime merge logic (Scenario 6).

Classical school: real domain objects, fakes at boundaries only.
"""

from finbot.infrastructure.adapters.informative_bar_cache import (
    InformativeBarCache,
)


class TestInformativeBarCache:
    def test_empty_cache_has_no_bars(self) -> None:
        cache = InformativeBarCache()
        assert cache.is_empty("h1") is True
        assert cache.get("h1") is None

    def test_update_and_get(self) -> None:
        cache = InformativeBarCache()
        bar = {"close": 50000, "high": 51000, "low": 49000, "open": 50500}
        cache.update("h1", bar)
        assert cache.is_empty("h1") is False
        result = cache.get("h1")
        assert result is not None
        assert result["close"] == 50000

    def test_update_overwrites_previous(self) -> None:
        cache = InformativeBarCache()
        cache.update("h1", {"close": 50000})
        cache.update("h1", {"close": 52000})
        assert cache.get("h1")["close"] == 52000

    def test_multiple_aliases_independent(self) -> None:
        cache = InformativeBarCache()
        cache.update("h1", {"close": 50000})
        cache.update("h4", {"close": 51000})
        assert cache.get("h1")["close"] == 50000
        assert cache.get("h4")["close"] == 51000

    def test_merge_into_adds_prefixed_keys(self) -> None:
        cache = InformativeBarCache()
        cache.update("h1", {"close": 50000, "high": 51000})
        primary = {"close": 49500, "open": 49400}

        merged = cache.merge_into(primary, alias="h1")

        # Original primary keys preserved
        assert merged["close"] == 49500
        assert merged["open"] == 49400
        # Informative keys added with alias prefix
        assert merged["h1_close"] == 50000
        assert merged["h1_high"] == 51000

    def test_merge_into_empty_cache_adds_nothing(self) -> None:
        cache = InformativeBarCache()
        primary = {"close": 49500}
        merged = cache.merge_into(primary, alias="h1")
        assert merged == {"close": 49500}

    def test_merge_all_aliases(self) -> None:
        cache = InformativeBarCache()
        cache.update("h1", {"close": 50000})
        cache.update("h4", {"close": 52000})
        primary = {"close": 49500}

        merged = cache.merge_all(primary, aliases=["h1", "h4"])

        assert merged["close"] == 49500
        assert merged["h1_close"] == 50000
        assert merged["h4_close"] == 52000

    def test_merge_does_not_mutate_original(self) -> None:
        cache = InformativeBarCache()
        cache.update("h1", {"close": 50000})
        primary = {"close": 49500}
        merged = cache.merge_into(primary, alias="h1")

        # Original dict unchanged
        assert "h1_close" not in primary
        assert primary["close"] == 49500
        # Merged copy has the extra keys
        assert merged["h1_close"] == 50000
