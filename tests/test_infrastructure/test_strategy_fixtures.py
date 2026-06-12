"""Tests for strategy fixture files."""

import json
from pathlib import Path

import pytest
import yaml

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "strategies"
STRATEGY_FILES = ["amt_dip_buyer_final.yaml", "amt_v2_vol_filter.yaml"]
EXPECTED_NAMES = ["amt_dip_buyer_final", "amt_v2_vol_filter"]


@pytest.fixture(scope="module")
def parsed_strategies() -> dict[str, dict]:
    """Load and cache both strategy YAML files once per test module."""
    strategies: dict[str, dict] = {}
    for filename in STRATEGY_FILES:
        with open(FIXTURES_DIR / filename) as fh:
            strategies[filename] = yaml.safe_load(fh)
    return strategies


@pytest.fixture(scope="module")
def requirements() -> dict:
    """Load the strategy requirements JSON once per test module."""
    with open(FIXTURES_DIR / "strategy_requirements.json") as fh:
        return json.load(fh)


class TestStrategyFixturesExist:
    @pytest.mark.parametrize("filename", STRATEGY_FILES)
    def test_target_strategy_files_exist(self, filename: str) -> None:
        path = FIXTURES_DIR / filename
        assert path.is_file(), f"Missing fixture: {path}"

    def test_target_strategy_files_are_valid_yaml(
        self, parsed_strategies: dict[str, dict]
    ) -> None:
        for filename in STRATEGY_FILES:
            data = parsed_strategies[filename]
            assert isinstance(data, dict), f"{filename} did not parse as a YAML dict"

    def test_target_strategy_names_match_expected(
        self, parsed_strategies: dict[str, dict]
    ) -> None:
        actual_names = [
            parsed_strategies[filename].get("name") for filename in STRATEGY_FILES
        ]
        assert (
            actual_names == EXPECTED_NAMES
        ), f"Strategy names {actual_names} != expected {EXPECTED_NAMES}"

    def test_fixture_indicators_match_requirements(
        self,
        parsed_strategies: dict[str, dict],
        requirements: dict,
    ) -> None:
        """Each YAML fixture's indicator list must match the requirements doc."""
        for filename in STRATEGY_FILES:
            yaml_indicators = sorted(
                ind["type"] for ind in parsed_strategies[filename].get("indicators", [])
            )
            name = parsed_strategies[filename]["name"]
            req_indicators = sorted(requirements["strategies"][name]["indicators"])
            assert yaml_indicators == req_indicators, (
                f"{filename} indicators {yaml_indicators} "
                f"!= requirements {req_indicators}"
            )


class TestStrategyRequirementsDocumented:
    def test_requirements_file_exists(self) -> None:
        path = FIXTURES_DIR / "strategy_requirements.json"
        assert path.is_file(), "Missing strategy_requirements.json"

    def test_requirements_file_is_valid_json(self, requirements: dict) -> None:
        assert (
            "strategies" in requirements
        ), "strategy_requirements.json missing 'strategies' key"

    def test_requirements_covers_target_strategies(self, requirements: dict) -> None:
        doc_names = set(requirements["strategies"].keys())
        assert doc_names == set(
            EXPECTED_NAMES
        ), f"Requirements covers {doc_names}, expected {set(EXPECTED_NAMES)}"

    def test_requirements_include_required_fields(self, requirements: dict) -> None:
        required_fields = {
            "name",
            "schema_version",
            "primary_timeframe",
            "sides",
            "indicators",
            "operators",
            "condition_groups",
            "risk_types",
            "parameters",
        }
        for strategy_name, req in requirements["strategies"].items():
            missing = required_fields - set(req.keys())
            assert (
                not missing
            ), f"{strategy_name} requirements missing fields: {missing}"
