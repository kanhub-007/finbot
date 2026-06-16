# Telegram Bot Control

**Date:** 2026-06-16
**Status:** Spec complete — ready for implementation

## Summary

Add native Telegram bot support to Finbot so traders can start/stop/monitor
strategies and receive trade notifications entirely through Telegram chat.

Uses `python-telegram-bot` v21+ with long-polling, inline keyboards for guided
flows, and MarkdownV2 formatting. Runs in the same process as the MCP server.

## Files

| File | Contents |
|------|----------|
| [01-story.md](01-story.md) | User story, context, non-goals |
| [02-scenarios.md](02-scenarios.md) | All scenarios with UI flows, Gherkin, Verify blocks |
| [03-domain.md](03-domain.md) | Domain model: entities, value objects, events, interfaces |
| [04-implementation.md](04-implementation.md) | Step-by-step implementation guide (17 steps) |
| [05-architecture.md](05-architecture.md) | Architecture Decision Records (9 ADRs) |

## Slices

| Slice | Scope | Scenarios |
|-------|-------|-----------|
| 1 (MVP) | Must Have | /start, /whoami, /status (idle+running), /run (guided flow), /stop, /help, trade notifications, risk notifications, fail-closed authorization, unknown command, bot-already-running |
| 2 | Should Have | /history browsing, run details, signals/orders/fills drill-down, /panic (including idle symbol selection), /list strategies |
| 3 | Could Have | /mute / /unmute, notification type filters, custom symbol input |

## Key Decisions

| Decision | Choice |
|----------|--------|
| Telegram library | `python-telegram-bot` v21+ |
| Update delivery | Long-polling (no webhook) |
| Process model | In-process with MCP server; Telegram owns a background asyncio loop/thread |
| User interaction | Inline keyboards for guided flows |
| Callback state | Server-side session store; compact callback_data under 64 bytes |
| Authorization | Fail closed; `/whoami` available to discover Telegram user ID |
| Notifications | Broadcast to all authorized chats through thread-safe dispatcher |
| Message format | MarkdownV2 |
| Strategy source | Local filesystem (no upload) |
| Database compatibility | Not required during dev; fresh schema correctness is enough |
