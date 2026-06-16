# Strategy Compatibility Matrix

This matrix tracks Finbot support for Finbar strategy features. Statuses are
derived from the installed `finbar-strategy-runtime` package at runtime — there
are no hand-maintained lists to drift.

| Feature | Parsed | Validated | Replay | Live Dry-run | Testnet | Live | Notes |
|---|---:|---:|---:|---:|---:|---:|---|
| schema_version | done | done | n/a | n/a | n/a | n/a | Package-enforced at parse time |
| name/description | done | done | done | done | done | done | Used for audit/signals |
| parameters/defaults | done | done | done | done | done | done | Resolved by package parser |
| primary timeframe | done | done | done | done | done | done | Required by all strategies |
| informative timeframes | done | done | done | done | done | done | Package supports multi-TF bar merging |
| all/any condition groups | done | done | done | done | done | done | Required by all strategies |
| not condition group | done | done | done | done | done | done | Supported by package evaluator |
| all comparison operators | done | done | done | done | done | done | `<`, `>`, `<=`, `>=`, `==`, `!=` |
| is_true operator | done | done | done | done | done | done | Required by target strategies |
| is_false operator | done | done | done | done | done | done | Supported by package evaluator |
| crosses_above/below | done | done | done | done | done | done | Package evaluator handles stateful crossovers |
| between/not_between | done | done | done | done | done | done | Supported by package evaluator |
| exists/missing | done | done | done | done | done | done | Supported by package evaluator |
| long entry/exit | done | done | done | done | done | done | Required by target strategies |
| short entry/exit | done | done | done | done | done | done | Package evaluator supports both sides |
| ATR stop | done | done | done | done | done | done | Required by target strategies |
| fixed_pct stop | done | done | done | done | done | done | Package `JsonRiskPriceCalculator` supports it |
| risk_reward target | done | done | done | done | done | done | Required by target strategies |
| ATR target | done | done | done | done | done | done | Package supports ATR-based take profit |
| fixed_pct target | done | done | done | done | done | done | Package supports fixed-pct take profit |
| formula features | done | done | done | done | done | done | Package `PandasFormulaFeatureCalculator` handles rolling/shift/body_pct/etc. |
| profile shape classifiers | done | done | done | done | done | done | B/D/P/neutral shape detection |
| composite volume profile | done | done | done | done | done | done | Multi-day CVP (5d/10d/20d) |
| VSA signals | done | done | done | done | done | done | Stopping volume, no demand/supply, climax, etc. |
| SMC / smart money concepts | done | done | done | done | done | done | Order blocks, FVG, BOS, CHoCH, liquidity sweeps |
| Wyckoff phases | done | done | done | done | done | done | Accumulation, markup, distribution, markdown |
| Hurst / regime detection | done | done | done | done | done | done | Hurst exponent, fractal regime, market regime |
| supply/demand zones | done | done | done | done | done | done | Zone detection, scoring, failure signals |
| Fibonacci levels | done | done | done | done | done | done | 0.382, 0.5, 0.618 retracements, 1.618 extension |
| Bill Williams indicators | done | done | done | done | done | done | Alligator, Awesome Oscillator, Accelerator, Fractals |
| VWAP bands | done | done | done | done | done | done | Session VWAP ± bands |
| liquidity / microstructure proxies | done | done | done | done | done | done | Spread, illiquidity, resiliency, VPIN, OFI |
| volatility estimators | done | done | done | done | done | done | Parkinson, Garman-Klass, Rogers-Satchell, Yang-Zhang, realized |
| intraday seasonality | done | done | done | done | done | done | Volume curves, IB range, day type classification |
| funding / OI / liquidations | done | done | done | done | done | done | Funding rate, open interest delta, liquidation data |
| standard TA (sma/ema/rsi/adx/macd/kama) | done | done | done | done | done | done | All standard pandas-ta indicators via package |
| portfolio/multi-asset | no | no | no | no | no | no | Out of MVP scope — one ticker per instance |

Statuses: `done`, `no`, or `error`.
