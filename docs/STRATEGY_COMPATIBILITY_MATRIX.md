# Strategy Compatibility Matrix

This matrix tracks Finbot support for Finbar strategy features.

| Feature | Parsed | Validated | Replay | Live Dry-run | Testnet | Live | Notes |
|---|---:|---:|---:|---:|---:|---:|---|
| schema_version | planned | planned | n/a | n/a | n/a | n/a | Required for validation |
| name/description | planned | planned | planned | planned | planned | planned | Used for audit/signals |
| parameters/defaults | planned | planned | planned | planned | planned | planned | Needed for risk refs |
| primary timeframe | planned | planned | planned | planned | planned | planned | First target: 1h |
| informative timeframes | planned | planned | later | later | later | later | Not needed by first two strategies |
| atr | planned | planned | planned | planned | planned | planned | Required by both target strategies |
| vp_vah | planned | planned | planned | planned | planned | planned | Required by both target strategies |
| vp_val | planned | planned | planned | planned | planned | planned | Required by both target strategies |
| above_value | planned | planned | planned | planned | planned | planned | Required by both target strategies |
| acceptance_into_value | planned | planned | planned | planned | planned | planned | Required by both target strategies |
| value_area_width_pct | planned | planned | planned | planned | planned | planned | Required by v2 strategy |
| all/any condition groups | planned | planned | planned | planned | planned | planned | Required by target strategies |
| is_true operator | planned | planned | planned | planned | planned | planned | Required by target strategies |
| comparison operators | planned | planned | planned | planned | planned | planned | `<` required by v2 |
| crosses_above/below | planned | planned | later | later | later | later | Stateful support required before enabling live |
| long entry/exit | planned | planned | planned | planned | planned | planned | Required by target strategies |
| short entry/exit | planned | planned | later | later | later | later | Schema should parse early |
| ATR stop | planned | planned | planned | planned | planned | planned | Required by target strategies |
| risk/reward target | planned | planned | planned | planned | planned | planned | Required by target strategies |
| fixed percent stop | planned | planned | later | later | later | later | Enable if copied from Finbar |
| formula features | planned | planned | later | later | later | later | Not needed by target strategies |
| portfolio/multi-asset | no | no | no | no | no | no | Out of MVP scope |

Statuses: `planned`, `later`, `no`, or `done`.
