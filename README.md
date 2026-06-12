# Finbot

Live Hyperliquid trading runtime for strategies created and backtested with
Finbar.

Finbot is intentionally separate from Finbar:

- **Finbar**: strategy schema, validation, indicators, backtests, optimization.
- **Finbot**: live market streams, order lifecycle, reconciliation, and risk
  controls.

## Safety defaults

- Default mode: `dry_run`
- Live trading requires explicit acknowledgment
- Secrets are loaded from environment variables only
- Startup reconciliation is required before trading

## Quick start

```bash
cd C:/HAL/Github/finbot
python -m venv .venv
.venv/Scripts/activate
pip install -e ".[dev]"
cp .env.example .env
finbot --help
```

Read `AGENTS.md` before changing code.
