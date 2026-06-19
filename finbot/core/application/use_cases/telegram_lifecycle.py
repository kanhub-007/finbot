"""Extracted lifecycle Telegram handlers (S8 decomposition).

Functions take the use case instance (``uc``) as first arg.
"""

from __future__ import annotations

from finbot.core.application.dto.telegram_command_result import (
    TelegramCommandResult,
)
from finbot.core.application.use_cases.telegram_helpers import (
    _escape_mdv2,
    _get_symbols,
)
from finbot.core.domain.entities.telegram_chat import TelegramChat


async def _handle_start(uc, request: TelegramCommandRequest) -> TelegramCommandResult:
    """Register the chat for notifications and return the welcome message."""
    chat = await uc._chat_repo.get_chat(request.chat_id)
    if chat is None:
        chat = TelegramChat(
            chat_id=request.chat_id,
            user_id=request.user_id,
            notifications_enabled=True,
        )
        await uc._chat_repo.add_chat(chat)

    return TelegramCommandResult(
        text=(
            "\U0001f916 *Finbot Trading Bot*\n"
            "Connected to Hyperliquid\\. Manage your trading "
            "strategies from here\\.\n\n"
            "*Commands:*\n"
            "/run \u2014 Start a trading bot\n"
            "/stop \u2014 Stop the running bot\n"
            "/status \u2014 View bot status & stats\n"
            "/history \u2014 Browse past runs\n"
            "/panic \u2014 \U0001f6a8 Emergency stop \\+ cancel orders\n"
            "/help \u2014 Show this message"
        ),
        parse_mode="MarkdownV2",
        reply_markup={
            "inline_keyboard": [
                [
                    {"text": "Run Bot", "callback_data": "/run"},
                    {"text": "Status", "callback_data": "/status"},
                ],
                [
                    {"text": "History", "callback_data": "/history"},
                    {"text": "Help", "callback_data": "/help"},
                ],
            ]
        },
    )


async def _handle_help(uc, request: TelegramCommandRequest) -> TelegramCommandResult:
    """Return the command list and safety notes."""
    return TelegramCommandResult(
        text=(
            "*Finbot Commands*\n\n"
            "/run \u2014 Start a trading bot \\(guided setup\\)\n"
            "/stop \u2014 Stop the running bot\n"
            "/status \u2014 View bot status, position & stats\n"
            "/history \u2014 Browse past bot runs\n"
            "/panic \u2014 \U0001f6a8 Emergency: cancel orders \\+ close position\n"
            "/help \u2014 Show this message\n\n"
            "*Safety:*\n"
            "\u2022 Default mode is Dry Run \u2014 no real orders\n"
            "\u2022 Live/Testnet require explicit confirmation\n"
            "\u2022 Only one bot can run at a time"
        ),
        parse_mode="MarkdownV2",
        reply_markup={
            "inline_keyboard": [
                [
                    {"text": "Run Bot", "callback_data": "/run"},
                    {"text": "Status", "callback_data": "/status"},
                    {"text": "History", "callback_data": "/history"},
                ],
            ]
        },
    )


async def _handle_status(uc, request: TelegramCommandRequest) -> TelegramCommandResult:
    """Return the bot's current live status or last run summary."""
    mgr = uc._bot_manager
    status = mgr.get_status()
    is_running = status.get("is_running", False)
    if is_running:
        return uc._format_running_status(status)
    else:
        return uc._format_idle_status(status)


def _format_running_status(uc, status: dict) -> TelegramCommandResult:
    """Format the status response for a running bot."""
    run_id = str(status.get("bot_run_id", ""))
    strategy = str(status.get("strategy_name", ""))
    symbol = str(status.get("symbol", ""))
    interval = str(status.get("interval", ""))
    mode = str(status.get("mode", ""))
    uptime_s = int(status.get("uptime_seconds", 0))
    hours = uptime_s // 3600
    minutes = (uptime_s % 3600) // 60
    total_signals = status.get("total_signals", 0)
    total_orders = status.get("total_orders", 0)
    total_fills = status.get("total_fills", 0)

    text = (
        "\U0001f4ca *Bot Status*\n"
        f"State: \u25b6 Running\n"
        f"Run ID: {_escape_mdv2(run_id)}\n"
        f"Strategy: {_escape_mdv2(strategy)}\n"
        f"Symbol: {_escape_mdv2(symbol)} / {_escape_mdv2(interval)}\n"
        f"Mode: {_escape_mdv2(mode)}\n"
        f"Uptime: {hours}h {minutes}m\n\n"
        f"*Totals:*\n"
        f"Signals: {total_signals} \\| Orders: {total_orders} "
        f"\\| Fills: {total_fills}"
    )
    return TelegramCommandResult(
        text=text,
        parse_mode="MarkdownV2",
        reply_markup={
            "inline_keyboard": [
                [
                    {"text": "Refresh", "callback_data": "/status"},
                    {"text": "Stop Bot", "callback_data": "/stop"},
                ],
            ]
        },
    )


def _format_idle_status(uc, status: dict) -> TelegramCommandResult:
    """Format the status response when no bot is running."""
    last_run = status.get("last_run")

    lines = [
        "\U0001f4ca *Bot Status*",
        "State: \u23f8 Idle",
        "No bot running\\.",
    ]

    if last_run is not None:
        lines.append("")
        lines.append("*Last Run:* " + _escape_mdv2(str(last_run.get("run_id", ""))))
        lines.append(
            "Strategy: " + _escape_mdv2(str(last_run.get("strategy_name", "")))
        )
        symbol = _escape_mdv2(str(last_run.get("symbol", "")))
        interval = _escape_mdv2(str(last_run.get("interval", "")))
        lines.append(f"Symbol: {symbol} / {interval}")
        ended = str(last_run.get("ended_at", ""))
        if ended:
            lines.append(f"Ended: {_escape_mdv2(ended)}")
    else:
        lines.append("")
        lines.append("No run history\\.")

    text = "\n".join(lines)
    return TelegramCommandResult(
        text=text,
        parse_mode="MarkdownV2",
        reply_markup={
            "inline_keyboard": [
                [
                    {"text": "Run new bot", "callback_data": "/run"},
                    {"text": "History", "callback_data": "/history"},
                ],
            ]
        },
    )


async def _handle_stop(uc, request: TelegramCommandRequest) -> TelegramCommandResult:
    """Stop the running bot and return a summary."""
    stop_result = uc._bot_manager.stop()
    if stop_result.get("status") == "no_bot_running":
        return TelegramCommandResult(
            text="\u23f9 No bot is currently running\\.",
            parse_mode="MarkdownV2",
        )
    return TelegramCommandResult(
        text=(
            "\u23f9 *Bot stopped\\.*\n"
            f"Run: {_escape_mdv2(str(stop_result.get('bot_run_id', '')))}"
        ),
        parse_mode="MarkdownV2",
        reply_markup={
            "inline_keyboard": [
                [
                    {"text": "View details", "callback_data": "/history"},
                    {"text": "Start new bot", "callback_data": "/run"},
                ],
            ]
        },
    )


async def _handle_list(uc, request: TelegramCommandRequest) -> TelegramCommandResult:
    """List available strategy files."""
    strategies = uc._strategy_dir.list_strategies()
    if not strategies:
        return TelegramCommandResult(
            text="No strategy files found\\.",
            parse_mode="MarkdownV2",
        )

    lines = ["\U0001f4c1 *Available Strategies*"]
    for i, s in enumerate(strategies, 1):
        lines.append(f"{i}\\. {_escape_mdv2(s)}")

    return TelegramCommandResult(
        text="\n".join(lines),
        parse_mode="MarkdownV2",
        reply_markup={
            "inline_keyboard": [
                [
                    {"text": "Run a strategy", "callback_data": "/run"},
                ],
            ]
        },
    )


async def _handle_mute(uc, request: TelegramCommandRequest) -> TelegramCommandResult:
    """Suppress notifications for this chat."""
    await uc._chat_repo.set_notifications(request.chat_id, False)
    return TelegramCommandResult(
        text="\U0001f515 Notifications muted\\. Use /unmute to resume\\.",
        parse_mode="MarkdownV2",
    )


async def _handle_unmute(uc, request: TelegramCommandRequest) -> TelegramCommandResult:
    """Resume notifications for this chat."""
    await uc._chat_repo.set_notifications(request.chat_id, True)
    return TelegramCommandResult(
        text="\U0001f514 Notifications unmuted\\.",
        parse_mode="MarkdownV2",
    )


async def _handle_history(uc, request: TelegramCommandRequest) -> TelegramCommandResult:
    """Show a paginated list of recent bot runs."""
    runs = uc._bot_manager.list_bot_runs(limit=5)

    if not runs:
        return TelegramCommandResult(
            text="No runs yet\\. Start one with /run\\.",
            parse_mode="MarkdownV2",
            reply_markup={
                "inline_keyboard": [
                    [{"text": "Run a bot", "callback_data": "/run"}],
                ]
            },
        )

    lines = ["\U0001f4cb *Recent Bot Runs*"]
    for i, run in enumerate(runs, 1):
        r_id = _escape_mdv2(str(getattr(run, "run_id", "")))
        name = _escape_mdv2(str(getattr(run, "strategy_name", "")))
        sym = _escape_mdv2(str(getattr(run, "symbol", "")))
        iv = _escape_mdv2(str(getattr(run, "interval", "")))
        md = _escape_mdv2(str(getattr(run, "mode", "")))
        lines.append(f"{i}\\. {r_id} \u2014 {name} / {sym} / {iv}\n{md}")

    return TelegramCommandResult(
        text="\n".join(lines),
        parse_mode="MarkdownV2",
        reply_markup={
            "inline_keyboard": [
                [
                    {"text": "\u25c0 Prev", "callback_data": "hist:prev"},
                    {"text": "Next \u25b6", "callback_data": "hist:next"},
                ],
            ]
        },
    )


async def _handle_symbol(uc, request: TelegramCommandRequest):
    """Activate a symbol (reads exchange leverage, no overwrite)."""
    args = request.args.strip()
    if not args:
        symbols = _get_symbols(getattr(uc, "_metadata_provider", None))
        if not symbols:
            return TelegramCommandResult(text="No symbols available\\.")
        return uc._render_symbol_picker(symbols, page=0)
    result = uc._bot_manager.activate_symbol(args.split()[0].upper())
    if result.get("status") != "active":
        return TelegramCommandResult(
            text=f"\u274c {_escape_mdv2(str(result.get('message', 'Rejected')))}",
            parse_mode="MarkdownV2",
        )
    sym = result.get("symbol", args.upper())
    lev = result.get("leverage", "1")
    mm = result.get("margin_mode", "isolated")
    return TelegramCommandResult(
        text=(
            f"\u2705 Active symbol: {_escape_mdv2(sym)}\n"
            f"Leverage: {_escape_mdv2(lev)}x {_escape_mdv2(mm)}"
        ),
        parse_mode="MarkdownV2",
    )


def _render_symbol_picker(uc, symbols, page=0):
    """Render a paginated symbol picker for /symbol with no args."""
    per_page = 6
    total = max(1, (len(symbols) + per_page - 1) // per_page)
    page = max(0, min(page, total - 1))
    start = page * per_page
    page_syms = symbols[start : start + per_page]
    rows = []
    row = []
    for sym in page_syms:
        row.append({"text": sym, "callback_data": f"sympick:{sym}"})
        if len(row) == 3:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    nav = []
    if page > 0:
        nav.append({"text": "\u25c0 Prev", "callback_data": f"sympage:{page - 1}"})
    nav.append({"text": f"{page + 1}/{total}", "callback_data": "none"})
    if page < total - 1:
        nav.append({"text": "Next \u25b6", "callback_data": f"sympage:{page + 1}"})
    rows.append(nav)
    return TelegramCommandResult(
        text=f"Select symbol \\({len(symbols)} available\\):",
        parse_mode="MarkdownV2",
        reply_markup={"inline_keyboard": rows},
    )


async def _handle_price(uc, request: TelegramCommandRequest):
    """Show the current price for the active symbol."""
    active = uc._bot_manager.get_active_symbol()
    if active is None:
        return TelegramCommandResult(
            text="No symbol selected\\. Use /symbol first\\.",
            parse_mode="MarkdownV2",
        )
    try:
        price = uc._bot_manager.get_active_price()
    except Exception as exc:
        return TelegramCommandResult(
            text=f"Could not fetch price: {_escape_mdv2(str(exc))}",
            parse_mode="MarkdownV2",
        )
    price_str = "?" if price is None else str(price)
    return TelegramCommandResult(
        text=f"{_escape_mdv2(active.symbol)}: {_escape_mdv2(price_str)} USD",
        parse_mode="MarkdownV2",
    )


async def _handle_balance(uc, request: TelegramCommandRequest):
    """Show wallet balance."""
    bal = uc._bot_manager.get_balance()
    if bal is None:
        return TelegramCommandResult(
            text="Requires wallet connection\\.", parse_mode="MarkdownV2"
        )
    return TelegramCommandResult(
        text=(
            "\U0001f4b0 Account Balance\n"
            f"Wallet: {_escape_mdv2(str(bal.wallet_value))} USD\n"
            f"Margin used: {_escape_mdv2(str(bal.margin_used))} USD\n"
            f"Available: {_escape_mdv2(str(bal.available))} USD"
        ),
        parse_mode="MarkdownV2",
    )


async def _handle_leverage(uc, request: TelegramCommandRequest):
    """View or set leverage on the active symbol."""
    active = uc._bot_manager.get_active_symbol()
    if active is None:
        return TelegramCommandResult(
            text="No symbol selected\\. Use /symbol first\\.",
            parse_mode="MarkdownV2",
        )
    args = request.args.strip().split()
    if not args:
        return TelegramCommandResult(
            text=(
                f"{_escape_mdv2(active.symbol)} "
                f"{_escape_mdv2(str(active.leverage))}x "
                f"{_escape_mdv2(active.margin_mode)}"
            ),
            parse_mode="MarkdownV2",
        )
    try:
        lev = int(args[0])
    except ValueError:
        return TelegramCommandResult(
            text="Leverage must be a number\\.", parse_mode="MarkdownV2"
        )
    mm = args[1].lower() if len(args) > 1 else "isolated"
    result = uc._bot_manager.set_leverage(lev, mm)
    if result.get("status") != "ok":
        return TelegramCommandResult(
            text=f"\u274c {_escape_mdv2(str(result.get('message', 'Rejected')))}",
            parse_mode="MarkdownV2",
        )
    return TelegramCommandResult(
        text=(
            f"Leverage set: {_escape_mdv2(active.symbol)} "
            f"{_escape_mdv2(str(lev))}x {_escape_mdv2(mm)}"
        ),
        parse_mode="MarkdownV2",
    )


async def _handle_position(uc, request: TelegramCommandRequest):
    """Show the current position + PnL for the active symbol."""
    active = uc._bot_manager.get_active_symbol()
    if active is None:
        return TelegramCommandResult(
            text="No symbol selected\\. Use /symbol first\\.",
            parse_mode="MarkdownV2",
        )
    pos = uc._bot_manager.get_active_position()
    if pos is None or pos.direction.value == "flat":
        return TelegramCommandResult(
            text=f"No open position on {_escape_mdv2(active.symbol)}\\.",
            parse_mode="MarkdownV2",
        )
    entry = pos.entry_price if pos.entry_price is not None else "?"
    return TelegramCommandResult(
        text=(
            f"\U0001f4ca Position: {_escape_mdv2(active.symbol)}\n"
            f"Side: {_escape_mdv2(pos.direction.value.upper())}\n"
            f"Size: {_escape_mdv2(str(pos.size))}\n"
            f"Entry: {_escape_mdv2(str(entry))}\n"
            f"PnL: {_escape_mdv2(str(pos.unrealized_pnl))} USD\n"
            f"Leverage: {_escape_mdv2(str(active.leverage))}x "
            f"{_escape_mdv2(active.margin_mode)}"
        ),
        parse_mode="MarkdownV2",
    )
