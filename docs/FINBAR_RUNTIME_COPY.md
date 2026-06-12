# Finbar Runtime Copy Inventory

This document must be filled before copying Finbar strategy runtime code into
Finbot.

## Rules

- Copy only the strategy runtime subset needed by Finbot.
- Do not copy Finbar REST/MCP presentation code.
- Do not copy Finbar startup/composition code.
- Do not copy Finbar backtest result storage unless explicitly justified.
- Rewrite imports from `finbar.*` to `finbot.*`.
- Add tests proving copied production code does not import `finbar`.

## Inventory

| Finbar source path | Finbot target path | Needed for | Dependencies | Notes |
|---|---|---|---|---|
| TBD | TBD | TBD | TBD | TBD |

## Review checklist

- [ ] Each copied file has a clear reason.
- [ ] No unrelated application/presentation code is copied.
- [ ] Imports are rewritten.
- [ ] Tests cover copied behavior.
- [ ] Optional parity test exists where possible.
