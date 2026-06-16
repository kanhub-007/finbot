# Telegram Bot Control

## User Story

As a **trader running Finbot strategies**, I want to **start, stop, monitor, and
manage my trading bot entirely through Telegram**, so that **I can control my
strategies from my phone without needing SSH, CLI, or a desktop dashboard**.

## Context

Finbot currently has two control surfaces: a CLI (`finbot run`, `finbot status`,
`finbot panic`) and an MCP server for AI agent integration. Neither is
convenient for a trader on the go. A Telegram bot provides a natural,
notification-capable interface: traders can start strategies, check positions,
see fills in real time, and trigger emergency stop — all from a chat app they
already use.

The Telegram bot runs **in the same process as the MCP server** (no separate
deployment). It uses `python-telegram-bot` (the same library proven in the
telegrammy project) for Bot API interaction, long-polling for update delivery,
and inline keyboards for guided multi-step flows (strategy selection, mode
confirmation, history browsing). Proactive notifications (fills, risk events,
errors) are broadcast to all authorized chats by default.

Security is enforced at multiple levels: only pre-configured Telegram user IDs
can issue control commands; live trading requires both environment-level live
acknowledgement and a Telegram inline-keyboard confirmation; the bot token is
stored only in environment variables; and the panic/kill-switch path is always
available regardless of bot state. Authorization fails closed: when Telegram is
enabled but no allowed user IDs are configured, control commands are denied and
only `/whoami` is available so the operator can discover their Telegram user ID.

## Non-Goals

Things explicitly NOT being built in this iteration:

- **Webhook-based update delivery.** Polling is simpler — no public HTTPS
  endpoint required.
- **Strategy file upload via Telegram.** Strategies must already exist on the
  filesystem where Finbot runs.
- **Per-chat notification preferences (mute/unmute/filter).** All authorized
  chats receive all notifications. Selective subscriptions are future work.
- **Multiple bot instances per chat.** One bot per Finbot process; the Telegram
  interface manages that single bot.
- **Backtesting or replay via Telegram.** Use the CLI or MCP for those.
- **Custom inline keyboards for third-party apps.** The Telegram bot is for
  direct human interaction, not a relay for other services.
- **Backward-compatible database migrations.** Finbot has not been released yet;
  schema changes may rebuild or replace dev tables as needed, as long as tests
  and documented setup remain correct.
