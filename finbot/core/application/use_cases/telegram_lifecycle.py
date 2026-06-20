"""Extracted lifecycle Telegram handlers (S8 decomposition).

Functions take the use case instance (``uc``) as first arg.
"""

from __future__ import annotations

from finbot.core.application.dto.telegram_command_request import (
    TelegramCommandRequest,
)
from finbot.core.application.dto.telegram_command_result import (
    TelegramCommandResult,
)
from finbot.core.application.use_cases.telegram_helpers import (
    _escape_mdv2,
    _get_symbols,
    _require_active_symbol,
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
            "/help \u2014 Show this message\n\n"
            "*Trading \\(manual control\\):*\n"
            "/symbol \u2014 Activate a trading symbol\n"
            "/price \u2014 Show current price\n"
            "/balance \u2014 Show wallet balance\n"
            "/leverage \u2014 View or set leverage\n"
            "/position \u2014 View current position\n"
            "/long \u2014 Open a long position\n"
            "/short \u2014 Open a short position\n"
            "/close \u2014 Close the active position\n"
            "/sl \u2014 Set stop\\-loss\n"
            "/tp \u2014 Set take\\-profit\n"
            "/orders \u2014 List open orders\n"
            "/cancel \u2014 Cancel an order\n"
            "/mode \u2014 Show connection \\(testnet/mainnet\\)"
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
            "*Runtime:*\n"
            "/run \u2014 Start a trading bot \\(guided setup\\)\n"
            "/stop \u2014 Stop the running bot\n"
            "/status \u2014 View bot status, position & stats\n"
            "/history \u2014 Browse past bot runs\n"
            "/panic \u2014 \U0001f6a8 Emergency: cancel orders \\+ close position\n\n"
            "*Trading:*\n"
            "/symbol \u2014 Activate a symbol for trading\n"
            "/price \u2014 Show current price\n"
            "/balance \u2014 Show wallet balance\n"
            "/leverage \u2014 View / set leverage\n"
            "/position \u2014 View current position \\+ PnL\n"
            "/long \u2014 Open long \\(e\\.g\\. /long 0\\.01 sl 95000\\)\n"
            "/short \u2014 Open short\n"
            "/close \u2014 Close active position\n"
            "/sl \u2014 Set stop\\-loss \\(/sl 2% or /sl 95000\\)\n"
            "/tp \u2014 Set take\\-profit\n"
            "/orders \u2014 List open orders\n"
            "/cancel \u2014 Cancel an order by oid\n"
            "/mode \u2014 Show connection \\(testnet / mainnet\\)\n\n"
            "*Safety:*\n"
            "\u2022 Dry Run is the default \u2014 no real orders\n"
            "\u2022 Testnet / Live require explicit confirmation\n"
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
    lev = result.get("leverage", "0")
    mm = result.get("margin_mode", "?")
    lev_str = (
        f"{_escape_mdv2(lev)}x {_escape_mdv2(mm)}"
        if lev != "0"
        else "unknown \\(set with /leverage\\)"
    )
    return TelegramCommandResult(
        text=(f"\u2705 Active symbol: {_escape_mdv2(sym)}\n" f"Leverage: {lev_str}"),
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
    active, err = _require_active_symbol(uc)
    if err is not None:
        return err
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
    spot = (
        f"Spot: {_escape_mdv2(str(bal.spot_usdc))} "
        "USD \\(available for perp margin\\)\n"
        if bal.spot_usdc > 0
        else ""
    )
    return TelegramCommandResult(
        text=(
            "\U0001f4b0 Account Balance\n"
            f"Margin: {_escape_mdv2(str(bal.wallet_value))} USD\n"
            f"Used: {_escape_mdv2(str(bal.margin_used))} USD\n"
            f"Avail: {_escape_mdv2(str(bal.available))} USD\n" + spot
        ),
        parse_mode="MarkdownV2",
    )


async def _handle_log(uc, request: TelegramCommandRequest) -> TelegramCommandResult:
    """Show recent strategy evaluation log entries."""
    reader = getattr(uc, "_log_reader", None)
    if reader is None:
        return TelegramCommandResult(
            text="Log reader not configured\\.", parse_mode="MarkdownV2"
        )
    available = reader.list_logs()
    if not available:
        return TelegramCommandResult(
            text="No strategy logs found\\. Start a bot with /run first\\.",
            parse_mode="MarkdownV2",
        )
    args = request.args.strip().split()
    name = args[0] if args else available[0]
    n = int(args[1]) if len(args) > 1 else 10
    if name not in available:
        return TelegramCommandResult(
            text=(
                f"Unknown log: {_escape_mdv2(name)}\\. "
                f"Available: {', '.join(available[:8])}"
            ),
            parse_mode="MarkdownV2",
        )
    strategy, symbol = reader.parse_log_name(name)
    entries = reader.read_tail(strategy, symbol, n=n)
    if not entries:
        return TelegramCommandResult(
            text=f"Empty log: {_escape_mdv2(name)}", parse_mode="MarkdownV2"
        )
    lines = [f"*Log: {_escape_mdv2(name)} \\(last {len(entries)}\\)*"]
    for e in entries[-5:]:
        ts = _escape_mdv2(str(e.get("ts", "?")))
        action = e.get("signal", {}).get("action", "?")
        risk = e.get("risk", {})
        intent = e.get("intent")
        close_val = e.get("candle", {}).get("close", "?")
        line = f"  {ts}: close={close_val} action={action}"
        if risk.get("accepted") is False:
            line += f" blocked: {_escape_mdv2(risk.get('gate','?'))}"
        if intent:
            line += f" {intent.get('side','?')} {intent.get('size','?')}"
        lines.append(line)
    if len(entries) > 5:
        lines.append(f"  \\.\\.\\. and {len(entries) - 5} more")
    return TelegramCommandResult(
        text="\n".join(lines),
        parse_mode="MarkdownV2",
    )


async def _handle_mode(uc, request: TelegramCommandRequest) -> TelegramCommandResult:
    """Show current connection environment (testnet / mainnet)."""
    env_url = "Testnet" if uc._testnet else "Mainnet"
    env_emoji = "\U0001f9ea" if uc._testnet else "\U0001f310"
    ack_status = "\u2705 enabled" if uc._live_trading_ack else "\u274c not set"
    lines = [
        f"{env_emoji} *Connection: {env_url}*",
        f"Strategy mode: `{uc._mode}`",
        f"Live trading ack: {ack_status}",
        "",
        "*Environment variables:*",
        f"`FINBOT_MODE={uc._mode}`",
        f"`FINBOT_HYPERLIQUID_TESTNET={"true" if uc._testnet else "false"}`",
    ]
    return TelegramCommandResult(text="\n".join(lines), parse_mode="MarkdownV2")


async def _handle_leverage(uc, request: TelegramCommandRequest):
    """View or set leverage on the active symbol."""
    active, err = _require_active_symbol(uc)
    if err is not None:
        return err
    args = request.args.strip().split()
    if not args:
        if active.leverage == 0:
            return TelegramCommandResult(
                text=(
                    f"{_escape_mdv2(active.symbol)} "
                    "leverage unknown "
                    "\\(set with /leverage 5 cross\\)"
                ),
                parse_mode="MarkdownV2",
            )
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
    active, err = _require_active_symbol(uc)
    if err is not None:
        return err
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
