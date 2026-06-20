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
