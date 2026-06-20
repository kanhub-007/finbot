"""StrategyLogWriter — writes per-candle strategy evaluation logs to disk.

One JSON-lines file per strategy+symbol combo (e.g.
``logs/macd_cross__BTC.jsonl``).  The ``__`` separator avoids ambiguity
with strategy names that contain underscores. Each line is a JSON object.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from typing import Any

_LOG_SEP = "__"  # separates strategy slug from symbol in filenames


class StrategyLogWriter:
    """Append-only JSON-lines logger for strategy evaluation decisions."""

    def __init__(self, log_dir: str = "logs") -> None:
        self._log_dir = log_dir

    @staticmethod
    def file_name(strategy_file: str, symbol: str) -> str:
        """Return the log filename (stem) for a strategy+symbol pair."""
        return f"{_slug(strategy_file)}{_LOG_SEP}{symbol.replace(':','_')}"

    def log_candle(
        self,
        *,
        strategy_file: str,
        symbol: str,
        interval: str,
        timestamp: int,
        candle: dict[str, Any] | None = None,
        indicators: dict[str, Any] | None = None,
        validation: dict[str, Any] | None = None,
        signal: dict[str, Any] | None = None,
        risk: dict[str, Any] | None = None,
        intent: dict[str, Any] | None = None,
    ) -> None:
        """Write one evaluation log entry."""
        entry: dict[str, Any] = {
            "ts": timestamp,
            "time": datetime.now(UTC).isoformat(),
            "strategy": _slug(strategy_file),
            "symbol": symbol,
            "interval": interval,
        }
        if candle:
            entry["candle"] = {
                k: candle[k]
                for k in ("open", "high", "low", "close", "volume")
                if k in candle
            }
        if indicators:
            entry["indicators"] = indicators
        if validation:
            entry["validation"] = validation
        if signal:
            entry["signal"] = signal
        if risk is not None:
            entry["risk"] = risk
        if intent:
            entry["intent"] = intent

        name = StrategyLogWriter.file_name(strategy_file, symbol) + ".jsonl"
        path = os.path.join(self._log_dir, name)
        _ensure_dir(path)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, default=str) + "\n")


class StrategyLogFileReader:
    """Read strategy evaluation logs from the filesystem."""

    def __init__(self, log_dir: str = "logs") -> None:
        self._log_dir = log_dir

    def list_logs(self) -> list[str]:
        """Return sorted list of ``strategy__symbol`` names with existing logs."""
        if not os.path.isdir(self._log_dir):
            return []
        return sorted(
            os.path.splitext(f.name)[0]
            for f in os.scandir(self._log_dir)
            if f.name.endswith(".jsonl")
        )

    def read_tail(
        self,
        strategy_file: str,
        symbol: str,
        n: int = 20,
    ) -> list[dict[str, Any]]:
        """Return the last *n* log entries for a strategy+symbol pair."""
        name = StrategyLogWriter.file_name(strategy_file, symbol) + ".jsonl"
        path = os.path.join(self._log_dir, name)
        if not os.path.exists(path):
            return []
        with open(path, encoding="utf-8") as f:
            lines = f.readlines()
        entries: list[dict[str, Any]] = []
        for line in lines[-n:]:
            line = line.strip()
            if line:
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
        return entries

    @staticmethod
    def parse_log_name(name: str) -> tuple[str, str]:
        """Split ``strategy__symbol`` back into (strategy_file, symbol)."""
        if _LOG_SEP in name:
            strategy_slug, symbol = name.split(_LOG_SEP, 1)
            return strategy_slug, symbol.replace("_", ":")
        return name, "?"


def _slug(filename: str) -> str:
    """Normalise a strategy filename to a valid filesystem slug."""
    name = filename.replace("\\", "/").split("/")[-1]
    name = name.removesuffix(".yaml").removesuffix(".yml").removesuffix(".json")
    return name.replace(" ", "_")


def _ensure_dir(filepath: str) -> None:
    d = os.path.dirname(filepath)
    if d:
        os.makedirs(d, exist_ok=True)
