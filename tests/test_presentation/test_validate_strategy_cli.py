"""Tests for validate-strategy and strategy-compat CLI commands."""

import os
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "strategies"
CLI_ENTRY = PROJECT_ROOT / "finbot" / "presentation" / "cli" / "main.py"


def _run(*args: str) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    # Ensure finbot is importable from the subprocess
    pythonpath = str(PROJECT_ROOT)
    if "PYTHONPATH" in env:
        pythonpath = f"{pythonpath}{os.pathsep}{env['PYTHONPATH']}"
    env["PYTHONPATH"] = pythonpath
    return subprocess.run(
        [sys.executable, str(CLI_ENTRY), *args],
        capture_output=True,
        text=True,
        env=env,
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


# ---------------------------------------------------------------------------
# S3 — CLI mode/URL consistency guard (C4)
# ---------------------------------------------------------------------------


class TestCLIModeUrlGuard:
    """C4: the run command refuses mode/testnet mismatches via the shared helper."""

    def test_cli_run_testnet_mode_with_mainnet_url_exits_nonzero(self, monkeypatch):
        import os
        import subprocess
        import sys

        env = os.environ.copy()
        env["PYTHONPATH"] = str(PROJECT_ROOT)
        env["FINBOT_MODE"] = "testnet"
        env["FINBOT_HYPERLIQUID_TESTNET"] = "false"
        env["FINBOT_HYPERLIQUID_PRIVATE_KEY"] = "0x" + "ab" * 32
        proc = subprocess.run(
            [
                sys.executable,
                str(CLI_ENTRY),
                "run",
                "--strategy",
                str(FIXTURES_DIR / "amt_dip_buyer_final.yaml"),
                "--symbol",
                "BTC",
                "--interval",
                "1h",
            ],
            capture_output=True,
            text=True,
            env=env,
            timeout=20,
        )
        assert proc.returncode != 0, proc.stdout
        assert "TESTNET" in proc.stdout.upper() or "MISMATCH" in proc.stdout.upper()
