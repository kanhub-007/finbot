"""Extracted Telegram command handlers — telegram_run_flow (S8 decomposition)."""

from __future__ import annotations

from finbot.core.application.dto.telegram_command_result import (
    TelegramCommandResult,
)
from finbot.core.application.use_cases.telegram_helpers import (
    _DEFAULT_INTERVALS,
    _escape_mdv2,
    _get_symbols,
)


async def _handle_run(uc, request: TelegramCommandRequest) -> TelegramCommandResult:
    """Start the guided /run flow or reject if bot is already running."""
    if uc._bot_manager.is_running():
        run_id = str(uc._bot_manager.get_status().get("bot_run_id", ""))
        return TelegramCommandResult(
            text=(
                "\u26a0\ufe0f A bot is already running "
                f"\\({_escape_mdv2(run_id)}\\)\\.\n"
                "Stop it first with /stop, then start a new one\\."
            ),
            parse_mode="MarkdownV2",
            reply_markup={
                "inline_keyboard": [
                    [
                        {"text": "Stop current bot", "callback_data": "/stop"},
                        {"text": "Cancel", "callback_data": "cancel"},
                    ],
                ]
            },
        )

    strategies = uc._strategy_dir.list_strategies()
    if not strategies:
        return TelegramCommandResult(
            text="No strategies found\\. Place \\\\.yaml files "
            "in the strategies directory\\.",
            parse_mode="MarkdownV2",
        )

    # Create a session for the run flow
    session = uc._session_store.create(request.chat_id, request.message_id)

    # If user typed "/run BTC", pre-fill symbol to skip the picker
    if request.args.strip():
        session.symbol = request.args.strip().upper()

    sid = session.session_id

    # Build inline keyboard for strategies
    displayed = strategies[:10]
    buttons = []
    for i, s in enumerate(displayed):
        buttons.append({"text": s, "callback_data": f"run:{sid}:strat:{i}"})
    keyboard_rows = []
    for i in range(0, len(buttons), 2):
        keyboard_rows.append(buttons[i : i + 2])

    return TelegramCommandResult(
        text="*Start a Bot*\nSelect a strategy:",
        parse_mode="MarkdownV2",
        reply_markup={"inline_keyboard": keyboard_rows},
    )


async def _handle_run_callback(
    uc, request: CallbackQueryRequest, data: CallbackData
) -> TelegramCommandResult:
    """Advance the /run guided-flow state machine.

    Callback format: run:<sid>:<action>:<value>
    data.action = session_id, data.value = action, data.subvalue = value
    """
    session_id = data.action  # parts[1]
    action = data.value  # parts[2]
    value = data.subvalue  # parts[3]

    session = uc._session_store.get(session_id)
    if session is None:
        return TelegramCommandResult(
            text="Session expired. Please start again with /run\\."
        )

    # Validate session ownership
    if session.chat_id != request.chat_id:
        return TelegramCommandResult(
            text="Invalid selection, please start again with /run\\."
        )

    if action == "strat":
        return uc._run_cb_strat(session, value)
    elif action == "sym":
        return uc._run_cb_sym(session, value)
    elif action == "page":
        return uc._render_symbol_page(session, page=int(value))
    elif action == "int":
        return uc._run_cb_int(session, value)
    elif action == "mode":
        return uc._run_cb_mode(session, value)
    elif action == "confirm":
        return uc._run_cb_confirm(session, value)
    else:
        return TelegramCommandResult(
            text="Invalid selection, please start again with /run\\."
        )


def _render_symbol_page(uc, session, page: int = 0) -> TelegramCommandResult:
    """Render a paginated symbol picker."""
    _SYMBOLS_PER_PAGE = 6
    symbols = _get_symbols(uc._metadata_provider)
    total_pages = (len(symbols) + _SYMBOLS_PER_PAGE - 1) // _SYMBOLS_PER_PAGE
    page = max(0, min(page, total_pages - 1))

    sid = session.session_id
    start = page * _SYMBOLS_PER_PAGE
    page_symbols = symbols[start : start + _SYMBOLS_PER_PAGE]

    # Symbol buttons (2 rows of 3)
    keyboard_rows = []
    row = []
    for sym in page_symbols:
        row.append({"text": sym, "callback_data": f"run:{sid}:sym:{sym}"})
        if len(row) == 3:
            keyboard_rows.append(row)
            row = []
    if row:
        keyboard_rows.append(row)

    # Navigation row
    nav_row = []
    if page > 0:
        nav_row.append(
            {"text": "\u25c0 Prev", "callback_data": f"run:{sid}:page:{page - 1}"}
        )
    nav_row.append({"text": f"{page + 1}/{total_pages}", "callback_data": "none"})
    if page < total_pages - 1:
        nav_row.append(
            {"text": "Next \u25b6", "callback_data": f"run:{sid}:page:{page + 1}"}
        )
    keyboard_rows.append(nav_row)

    # Search hint row
    keyboard_rows.append(
        [{"text": "\u2315 Tip: /run BTC skips this step", "callback_data": "none"}]
    )

    return TelegramCommandResult(
        text=(
            f"Select symbol \\({len(symbols)} available,"
            f" page {page + 1}/{total_pages}\\):"
        ),
        parse_mode="MarkdownV2",
        reply_markup={"inline_keyboard": keyboard_rows},
    )


def _run_cb_strat(uc, session, idx_str: str) -> TelegramCommandResult:
    """User selected a strategy — show symbol picker."""
    strategies = uc._strategy_dir.list_strategies()
    try:
        idx = int(idx_str)
        strategy_name = strategies[idx]
    except (ValueError, IndexError):
        return TelegramCommandResult(
            text="Invalid strategy selection. " "Please start again with /run\\."
        )

    session.strategy_path = uc._strategy_dir.get_strategy_path(strategy_name)
    uc._session_store.save(session)

    # If symbol was pre-filled via "/run BTC", skip the picker
    if session.symbol:
        return uc._run_cb_sym(session, session.symbol)

    return uc._render_symbol_page(session, page=0)


def _run_cb_sym(uc, session, symbol: str) -> TelegramCommandResult:
    """User selected a symbol — show interval picker."""
    session.symbol = symbol
    uc._session_store.save(session)

    sid = session.session_id
    buttons = []
    for interval in _DEFAULT_INTERVALS:
        buttons.append({"text": interval, "callback_data": f"run:{sid}:int:{interval}"})
    keyboard_rows = []
    for i in range(0, len(buttons), 3):
        keyboard_rows.append(buttons[i : i + 3])

    return TelegramCommandResult(
        text=(
            f"Strategy: {_escape_mdv2(session.strategy_path or '')}\n"
            f"Symbol: {_escape_mdv2(symbol)}\n"
            "Select interval:"
        ),
        parse_mode="MarkdownV2",
        reply_markup={"inline_keyboard": keyboard_rows},
    )


def _run_cb_int(uc, session, interval: str) -> TelegramCommandResult:
    """User selected an interval — show mode picker."""
    session.interval = interval
    uc._session_store.save(session)

    sid = session.session_id
    return TelegramCommandResult(
        text=(
            f"Strategy: {_escape_mdv2(session.strategy_path or '')}\n"
            f"Symbol: {_escape_mdv2(session.symbol or '')}"
            f" / {_escape_mdv2(interval)}\n"
            "Select mode:"
        ),
        parse_mode="MarkdownV2",
        reply_markup={
            "inline_keyboard": [
                [
                    {
                        "text": "\U0001f4ca Dry Run",
                        "callback_data": f"run:{sid}:mode:dry_run",
                    },
                    {
                        "text": "\U0001f9ea Testnet",
                        "callback_data": f"run:{sid}:mode:testnet",
                    },
                ],
                [
                    {
                        "text": "\u26a0 Live",
                        "callback_data": f"run:{sid}:mode:live",
                    },
                ],
            ]
        },
    )


def _run_cb_mode(uc, session, mode: str) -> TelegramCommandResult:
    """User selected a mode — start bot or show live confirmation."""
    if mode == "live":
        return uc._run_cb_mode_live(session)
    return uc._start_bot_from_session(session, mode)


def _run_cb_mode_live(uc, session) -> TelegramCommandResult:
    """Show live trading confirmation prompt."""
    sid = session.session_id
    return TelegramCommandResult(
        text=(
            "\u26a0\ufe0f *LIVE TRADING CONFIRMATION*\n"
            f"Strategy: {_escape_mdv2(session.strategy_path or '')}\n"
            f"Symbol: {_escape_mdv2(session.symbol or '')}"
            f" / {_escape_mdv2(session.interval or '')}\n"
            "Mode: LIVE\n\n"
            "This will place *real orders* on Hyperliquid "
            "with real funds\\.\n"
            "Are you sure?"
        ),
        parse_mode="MarkdownV2",
        reply_markup={
            "inline_keyboard": [
                [
                    {
                        "text": "\u2705 Yes, start live trading",
                        "callback_data": f"run:{sid}:confirm:yes",
                    },
                    {
                        "text": "\u274c Cancel",
                        "callback_data": f"run:{sid}:confirm:no",
                    },
                ],
            ]
        },
    )


def _run_cb_confirm(uc, session, value: str) -> TelegramCommandResult:
    """Handle live trading confirmation."""
    if value == "yes":
        return uc._start_bot_from_session(session, "live")
    else:
        return uc._run_cb_int(session, session.interval or "1h")


def _read_execution_config(uc, strategy_path: str):
    """Parse the optional execution block from a strategy file.

    Returns a StrategyExecutionConfig or None. Best-effort: file read or
    parse errors return None so a malformed block never blocks startup.
    """
    from pathlib import Path

    from finbot.core.domain.services.strategy_execution_parser import (
        parse_strategy_execution,
    )

    try:
        content = Path(strategy_path).read_text(encoding="utf-8")
    except Exception:
        return None
    try:
        return parse_strategy_execution(content)
    except Exception:
        return None


def _start_bot_from_session(uc, session, mode: str) -> TelegramCommandResult:
    """Call bot_manager.start() with the accumulated session state."""
    exec_config = uc._read_execution_config(session.strategy_path or "")
    result = uc._bot_manager.start(
        strategy_path=session.strategy_path or "",
        symbol=session.symbol or "",
        interval=session.interval or "1h",
        mode=mode,
        live_trading_ack=uc._live_trading_ack,
        execution_config=exec_config,
    )

    if result.get("status") != "running":
        return TelegramCommandResult(
            text=(
                "\u274c Failed to start bot: "
                f"{_escape_mdv2(str(result.get('message', 'Unknown error')))}"
                "\\."
            ),
            parse_mode="MarkdownV2",
        )

    run_id = _escape_mdv2(str(result.get("bot_run_id", "")))
    strategy = _escape_mdv2(session.strategy_path or "")
    symbol = _escape_mdv2(session.symbol or "")
    interval = _escape_mdv2(session.interval or "1h")
    if mode == "dry_run":
        return TelegramCommandResult(
            text=(
                "\u2705 *Bot started\\!*\n"
                f"Run ID: {run_id}\n"
                f"Strategy: {strategy}\n"
                f"Symbol: {symbol} / {interval}\n"
                f"Mode: DRY\\_RUN\n\n"
                "No real orders will be placed\\.\n"
                "Use /status to monitor or /stop to halt\\."
            ),
            parse_mode="MarkdownV2",
            reply_markup={
                "inline_keyboard": [
                    [
                        {"text": "Status", "callback_data": "/status"},
                        {"text": "Stop", "callback_data": "/stop"},
                    ],
                ]
            },
        )
    else:
        return TelegramCommandResult(
            text=(
                "\u2705 *Bot started\\!*\n"
                f"Run ID: {run_id}\n"
                f"Strategy: {strategy}\n"
                f"Symbol: {symbol} / {interval}\n"
                f"Mode: {mode.upper()}\n\n"
                "Real orders WILL be placed\\.\n"
                "Use /status to monitor or /stop to halt\\."
            ),
            parse_mode="MarkdownV2",
            reply_markup={
                "inline_keyboard": [
                    [
                        {"text": "Status", "callback_data": "/status"},
                        {"text": "Stop", "callback_data": "/stop"},
                    ],
                ]
            },
        )
