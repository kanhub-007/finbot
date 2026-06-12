"""Tests for validate-strategy and strategy-compat CLI commands."""

import subprocess
import sys
from pathlib import Path

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "strategies"
CLI_ENTRY = (
    Path(__file__).resolve().parent.parent.parent
    / "finbot"
    / "presentation"
    / "cli"
    / "main.py"
)


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(CLI_ENTRY), *args],
        capture_output=True,
        text=True,
    )


class TestValidateStrategyCLI:
    def test_cli_validate_strategy_success_exit_code_zero(self) -> None:
        proc = _run(
            "validate-strategy",
            "--strategy",
            str(FIXTURES_DIR / "amt_dip_buyer_final.yaml"),
        )
        assert proc.returncode == 0, proc.stderr
        assert "VALID" in proc.stdout

    def test_cli_validate_strategy_failure_exit_code_nonzero(self) -> None:
        proc = _run(
            "validate-strategy",
            "--strategy",
            str(FIXTURES_DIR / "invalid_missing_name.yaml"),
        )
        assert proc.returncode != 0, proc.stdout

    def test_cli_strategy_compat_outputs_json(self) -> None:
        proc = _run(
            "strategy-compat",
            "--strategy",
            str(FIXTURES_DIR / "amt_dip_buyer_final.yaml"),
        )
        assert proc.returncode == 0, proc.stderr
        assert '"strategy"' in proc.stdout
        assert '"modes"' in proc.stdout
