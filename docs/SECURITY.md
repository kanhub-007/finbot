# Security

Finbot is live-trading software. Treat private keys and order execution as
safety-critical.

## Secrets

- Do not commit private keys, mnemonics, or wallet secrets.
- Do not store private keys in SQLite.
- Do not store private keys in bot config YAML.
- Load private keys only from environment variables or a future secrets manager.
- Dry-run must not require private keys.

## Live mode requirements

Live mode must require:

```env
FINBOT_MODE=live
FINBOT_LIVE_TRADING_ACK=true
```

It must also require:

- private key or agent wallet private key
- account address
- max position/notional limit
- persistence enabled
- successful startup reconciliation

## Redaction

Logs, exceptions, settings reprs, and audit events must never show full secret
values.

Required tests:

- private key not required for dry-run
- private key required for testnet/live execution
- settings repr does not expose private key
- logs redact private key value

## Fund movement

MVP must not implement withdrawals, deposits, bridging, or transfers. Finbot only
places/cancels/modifies trading orders.
