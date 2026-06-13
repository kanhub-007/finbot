# Finbot

Live Hyperliquid trading runtime for Finbar-designed strategies.

Finbot loads YAML strategy files, subscribes to real-time Hyperliquid candles,
computes technical indicators, evaluates entry/exit rules, and executes orders
through a risk-gated pipeline — all while keeping a full audit trail.

**Finbar** → strategy design, backtesting, optimization  
**Finbot** → live execution, risk controls, order lifecycle, reconciliation

---

## Quick Start

```bash
# Prerequisites: Python 3.13+
python -m venv .venv313
.venv313/Scripts/activate        # Windows
# source .venv313/bin/activate   # macOS/Linux

pip install pandas pandas_ta hyperliquid-python-sdk pydantic pydantic-settings \
            python-dotenv pyyaml sqlalchemy pytest black

cp .env.example .env
```

---

## Verify Functionality (no API key needed)

### 1. Run the test suite
```bash
pytest tests/ -q
# → 774 passed, 1 skipped
```

### 2. Replay a strategy over historical bars
```bash
PYTHONPATH=. python finbot/presentation/cli/main.py replay \
  --strategy tests/fixtures/strategies/amt_dip_buyer_final.yaml \
  --bars tests/fixtures/bars/amt_dip_buyer_100_bars.csv \
  --symbol AAPL --interval 1h
```
Output:
```
complete: 6 signals
  bar=49  long_entry  close=97.74  stop=92.49  target=105.61
  bar=60  long_exit   close=97.98
  bar=61  long_entry  close=97.84  stop=92.59  target=105.72
  bar=100 long_exit   close=91.89
  bar=110 long_entry  close=93.09  stop=87.84  target=100.97
  bar=140 long_exit   close=90.62
```

### 3. Validate a strategy
```bash
PYTHONPATH=. python finbot/presentation/cli/main.py validate-strategy \
  --strategy tests/fixtures/strategies/amt_dip_buyer_final.yaml
```

### 4. Check strategy compatibility
```bash
PYTHONPATH=. python finbot/presentation/cli/main.py strategy-compat \
  --strategy tests/fixtures/strategies/amt_dip_buyer_final.yaml
```

---

## Supported Strategies

Currently supports two AMT (Auction Market Theory) strategies:

| Strategy | File | Indicators |
|----------|------|------------|
| AMT Dip Buyer | `amt_dip_buyer_final.yaml` | atr, vp_vah, vp_val, acceptance_into_value, above_value |
| AMT V2 Vol Filter | `amt_v2_vol_filter.yaml` | atr, vp_vah, vp_val, acceptance_into_value, above_value, value_area_width_pct |

Supported risk types: `atr` (ATR-based stop loss), `risk_reward` (take-profit multiplier).

Unsupported strategy features are rejected at startup with a clear explanation.

---

## Execution Modes

| Mode | Submits Orders | Requires | Purpose |
|------|---------------|----------|---------|
| `replay` | No | CSV bars | Verify signals against historical data |
| `dry_run` | No | None | Simulate with fake market data |
| `testnet` | Yes (Hyperliquid testnet) | Private key | Live testnet execution |
| `live` | Yes (Hyperliquid mainnet) | Private key + ACK | Real-money trading |

---

## Commands

```
finbot run                 Start the bot (use --live-data for websocket mode)
finbot replay              Replay strategy over historical CSV bars
finbot validate-strategy   Check if a YAML file is valid
finbot strategy-compat     Show feature support per execution mode
finbot status              Show last signal, order counts, bot run info
finbot db migrate          Apply pending database migrations
finbot panic               Emergency: cancel orders / close position
```

---

## Live Trading Setup

1. Copy `.env.example` to `.env`
2. Set required variables:

```env
FINBOT_MODE=live                          # dry_run | testnet | live
FINBOT_LIVE_TRADING_ACK=true              # Required for live
FINBOT_HYPERLIQUID_PRIVATE_KEY=0x...      # Your 64-byte hex private key
FINBOT_HYPERLIQUID_ACCOUNT_ADDRESS=0x...  # Your wallet address
FINBOT_HYPERLIQUID_VAULT_ADDRESS=0x...   # HIP-3 vault address (optional)
FINBOT_TESTNET=false                      # false = mainnet
FINBOT_DATABASE_URL=sqlite:///data/finbot_live.db
FINBOT_MAX_POSITION_USD=100               # Start small
FINBOT_MAX_DAILY_LOSS_USD=25
```

3. Run:

```bash
PYTHONPATH=. python finbot/presentation/cli/main.py run \
  --live-data \
  --strategy strategies/amt_dip_buyer_final.yaml \
  --symbol BTC --interval 1h
```

The bot will:
1. Validate strategy compatibility
2. Check all live-mode safety gates
3. Load warmup bars from Hyperliquid
4. Subscribe to candle websocket
5. Compute indicators, evaluate rules, run risk gates
6. Submit orders with idempotent `cloid`
7. Track order lifecycle via account websocket events

---

## Architecture

```
┌─────────────────────────────────────────────────────┐
│  presentation/cli/    CLI commands                   │
├─────────────────────────────────────────────────────┤
│  startup/             DI factory, composition root   │
├─────────────────────────────────────────────────────┤
│  core/application/    Use cases, orchestration       │
│  core/domain/         Entities, interfaces, services │
├─────────────────────────────────────────────────────┤
│  infrastructure/      Hyperliquid SDK, SQLite,       │
│                       pandas_ta, YAML parser         │
└─────────────────────────────────────────────────────┘
```

**Pipeline:** `candle → warmup → indicators → validation → evaluate → risk gates → plan → submit → lifecycle`

---

## Multi-Ticker

Finbot runs **one ticker per instance**. To trade multiple symbols, run separate
processes with different `--symbol` arguments and database paths:

```bash
finbot run --strategy dip.yaml --symbol BTC  --interval 1h &
finbot run --strategy dip.yaml --symbol ETH  --interval 1h &
```

---

## HIP-3 Vault Support

HIP-3 vault trading is supported via `FINBOT_HYPERLIQUID_VAULT_ADDRESS`.
When set, the exchange gateway authenticates as the vault address for order
submission. Set it in `.env`:

```env
FINBOT_HYPERLIQUID_VAULT_ADDRESS=0x...
```

The private key must belong to an authorized vault agent.

---

## Perpetuals (Perps)

Finbot trades Hyperliquid perps by default — the `Exchange` SDK class handles
perpetual futures. No additional configuration needed. Spot trading is not
currently supported.

---

## Security

- Private keys loaded from environment only (`SecretStr`)
- Never logged, never printed, never serialized
- Redacted from all log output via `SecretRedactingFilter`
- Live mode blocked without explicit `FINBOT_LIVE_TRADING_ACK=true`
- All live-mode blockers reported together (not one at a time)
- In-memory database rejected for live mode

---

## Development

```bash
pytest tests/ -q              # Full suite: 774 tests
pytest tests/test_architecture/ -q  # Architecture: 487 tests
ruff check finbot tests       # Lint
black --check finbot tests    # Format
```

See `AGENTS.md` for architecture rules, design patterns, and coding conventions.
