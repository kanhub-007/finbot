# Domain Model — Cross-Asset Strategy Support

## Changed Entities

### StrategyTimeframes (modified)
| Field | Type | Change |
|-------|------|--------|
| `primary` | `str \| None` | Unchanged |
| `informative_intervals` | `tuple[str, ...]` | Unchanged |
| `informative_aliases` | `dict[str, str]` | Unchanged: alias → interval |
| `informative_symbols` | `dict[str, str \| None]` | **New**: alias → symbol (None = use primary) |

```python
@dataclass(frozen=True, unsafe_hash=True)
class StrategyTimeframes:
    primary: str | None
    informative_intervals: tuple[str, ...]
    informative_aliases: dict[str, str] = field(hash=False, compare=True)
    informative_symbols: dict[str, str | None] = field(hash=False, compare=True)

    @property
    def is_mtf(self) -> bool:
        return len(self.informative_intervals) > 0

    def effective_symbol(self, alias: str, primary_symbol: str) -> str:
        """Resolve the actual symbol for an informative alias."""
        return self.informative_symbols.get(alias) or primary_symbol
```

### StrategyTimeframeParser (modified)
Parses the optional `symbol` field from each informative entry in the YAML
`timeframes` block. When absent, stores `None` (caller resolves to primary).

## Changed Interfaces

### BotLoop.start() (modified)
Adds optional `informative_symbols: list[str] | None` parameter so the loop
knows which symbol to subscribe per informative stream. Same length as
`informative_streams` and `informative_aliases`; `None` entries mean
"use primary symbol".

### MarketDataStream (unchanged)
Already accepts `(symbol, interval)` independently. No interface change needed.

## Unchanged
- `CausalStreamingEnricher` — bars arrive per alias, symbol-agnostic
- `BarEnricher` — same
- `LiveTradingRuntimeUseCase.process_informative_candle()` — already receives `(alias, bar)`
- `WarmupWindow` — per-alias windows work identically
- All risk gates, order planner, submission strategy
