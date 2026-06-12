"""CSV bar loader — implements BarLoader interface."""

import csv
import io
from pathlib import Path

from finbot.core.domain.interfaces.bar_loader import BarLoader


class CsvBarLoader(BarLoader):
    """Load OHLCV bars from CSV files or text."""

    def load_bars(self, csv_text: str) -> list[dict]:
        reader = csv.DictReader(io.StringIO(csv_text))
        bars = []
        for row in reader:
            bar: dict = {}
            for key, val in row.items():
                bar[key] = _coerce_value(val)
            bars.append(bar)
        bars.sort(key=lambda b: str(b.get("timestamp", "")))
        return bars

    def load_bars_from_file(self, path: str) -> list[dict]:
        content = Path(path).read_text(encoding="utf-8")
        return self.load_bars(content)


def _coerce_value(val: str):
    """Coerce CSV string values to int/float/bool when possible."""
    stripped = val.strip()
    if stripped.lower() in ("true", "false"):
        return stripped.lower() == "true"
    try:
        return int(stripped)
    except ValueError:
        pass
    try:
        return float(stripped)
    except ValueError:
        pass
    return stripped
