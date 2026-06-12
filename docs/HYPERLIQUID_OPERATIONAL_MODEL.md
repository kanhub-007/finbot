# Hyperliquid Operational Model

This document describes how Finbot should interact with Hyperliquid.

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

Order placement/cancellation/modification requires wallet signing. Hyperliquid
uses private-key signatures, not normal API-key/secret pairs.

Finbot should prefer an agent/API wallet instead of a main wallet.

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
| Testnet execution | yes | testnet/agent private key |
| Live execution | yes | live/agent private key + explicit ack |
