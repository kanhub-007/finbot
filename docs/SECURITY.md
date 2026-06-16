# Security

Finbot is live-trading software. Treat private keys and order execution as
safety-critical.

## Authentication — Agent Wallets

Finbot uses Hyperliquid **Agent Wallets** (API Wallets) for authentication.
An Agent Wallet is a dedicated private key that signs trades on behalf of your
main account. It **cannot withdraw or transfer funds** — even if compromised,
an attacker can only trade, not steal your capital.

**How it works:**
- `FINBOT_HYPERLIQUID_PRIVATE_KEY` — the Agent Wallet private key (generated at
  app.hyperliquid.xyz/API). This signs order payloads locally.
- `FINBOT_HYPERLIQUID_ACCOUNT_ADDRESS` — your main wallet address. Tells
  Hyperliquid whose margin to trade with.
- The Agent key is authorized via an L1 transaction from your main wallet.

> ⚠️ **Agent keys expire after 90 days (or 180 if set to MAX).** When your bot
> starts getting unauthorized errors after months of running, the Agent key has
> likely expired. Generate a new one on the API page.

**Never use your main wallet's private key** for `FINBOT_HYPERLIQUID_PRIVATE_KEY`.
Always generate a dedicated Agent Wallet.

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

- Agent Wallet private key (not the main wallet key)
- main account address
- max position/notional limit
- persistence enabled
- successful startup reconciliation

## Redaction

Logs, exceptions, settings reprs, and audit events must never show full secret
values.

Required tests:

- private key not required for dry-run
- Agent Wallet private key required for testnet/live execution
- settings repr does not expose private key
- logs redact private key value

## Fund movement

MVP must not implement withdrawals, deposits, bridging, or transfers. Finbot only
places/cancels/modifies trading orders. Agent Wallets cannot withdraw funds
anyway — this is enforced at the Hyperliquid protocol level.
