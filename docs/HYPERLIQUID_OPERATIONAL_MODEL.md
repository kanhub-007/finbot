# Hyperliquid Operational Model

This document describes how Finbot interacts with Hyperliquid.

## Authentication — Agent Wallets

Hyperliquid is a decentralized L1 app chain. Instead of traditional CEX API
keys, every trading request requires a cryptographic signature from an
**Agent Wallet** (API Wallet).

An Agent Wallet is a secondary Ethereum-style private key that you authorize
to sign trades on behalf of your main account:
- **What it can do:** place orders, cancel orders, modify positions.
- **What it CANNOT do:** withdraw or transfer funds.

**Setup:** Generate an Agent key at https://app.hyperliquid.xyz/API, authorize
it via an L1 signature from your main wallet, then provide:
- `FINBOT_HYPERLIQUID_PRIVATE_KEY` → the Agent's private key (signs trades)
- `FINBOT_HYPERLIQUID_ACCOUNT_ADDRESS` → your main wallet address (whose funds to trade)

> ⚠️ Agent keys expire after 90 days (or 180 if set to MAX in the UI). When
> expired, the bot gets unauthorized errors — generate a new Agent key.

## Public market data

Public websocket data does not require secrets.

Likely subscriptions:

```python
{"type": "candle", "coin": "BTC", "interval": "1h"}
{"type": "bbo", "coin": "BTC"}
{"type": "trades", "coin": "BTC"}
```

## Account read-only data

Account streams require the public account/wallet address, not the private key.

```python
{"type": "userFills", "user": address}
{"type": "orderUpdates", "user": address}
{"type": "webData2", "user": address}
```

## Order execution

Order placement/cancellation/modification requires wallet signing. The SDK uses
the Agent Wallet private key to sign payloads locally, then sends the signed
transaction and main account address to the Hyperliquid Exchange API.

```
[ Main Wallet ]  ← holds the funds
       ↑ authorized via L1
[ Agent Key   ]  ← signs trades, ZERO funds, cannot withdraw
```

Always use an Agent Wallet — never put your main wallet's private key in the
bot configuration.

## Fund management

Finbot MVP must not implement:

- deposits
- withdrawals
- bridging
- transfers
- vault management

Finbot should only trade with collateral already deposited on Hyperliquid.

## Runtime phases

| Phase | Uses Hyperliquid? | Secrets required? |
|---|---|---|
| Replay dry-run | no | no |
| Public websocket dry-run | yes | no |
| Account read-only dry-run | yes | account address only |
| Testnet execution | yes | Agent Wallet private key |
| Live execution | yes | Agent Wallet private key + explicit ACK |
