"""Extracted Telegram command handlers — telegram_run_flow (S8 decomposition)."""

from __future__ import annotations

from finbot.core.application.dto.callback_query_request import CallbackQueryRequest
from finbot.core.application.dto.telegram_command_request import (
    TelegramCommandRequest,
)
from finbot.core.application.dto.telegram_command_result import (
    TelegramCommandResult,
)
from finbot.core.application.use_cases.telegram_helpers import (
    _DEFAULT_INTERVALS,
    _escape_mdv2,
    _get_symbol_groups,
    _normalize_symbol,
)
from finbot.core.domain.entities.callback_data import CallbackData


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

    # If user typed "/run BTC" or "/run flx:TSLA", pre-fill symbol to skip
    # the picker. HIP-3 DEX names stay lowercase while coins are uppercased.
    if request.args.strip():
        try:
            session.symbol = _normalize_symbol(request.args)
        except ValueError:
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
    if action == "sym" and data.segment_count > 4:
        value = ":".join(data.parts[3:])
    # Risk callbacks have 5 segments: run:sid:risk:pct:5 or run:sid:risk:lev:10
    if action == "risk" and data.segment_count > 4:
        value = ":".join(data.parts[3:])

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
    elif action == "symtype":
        return uc._render_symbol_page(session, page=0, symbol_type=value)
    elif action == "symidx":
        return uc._run_cb_symidx(session, value)
    elif action == "page":
        symbol_type, page = _parse_symbol_page_value(value)
        return uc._render_symbol_page(session, page=page, symbol_type=symbol_type)
    elif action == "int":
        return uc._run_cb_int(session, value)
    elif action == "risk":
        return _run_cb_risk(uc, session, value)
    elif action == "mode":
        return uc._run_cb_mode(session, value)
    elif action == "confirm":
        return uc._run_cb_confirm(session, value)
    else:
        return TelegramCommandResult(
            text="Invalid selection, please start again with /run\\."
        )


def _render_symbol_type_menu(uc, session) -> TelegramCommandResult:
    """Render the crypto-vs-HIP-3 symbol category picker."""
    crypto_symbols, hip3_symbols = _get_symbol_groups(uc._metadata_provider)
    sid = session.session_id
    return TelegramCommandResult(
        text=(
            "Select perp market type:\n"
            f"• Crypto perps: {len(crypto_symbols)} symbols\n"
            f"• HIP\\-3 perps: {len(hip3_symbols)} symbols"
        ),
        parse_mode="MarkdownV2",
        reply_markup={
            "inline_keyboard": [
                [
                    {
                        "text": f"Crypto perps ({len(crypto_symbols)})",
                        "callback_data": f"run:{sid}:symtype:crypto",
                    },
                ],
                [
                    {
                        "text": f"HIP-3 perps ({len(hip3_symbols)})",
                        "callback_data": f"run:{sid}:symtype:hip3",
                    },
                ],
            ]
        },
    )


def _render_symbol_page(
    uc, session, page: int = 0, symbol_type: str = "crypto"
) -> TelegramCommandResult:
    """Render a paginated symbol picker for one market type."""
    symbols_per_page = 6
    symbols = _symbols_for_type(uc._metadata_provider, symbol_type)
    total_pages = max(1, (len(symbols) + symbols_per_page - 1) // symbols_per_page)
    page = max(0, min(page, total_pages - 1))

    sid = session.session_id
    start = page * symbols_per_page
    page_symbols = symbols[start : start + symbols_per_page]

    keyboard_rows = []
    row = []
    for idx, sym in enumerate(page_symbols, start=start):
        row.append(
            {"text": sym, "callback_data": f"run:{sid}:symidx:{symbol_type},{idx}"}
        )
        if len(row) == 3:
            keyboard_rows.append(row)
            row = []
    if row:
        keyboard_rows.append(row)

    nav_row = []
    if page > 0:
        nav_row.append(
            {
                "text": "\u25c0 Prev",
                "callback_data": f"run:{sid}:page:{symbol_type},{page - 1}",
            }
        )
    nav_row.append({"text": f"{page + 1}/{total_pages}", "callback_data": "none"})
    if page < total_pages - 1:
        nav_row.append(
            {
                "text": "Next \u25b6",
                "callback_data": f"run:{sid}:page:{symbol_type},{page + 1}",
            }
        )
    keyboard_rows.append(nav_row)
    keyboard_rows.append(
        [{"text": "\u21a9 Market type", "callback_data": f"run:{sid}:strat:current"}]
    )
    keyboard_rows.append(
        [{"text": "\u2315 Tip: /run flx:TSLA skips this step", "callback_data": "none"}]
    )

    return TelegramCommandResult(
        text=(
            f"Select {_symbol_type_label(symbol_type)} symbol "
            f"\\({len(symbols)} available, page {page + 1}/{total_pages}\\):"
        ),
        parse_mode="MarkdownV2",
        reply_markup={"inline_keyboard": keyboard_rows},
    )


def _symbols_for_type(
    metadata_provider: object | None, symbol_type: str
) -> tuple[str, ...]:
    """Return symbols for the requested Telegram market category."""
    crypto_symbols, hip3_symbols = _get_symbol_groups(metadata_provider)
    return hip3_symbols if symbol_type == "hip3" else crypto_symbols


def _symbol_type_label(symbol_type: str) -> str:
    """Return a display label for a symbol category."""
    return "HIP\\-3 perp" if symbol_type == "hip3" else "crypto perp"


def _read_symbol_max_leverage(uc, symbol: str) -> int:
    """Return the exchange max leverage for *symbol*, or 0 if unknown."""
    if not symbol:
        return 0
    provider = getattr(uc, "_metadata_provider", None)
    if provider is None:
        return 0
    try:
        meta = provider.get_metadata(symbol)
    except Exception:
        return 0
    return int(getattr(meta, "max_leverage", 0)) if meta else 0


def _parse_symbol_page_value(value: str) -> tuple[str, int]:
    """Parse ``<symbol_type>,<page>`` with backward-compatible page-only input."""
    if "," not in value:
        return "crypto", int(value)
    symbol_type, page_text = value.split(",", maxsplit=1)
    return symbol_type, int(page_text)


def _parse_symbol_index_value(value: str) -> tuple[str, int]:
    """Parse ``<symbol_type>,<index>`` from callback data."""
    symbol_type, idx_text = value.split(",", maxsplit=1)
    return symbol_type, int(idx_text)


def _run_cb_strat(uc, session, idx_str: str) -> TelegramCommandResult:
    """User selected a strategy — show symbol type or symbol picker."""
    if idx_str != "current":
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

    # If symbol was pre-filled via "/run BTC" or "/run flx:TSLA", skip picker.
    if session.symbol:
        return uc._run_cb_sym(session, session.symbol)

    crypto_symbols, hip3_symbols = _get_symbol_groups(uc._metadata_provider)
    if crypto_symbols and hip3_symbols:
        return uc._render_symbol_type_menu(session)
    return uc._render_symbol_page(
        session, page=0, symbol_type="hip3" if hip3_symbols else "crypto"
    )


def _run_cb_symidx(uc, session, value: str) -> TelegramCommandResult:
    """Resolve an indexed symbol callback, then show interval picker."""
    symbol_type, idx = _parse_symbol_index_value(value)
    symbols = _symbols_for_type(uc._metadata_provider, symbol_type)
    try:
        symbol = symbols[idx]
    except IndexError:
        return TelegramCommandResult(
            text="Invalid symbol selection. Please start again with /run\\."
        )
    return uc._run_cb_sym(session, symbol)


def _run_cb_sym(uc, session, symbol: str) -> TelegramCommandResult:
    """User selected a symbol — show interval picker, or skip to mode
    picker when the strategy declares MTF timeframes."""
    session.symbol = _normalize_symbol(symbol)

    # Check for MTF timeframes in the strategy YAML (Scenario 4 / ADR-10).
    # When the strategy declares a ``timeframes`` block, the interval
    # picker is skipped and the user goes to risk config, then mode picker.
    # Delegates to the injected StrategyDefinitionLoader so YAML/file I/O
    # stays in infrastructure, not the application layer.
    tf = _read_strategy_timeframes(uc, session.strategy_path or "")
    if tf is not None:
        primary, informatives = tf
        session.interval = primary
        session._informative_intervals = list(informatives)
        uc._session_store.save(session)
        return _show_risk_config(uc, session, primary, informatives)

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


def _read_strategy_timeframes(uc, path: str) -> tuple[str, list[str]] | None:
    """Parse the ``timeframes`` block via the injected strategy loader.

    Returns ``(primary, informatives)`` when the strategy has a
    ``timeframes`` block with at least a primary interval; ``None``
    otherwise.  Delegates to ``uc._strategy_loader.parse_timeframes()``
    so all YAML/file I/O stays in infrastructure.
    """
    if not path:
        return None
    loader = getattr(uc, "_strategy_loader", None)
    if loader is None:
        return None
    try:
        content = loader.load_content(path)
    except Exception:
        return None
    try:
        tf = loader.parse_timeframes(content)
    except Exception:
        return None
    if tf is None:
        return None
    informatives = list(tf.informative_intervals)
    return (tf.primary or "", informatives)


# -- risk config step --------------------------------------------------------

_RISK_PRESETS = ((3, "3%"), (5, "5%"), (10, "10%"))
_LEV_PRESETS = ((5, "5x"), (10, "10x"), (20, "20x"))


def _show_risk_config(
    uc, session, interval: str, informatives: list[str]
) -> TelegramCommandResult:
    """Show risk-percentage and leverage picker before the mode picker.

    Risk is applied to the total USD balance (not the leveraged amount).
    The selected values are stored in *session* and forwarded to
    ``bot_manager.start()`` via ``_start_bot_from_session``.

    Leverage presets are capped to the symbol's exchange max.  If the
    currently-selected leverage exceeds the max (e.g. user changed
    symbol after picking leverage), it is clamped down.
    """
    sid = session.session_id
    tf_display = interval
    if informatives:
        tf_display = f"{interval} + {' + '.join(informatives)}"

    risk_label = f"{session.risk_pct}%"

    # Read the symbol's max leverage from exchange metadata.
    max_lev = _read_symbol_max_leverage(uc, session.symbol or "")
    if max_lev > 0 and session.leverage > max_lev:
        session.leverage = max_lev
        uc._session_store.save(session)
    lev_label = f"{session.leverage}x"
    if max_lev > 0:
        lev_label += f" (max {max_lev}x)"

    # Build keyboard: risk presets row, leverage presets row, continue.
    risk_row: list[dict] = []
    for pct, label in _RISK_PRESETS:
        sel = " \u2705" if session.risk_pct == pct else ""
        risk_row.append(
            {
                "text": f"{label}{sel}",
                "callback_data": f"run:{sid}:risk:pct:{pct}",
            }
        )

    lev_row: list[dict] = []
    for lev, label in _LEV_PRESETS:
        if max_lev > 0 and lev > max_lev:
            continue  # skip presets above the symbol's max
        sel = " \u2705" if session.leverage == lev else ""
        lev_row.append(
            {
                "text": f"{label}{sel}",
                "callback_data": f"run:{sid}:risk:lev:{lev}",
            }
        )

    return TelegramCommandResult(
        text=(
            f"Strategy: {_escape_mdv2(session.strategy_path or '')}\n"
            f"Symbol: {_escape_mdv2(session.symbol or '')}"
            f" / {_escape_mdv2(tf_display)}\n\n"
            f"*Risk per trade:* {risk_label} of balance\n"
            f"*Leverage:* {lev_label}\n\n"
            "Risk is applied to total USD balance, not the leveraged amount\\."
        ),
        parse_mode="MarkdownV2",
        reply_markup={
            "inline_keyboard": [
                risk_row,
                lev_row,
                [
                    {
                        "text": "\u25b6 Continue",
                        "callback_data": f"run:{sid}:risk:done",
                    },
                ],
            ]
        },
    )


def _run_cb_risk(uc, session, value: str) -> TelegramCommandResult:
    """Handle risk-config callbacks: pct:<N>, lev:<N>, done."""
    informatives = getattr(session, "_informative_intervals", []) or []
    interval = session.interval or "1h"

    if value.startswith("pct:"):
        try:
            session.risk_pct = int(value.split(":", 1)[1])
        except (ValueError, IndexError):
            pass
        uc._session_store.save(session)
        return _show_risk_config(uc, session, interval, informatives)

    if value.startswith("lev:"):
        try:
            session.leverage = int(value.split(":", 1)[1])
        except (ValueError, IndexError):
            pass
        uc._session_store.save(session)
        return _show_risk_config(uc, session, interval, informatives)

    if value == "done":
        return _show_mode_picker_with_timeframes(session, interval, informatives)

    # Unknown sub-action — re-render.
    return _show_risk_config(uc, session, interval, informatives)


def _show_mode_picker_with_timeframes(
    session, interval: str, informatives: list[str]
) -> TelegramCommandResult:
    """Show the mode picker with timeframe info (MTF skip path)."""
    sid = session.session_id
    tf_display = interval
    if informatives:
        tf_display = f"{interval} + {' + '.join(informatives)}"
    return TelegramCommandResult(
        text=(
            f"Strategy: {_escape_mdv2(session.strategy_path or '')}\n"
            f"Symbol: {_escape_mdv2(session.symbol or '')}"
            f" / {_escape_mdv2(tf_display)}\n"
            "Select mode:"
        ),
        parse_mode="MarkdownV2",
        reply_markup=_build_mode_picker_keyboard(sid),
    )


def _run_cb_int(uc, session, interval: str) -> TelegramCommandResult:
    """User selected an interval — show risk config, then mode picker."""
    session.interval = interval
    uc._session_store.save(session)
    return _show_risk_config(uc, session, interval, [])


def _build_mode_picker_keyboard(sid: str) -> dict:
    """Build the shared Dry Run / Testnet / Live mode picker keyboard."""
    return {
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
    }


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
    Delegates file I/O to the injected strategy loader so the application
    layer has no filesystem dependency.
    """
    from finbot.core.domain.services.strategy_execution_parser import (
        parse_strategy_execution,
    )

    loader = getattr(uc, "_strategy_loader", None)
    if loader is None:
        return None
    try:
        content = loader.load_content(strategy_path)
    except Exception:
        return None
    try:
        return parse_strategy_execution(content)
    except Exception:
        return None


def _start_bot_from_session(uc, session, mode: str) -> TelegramCommandResult:
    """Call bot_manager.start() with the accumulated session state.

    Before starting: applies the risk% and leverage selections from the
    /run flow by updating the runtime config and setting leverage on the
    active symbol.
    """
    # Apply risk% → max_position_usd on the runtime config.
    # Risk is on total USD balance, not the leveraged amount.
    if session.risk_pct > 0:
        bal = uc._bot_manager.get_balance()
        if bal is not None:
            max_usd = bal.wallet_value * session.risk_pct // 100
            uc._bot_manager.update_bot_config("max_position", str(max_usd))

    # Set leverage on the active symbol.
    if session.leverage > 0:
        sym_result = uc._bot_manager.activate_symbol(session.symbol or "")
        if sym_result.get("status") not in ("active", "ok"):
            return TelegramCommandResult(
                text=f"\u274c Cannot activate {_escape_mdv2(session.symbol or '')}: "
                     f"{_escape_mdv2(str(sym_result.get('message', 'unknown')))}",
                parse_mode="MarkdownV2",
            )
        lev_result = uc._bot_manager.set_leverage(session.leverage, "isolated")
        if lev_result.get("status") != "ok":
            return TelegramCommandResult(
                text=f"\u274c Cannot set {session.leverage}x leverage: "
                     f"{_escape_mdv2(str(lev_result.get('message', 'unknown')))}",
                parse_mode="MarkdownV2",
            )

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
