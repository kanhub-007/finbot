"""Tests for StrategyTimeframes value object and parse_timeframes domain service.

Scenario 1: Strategy declares timeframes — YAML loader exposes them.
Classical school: real domain objects, fakes at boundaries only.
"""

from finbot.core.domain.entities.strategy_timeframes import StrategyTimeframes
from finbot.core.domain.services.strategy_timeframe_parser import (
    parse_timeframes,
)
from finbot.infrastructure.strategy.yaml_strategy_definition_loader import (
    YamlStrategyDefinitionLoader,
)

# ---------------------------------------------------------------------------
# StrategyTimeframes value object tests
# ---------------------------------------------------------------------------


class TestStrategyTimeframesValueObject:
    def test_construction_with_all_fields(self) -> None:
        tf = StrategyTimeframes(
            primary="30min",
            informative_intervals=("1h",),
            informative_aliases={"h1": "1h"},
        )
        assert tf.primary == "30min"
        assert tf.informative_intervals == ("1h",)
        assert tf.informative_aliases == {"h1": "1h"}

    def test_construction_no_informative(self) -> None:
        tf = StrategyTimeframes(
            primary="30min",
            informative_intervals=(),
            informative_aliases={},
        )
        assert tf.primary == "30min"
        assert tf.informative_intervals == ()
        assert tf.informative_aliases == {}

    def test_is_mtf_returns_true_when_informative_present(self) -> None:
        tf = StrategyTimeframes(
            primary="30min",
            informative_intervals=("1h",),
            informative_aliases={"h1": "1h"},
        )
        assert tf.is_mtf is True

    def test_is_mtf_returns_false_when_no_informative(self) -> None:
        tf = StrategyTimeframes(
            primary="30min",
            informative_intervals=(),
            informative_aliases={},
        )
        assert tf.is_mtf is False

    def test_equality(self) -> None:
        a = StrategyTimeframes(
            primary="30min",
            informative_intervals=("1h",),
            informative_aliases={"h1": "1h"},
        )
        b = StrategyTimeframes(
            primary="30min",
            informative_intervals=("1h",),
            informative_aliases={"h1": "1h"},
        )
        assert a == b
        assert hash(a) == hash(b)

    def test_inequality_different_primary(self) -> None:
        a = StrategyTimeframes(
            primary="30min",
            informative_intervals=("1h",),
            informative_aliases={"h1": "1h"},
        )
        b = StrategyTimeframes(
            primary="1h",
            informative_intervals=("1h",),
            informative_aliases={"h1": "1h"},
        )
        assert a != b

    def test_immutable(self) -> None:
        tf = StrategyTimeframes(
            primary="30min",
            informative_intervals=("1h",),
            informative_aliases={"h1": "1h"},
        )
        try:
            tf.primary = "1h"  # type: ignore[misc]
            assert False, "Should have raised FrozenInstanceError"
        except Exception:
            pass


# ---------------------------------------------------------------------------
# parse_timeframes domain service tests
# ---------------------------------------------------------------------------


class TestParseTimeframes:
    def test_mtf_definition_returns_strategy_timeframes(self) -> None:
        """parse_timeframes extracts primary and informative from a
        StrategyDefinition with timeframes."""
        from finbar_strategy_runtime.domain.entities.informative_timeframe import (
            InformativeTimeframe,
        )
        from finbar_strategy_runtime.domain.entities.strategy_definition import (
            StrategyDefinition,
            TimeframeDeclaration,
        )

        definition = StrategyDefinition(
            name="test",
            sides={},
            timeframes=TimeframeDeclaration(
                primary="30min",
                informative=[
                    InformativeTimeframe(interval="1h", alias="h1"),
                ],
            ),
        )

        result = parse_timeframes(definition)
        assert result is not None
        assert result.primary == "30min"
        assert result.informative_intervals == ("1h",)
        assert result.informative_aliases == {"h1": "1h"}
        assert result.is_mtf is True

    def test_single_tf_definition_returns_none(self) -> None:
        """parse_timeframes returns None when definition has no
        timeframes block."""
        from finbar_strategy_runtime.domain.entities.strategy_definition import (
            StrategyDefinition,
        )

        definition = StrategyDefinition(name="test", sides={})
        result = parse_timeframes(definition)
        assert result is None

    def test_definition_with_timeframes_but_no_informative(self) -> None:
        """parse_timeframes still returns a StrategyTimeframes,
        but informative_intervals is empty."""
        from finbar_strategy_runtime.domain.entities.strategy_definition import (
            StrategyDefinition,
            TimeframeDeclaration,
        )

        definition = StrategyDefinition(
            name="test",
            sides={},
            timeframes=TimeframeDeclaration(primary="1h"),
        )

        result = parse_timeframes(definition)
        assert result is not None
        assert result.primary == "1h"
        assert result.informative_intervals == ()
        assert result.informative_aliases == {}
        assert result.is_mtf is False

    def test_none_definition_returns_none(self) -> None:
        """Safety: passing None returns None."""
        result = parse_timeframes(None)  # type: ignore[arg-type]
        assert result is None


# ---------------------------------------------------------------------------
# YamlStrategyDefinitionLoader.last_timeframes() tests
# ---------------------------------------------------------------------------


class TestLoaderLastTimeframes:
    def test_mtf_strategy_exposes_timeframes(self) -> None:
        """After loading the MTF strategy, last_timeframes() returns
        the correct primary and informative intervals."""
        loader = YamlStrategyDefinitionLoader()
        loader.load_from_file("strategies/14_amt_value_reject_30m_1h_mtf.yaml")
        tf = loader.last_timeframes()
        assert tf is not None
        assert tf.primary == "30min"
        assert tf.informative_intervals == ("1h",)
        assert tf.informative_aliases == {"h1": "1h"}

    def test_single_tf_strategy_returns_none(self) -> None:
        """After loading a strategy without a timeframes block,
        last_timeframes() returns None."""
        loader = YamlStrategyDefinitionLoader()
        loader.load_from_text(
            'schema_version: "2.0"\n'
            "name: no_tf_strategy\n"
            "indicators:\n"
            "  - name: my_atr\n"
            "    type: atr\n"
            "    timeframe: primary\n"
            "sides:\n"
            "  long:\n"
            "    entry:\n"
            "      condition:\n"
            '        operator: ">"\n'
            "        left: close\n"
            "        right: my_atr\n"
        )
        tf = loader.last_timeframes()
        assert tf is None

    def test_no_strategy_loaded_yet_returns_none(self) -> None:
        """Before any strategy is loaded, last_timeframes() returns None."""
        loader = YamlStrategyDefinitionLoader()
        assert loader.last_timeframes() is None


# ---------------------------------------------------------------------------
# Cross-asset tests (2026-06-24 spec)
# ---------------------------------------------------------------------------


class TestCrossAssetStrategyTimeframes:
    """Cross-asset extends MTF: each informative can declare a symbol."""

    def test_informative_with_explicit_symbol(self) -> None:
        """parse_timeframes reads the symbol field when present."""
        from finbar_strategy_runtime.domain.entities.informative_timeframe import (
            InformativeTimeframe,
        )
        from finbar_strategy_runtime.domain.entities.strategy_definition import (
            StrategyDefinition,
            TimeframeDeclaration,
        )

        # Simulate a package InformativeTimeframe with a symbol attr.
        item = InformativeTimeframe(interval="1h", alias="btc_1h")
        object.__setattr__(item, "symbol", "BTC")

        definition = StrategyDefinition(
            name="cross_asset",
            sides={},
            timeframes=TimeframeDeclaration(
                primary="30m",
                informative=[item],
            ),
        )

        result = parse_timeframes(definition)
        assert result is not None
        assert result.informative_aliases == {"btc_1h": "1h"}
        assert result.informative_symbols == {"btc_1h": "BTC"}
        assert result.effective_symbol("btc_1h", "ALT") == "BTC"

    def test_informative_without_symbol_defaults_to_none(self) -> None:
        """When no symbol is declared, informative_symbols stores None."""
        from finbar_strategy_runtime.domain.entities.informative_timeframe import (
            InformativeTimeframe,
        )
        from finbar_strategy_runtime.domain.entities.strategy_definition import (
            StrategyDefinition,
            TimeframeDeclaration,
        )

        item = InformativeTimeframe(interval="1h", alias="h1")
        definition = StrategyDefinition(
            name="same_symbol",
            sides={},
            timeframes=TimeframeDeclaration(
                primary="30m",
                informative=[item],
            ),
        )

        result = parse_timeframes(definition)
        assert result is not None
        assert result.informative_symbols == {"h1": None}
        # effective_symbol falls back to primary
        assert result.effective_symbol("h1", "ALT") == "ALT"

    def test_mixed_cross_asset_and_same_symbol(self) -> None:
        """Informatives with and without symbols coexist."""
        from finbar_strategy_runtime.domain.entities.informative_timeframe import (
            InformativeTimeframe,
        )
        from finbar_strategy_runtime.domain.entities.strategy_definition import (
            StrategyDefinition,
            TimeframeDeclaration,
        )

        h1 = InformativeTimeframe(interval="1h", alias="h1")
        btc = InformativeTimeframe(interval="1h", alias="btc_1h")
        object.__setattr__(btc, "symbol", "BTC")

        definition = StrategyDefinition(
            name="mixed",
            sides={},
            timeframes=TimeframeDeclaration(
                primary="30m",
                informative=[h1, btc],
            ),
        )

        result = parse_timeframes(definition)
        assert result is not None
        assert result.informative_aliases == {"h1": "1h", "btc_1h": "1h"}
        assert result.informative_symbols == {"h1": None, "btc_1h": "BTC"}

    def test_effective_symbol_on_unknown_alias_returns_primary(self) -> None:
        """effective_symbol on an alias not in the map returns primary."""
        tf = StrategyTimeframes(
            primary="30m",
            informative_intervals=("1h",),
            informative_aliases={"h1": "1h"},
        )
        assert tf.effective_symbol("unknown", "ALT") == "ALT"

    def test_strategy_timeframes_equality_with_symbols(self) -> None:
        """Two StrategyTimeframes with same symbols are equal."""
        a = StrategyTimeframes(
            primary="30m",
            informative_intervals=("1h",),
            informative_aliases={"h1": "1h"},
            informative_symbols={"h1": "BTC"},
        )
        b = StrategyTimeframes(
            primary="30m",
            informative_intervals=("1h",),
            informative_aliases={"h1": "1h"},
            informative_symbols={"h1": "BTC"},
        )
        assert a == b


class TestLoaderCrossAssetTimeframes:
    """YAML loader passes symbol through from raw content."""

    def test_parse_raw_yaml_with_symbol(self) -> None:
        """Loader.parse_timeframes() extracts symbol from raw YAML."""
        loader = YamlStrategyDefinitionLoader()
        result = loader.parse_timeframes(
            "timeframes:\n"
            "  primary: 30m\n"
            "  informative:\n"
            "    - alias: btc_1h\n"
            "      interval: 1h\n"
            "      symbol: BTC\n"
        )
        assert result is not None
        assert result.informative_aliases == {"btc_1h": "1h"}
        assert result.informative_symbols == {"btc_1h": "BTC"}

    def test_parse_raw_yaml_without_symbol(self) -> None:
        """Loader.parse_timeframes() stores None when symbol is absent."""
        loader = YamlStrategyDefinitionLoader()
        result = loader.parse_timeframes(
            "timeframes:\n"
            "  primary: 30m\n"
            "  informative:\n"
            "    - alias: h1\n"
            "      interval: 1h\n"
        )
        assert result is not None
        assert result.informative_aliases == {"h1": "1h"}
        assert result.informative_symbols == {"h1": None}
