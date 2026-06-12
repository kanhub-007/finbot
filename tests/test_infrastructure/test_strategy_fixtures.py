"""Tests for strategy fixture files."""

import json
from pathlib import Path

import yaml

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "strategies"
STRATEGY_FILES = ["amt_dip_buyer_final.yaml", "amt_v2_vol_filter.yaml"]
EXPECTED_NAMES = ["amt_dip_buyer_final", "amt_v2_vol_filter"]


class TestStrategyFixturesExist:
    @staticmethod
    def _fixture_path(filename: str) -> Path:
        return FIXTURES_DIR / filename

    def test_target_strategy_files_exist(self) -> None:
        for filename in STRATEGY_FILES:
            path = self._fixture_path(filename)
            assert path.is_file(), f"Missing fixture: {path}"

    def test_target_strategy_files_are_valid_yaml(self) -> None:
        for filename in STRATEGY_FILES:
            path = self._fixture_path(filename)
            with open(path) as fh:
                data = yaml.safe_load(fh)
            assert isinstance(data, dict), f"{filename} did not parse as a YAML dict"

    def test_target_strategy_names_match_expected(self) -> None:
        actual_names = []
        for filename in STRATEGY_FILES:
            path = self._fixture_path(filename)
            with open(path) as fh:
                data = yaml.safe_load(fh)
            actual_names.append(data.get("name"))

        assert (
            actual_names == EXPECTED_NAMES
        ), f"Strategy names {actual_names} != expected {EXPECTED_NAMES}"


class TestStrategyRequirementsDocumented:
    def test_requirements_file_exists(self) -> None:
        path = FIXTURES_DIR / "strategy_requirements.json"
        assert path.is_file(), "Missing strategy_requirements.json"

    def test_requirements_file_is_valid_json(self) -> None:
        path = FIXTURES_DIR / "strategy_requirements.json"
        with open(path) as fh:
            data = json.load(fh)
        assert (
            "strategies" in data
        ), "strategy_requirements.json missing 'strategies' key"

    def test_requirements_covers_target_strategies(self) -> None:
        path = FIXTURES_DIR / "strategy_requirements.json"
        with open(path) as fh:
            data = json.load(fh)
        doc_names = set(data["strategies"].keys())
        assert doc_names == set(
            EXPECTED_NAMES
        ), f"Requirements covers {doc_names}, expected {set(EXPECTED_NAMES)}"

    def test_requirements_include_required_fields(self) -> None:
        required_fields = {
            "name",
            "schema_version",
            "primary_timeframe",
            "sides",
            "indicators",
            "operators",
            "condition_groups",
            "risk_types",
        }
        path = FIXTURES_DIR / "strategy_requirements.json"
        with open(path) as fh:
            data = json.load(fh)
        for strategy_name, req in data["strategies"].items():
            missing = required_fields - set(req.keys())
            assert (
                not missing
            ), f"{strategy_name} requirements missing fields: {missing}"
