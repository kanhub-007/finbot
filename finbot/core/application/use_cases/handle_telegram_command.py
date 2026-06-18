"""HandleTelegramCommand — central use case for Telegram bot commands."""

from __future__ import annotations

from finbot.core.application.dto.callback_query_request import (
    CallbackQueryRequest,
)
from finbot.core.application.dto.telegram_command_request import (
    TelegramCommandRequest,
)
from finbot.core.application.dto.telegram_command_result import (
    TelegramCommandResult,
)
from finbot.core.application.use_cases.telegram_helpers import (
    _DEFAULT_INTERVALS,
    _DEFAULT_SYMBOLS,
    _escape_mdv2,
    _get_symbols,
    _parse_brackets,
)
from finbot.core.domain.entities.callback_data import CallbackData
from finbot.core.domain.entities.telegram_chat import TelegramChat
from finbot.core.domain.interfaces.bot_manager_port import BotManagerPort
from finbot.core.domain.interfaces.strategy_directory import StrategyDirectory
from finbot.core.domain.interfaces.telegram_chat_repository import (
    TelegramChatRepository,
)
from finbot.core.domain.interfaces.telegram_session_store import (
    TelegramSessionStore,
)


class HandleTelegramCommand:
    """Central use case that routes Telegram commands and callback queries.

    Authorization fails closed: /whoami is always allowed. All other
    commands and callbacks require the user_id to be in the configured
    allowed_users set. When allowed_users is empty, control commands
    are denied with a setup-unconfigured message.
    """

    def __init__(
        self,
        *,
        bot_manager: BotManagerPort,
        chat_repo: TelegramChatRepository,
        strategy_dir: StrategyDirectory,
        session_store: TelegramSessionStore,
        allowed_users: frozenset[int],
        live_trading_ack: bool = False,
        metadata_provider: object | None = None,
    ) -> None:
        self._bot_manager = bot_manager
        self._chat_repo = chat_repo
        self._strategy_dir = strategy_dir
        self._session_store = session_store
        self._allowed_users = allowed_users
        self._live_trading_ack = live_trading_ack
        self._metadata_provider = metadata_provider

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def execute(self, request: TelegramCommandRequest) -> TelegramCommandResult:
        """Route a Telegram command to the appropriate handler."""
        cmd = request.command

        # /whoami is always allowed — no authorization check
        if cmd == "/whoami":
            return self._handle_whoami(request)

        # Authorization check for all other commands
        auth_error = self._authorize(request)
        if auth_error is not None:
            return auth_error

        # Route to handler
        handler = _COMMAND_HANDLERS.get(cmd)
        if handler is not None:
            return await handler(self, request)

        # Unknown command
        return TelegramCommandResult(
            text=f"Unknown command: {cmd}\nUse /help to see available commands\\."
        )

    async def handle_callback(
        self, request: CallbackQueryRequest
    ) -> TelegramCommandResult:
        """Handle an inline-keyboard callback query.

        Callbacks are authorized the same as commands (fail-closed).
        Callback data uses colon-separated format parsed via CallbackData.
        """
        data = CallbackData.parse(request.callback_data)

        # Quick navigation callbacks (no auth needed — just re-route to
        # the command handler which will enforce auth)
        if data.raw in ("/run", "/status", "/history", "/stop", "/help"):
            return await self.execute(
                TelegramCommandRequest(
                    command=data.raw,
                    args="",
                    chat_id=request.chat_id,
                    user_id=request.user_id,
                    message_id=request.message_id,
                )
            )

        # All other callbacks require authorization
        auth_error = self._authorize(request)
        if auth_error is not None:
            return auth_error

        # Run flow callbacks: run:<sid>:<action>:<value>
        if data.has_prefix("run") and data.segment_count >= 4:
            return await self._handle_run_callback(request, data)

        # Panic callbacks
        if data.has_prefix("panic") and data.segment_count >= 2:
            return self._handle_panic_callback(request, data)

        return TelegramCommandResult(
            text="Invalid selection, please start again with /run\\."
        )

    # ------------------------------------------------------------------
    # Authorization
    # ------------------------------------------------------------------

    def _authorize(
        self, request: TelegramCommandRequest | CallbackQueryRequest
    ) -> TelegramCommandResult | None:
        """Check authorization for control commands/callbacks.

        Returns None if authorized, or a TelegramCommandResult with
        the denial message. Fails closed when no users are configured.
        """
        if not self._allowed_users:
            return TelegramCommandResult(
                text="\u26d4 *Telegram control not configured\\.*\n\n"
                     "No authorized users are set in "
                     "FINBOT_TELEGRAM_ALLOWED_USERS\\.\n"
                     "Send /whoami to discover your Telegram user ID, "
                     "then add it to your environment configuration\\.",
                parse_mode="MarkdownV2",
            )

        if request.user_id not in self._allowed_users:
            return TelegramCommandResult(
                text="\u26d4 *Unauthorized\\.*\n"
                     "You are not authorized to control this trading bot\\.\n"
                     "Contact the bot administrator to be added\\.",
                parse_mode="MarkdownV2",
            )

        return None

    # ------------------------------------------------------------------
    # Handlers — Commands
    # ------------------------------------------------------------------

    def _handle_whoami(
        self, request: TelegramCommandRequest
    ) -> TelegramCommandResult:
        """Return the user's Telegram user_id and chat_id.

        Always allowed — no authorization check. This is how operators
        discover their Telegram ID to configure FINBOT_TELEGRAM_ALLOWED_USERS.
        """
        text = (
            "Your Telegram IDs:\n"
            f"User ID: {request.user_id}\n"
            f"Chat ID: {request.chat_id}\n\n"
            "Add this to your environment:\n"
            f"FINBOT_TELEGRAM_ALLOWED_USERS={request.user_id}"
        )
        return TelegramCommandResult(text=text)

    async def _handle_start(
        self, request: TelegramCommandRequest
    ) -> TelegramCommandResult:
        """Register the chat for notifications and return the welcome message."""
        chat = await self._chat_repo.get_chat(request.chat_id)
        if chat is None:
            chat = TelegramChat(
                chat_id=request.chat_id,
                user_id=request.user_id,
                notifications_enabled=True,
            )
            await self._chat_repo.add_chat(chat)

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

    async def _handle_help(
        self, request: TelegramCommandRequest
    ) -> TelegramCommandResult:
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

    async def _handle_status(
        self, request: TelegramCommandRequest
    ) -> TelegramCommandResult:
        """Return the bot's current live status or last run summary."""
        mgr = self._bot_manager
        status = mgr.get_status()
        is_running = status.get("is_running", False)
        if is_running:
            return self._format_running_status(status)
        else:
            return self._format_idle_status(status)

    def _format_running_status(self, status: dict) -> TelegramCommandResult:
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

    def _format_idle_status(self, status: dict) -> TelegramCommandResult:
        """Format the status response when no bot is running."""
        last_run = status.get("last_run")

        lines = [
            "\U0001f4ca *Bot Status*",
            "State: \u23f8 Idle",
            "No bot running\\.",
        ]

        if last_run is not None:
            lines.append("")
            lines.append(
                "*Last Run:* "
                + _escape_mdv2(str(last_run.get("run_id", "")))
            )
            lines.append(
                "Strategy: "
                + _escape_mdv2(str(last_run.get("strategy_name", "")))
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

    async def _handle_stop(
        self, request: TelegramCommandRequest
    ) -> TelegramCommandResult:
        """Stop the running bot and return a summary."""
        stop_result = self._bot_manager.stop()
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

    async def _handle_run(
        self, request: TelegramCommandRequest
    ) -> TelegramCommandResult:
        """Start the guided /run flow or reject if bot is already running."""
        if self._bot_manager.is_running():
            run_id = str(self._bot_manager.get_status().get("bot_run_id", ""))
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

        strategies = self._strategy_dir.list_strategies()
        if not strategies:
            return TelegramCommandResult(
                text="No strategies found\\. Place \\\\.yaml files "
                     "in the strategies directory\\.",
                parse_mode="MarkdownV2",
            )

        # Create a session for the run flow
        session = self._session_store.create(request.chat_id, request.message_id)

        # If user typed "/run BTC", pre-fill symbol to skip the picker
        if request.args.strip():
            session.symbol = request.args.strip().upper()

        sid = session.session_id

        # Build inline keyboard for strategies
        displayed = strategies[:10]
        buttons = []
        for i, s in enumerate(displayed):
            buttons.append(
                {"text": s, "callback_data": f"run:{sid}:strat:{i}"}
            )
        keyboard_rows = []
        for i in range(0, len(buttons), 2):
            keyboard_rows.append(buttons[i : i + 2])

        return TelegramCommandResult(
            text="*Start a Bot*\nSelect a strategy:",
            parse_mode="MarkdownV2",
            reply_markup={"inline_keyboard": keyboard_rows},
        )

    async def _handle_list(
        self, request: TelegramCommandRequest
    ) -> TelegramCommandResult:
        """List available strategy files."""
        strategies = self._strategy_dir.list_strategies()
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

    async def _handle_mute(
        self, request: TelegramCommandRequest
    ) -> TelegramCommandResult:
        """Suppress notifications for this chat."""
        await self._chat_repo.set_notifications(request.chat_id, False)
        return TelegramCommandResult(
            text="\U0001f515 Notifications muted\\. Use /unmute to resume\\.",
            parse_mode="MarkdownV2",
        )

    async def _handle_unmute(
        self, request: TelegramCommandRequest
    ) -> TelegramCommandResult:
        """Resume notifications for this chat."""
        await self._chat_repo.set_notifications(request.chat_id, True)
        return TelegramCommandResult(
            text="\U0001f514 Notifications unmuted\\.",
            parse_mode="MarkdownV2",
        )

    async def _handle_history(
        self, request: TelegramCommandRequest
    ) -> TelegramCommandResult:
        """Show a paginated list of recent bot runs."""
        runs = self._bot_manager.list_bot_runs(limit=5)

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
            lines.append(
                f"{i}\\. {r_id} \u2014 {name} / {sym} / {iv}\n{md}"
            )

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

    async def _handle_panic(
        self, request: TelegramCommandRequest
    ) -> TelegramCommandResult:
        """Emergency panic — show action options or pick symbol first."""
        if self._bot_manager.is_running():
            status = self._bot_manager.get_status()
            symbol = _escape_mdv2(str(status.get("symbol", "")))
            suffix = f" \u2014 {symbol}" if symbol else ""
            return TelegramCommandResult(
                text=f"\U0001f6a8 *EMERGENCY{suffix}*\nSelect action:",
                parse_mode="MarkdownV2",
                reply_markup={
                    "inline_keyboard": [
                        [
                            {
                                "text": "Cancel all orders",
                                "callback_data": f"panic:cancel:{symbol}",
                            },
                            {
                                "text": "Close position",
                                "callback_data": f"panic:close:{symbol}",
                            },
                        ],
                        [
                            {
                                "text": "Both",
                                "callback_data": f"panic:both:{symbol}",
                            },
                            {
                                "text": "\u274c Cancel",
                                "callback_data": "panic:abort",
                            },
                        ],
                    ]
                },
            )
        else:
            # Idle — show symbol picker
            buttons = []
            for sym in _get_symbols(self._metadata_provider)[:30]:
                buttons.append(
                    {"text": sym, "callback_data": f"panic:sym:{sym}"}
                )
            keyboard_rows = []
            for i in range(0, len(buttons), 3):
                keyboard_rows.append(buttons[i : i + 3])

            return TelegramCommandResult(
                text=(
                    "\U0001f6a8 *EMERGENCY*\n"
                    "No bot is currently running, "
                    "so select a symbol first:"
                ),
                parse_mode="MarkdownV2",
                reply_markup={"inline_keyboard": keyboard_rows},
            )

    # ------------------------------------------------------------------
    # Handlers — Callbacks
    # ------------------------------------------------------------------

    async def _handle_run_callback(
        self, request: CallbackQueryRequest, data: CallbackData
    ) -> TelegramCommandResult:
        """Advance the /run guided-flow state machine.

        Callback format: run:<sid>:<action>:<value>
        data.action = session_id, data.value = action, data.subvalue = value
        """
        session_id = data.action  # parts[1]
        action = data.value       # parts[2]
        value = data.subvalue     # parts[3]

        session = self._session_store.get(session_id)
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
            return self._run_cb_strat(session, value)
        elif action == "sym":
            return self._run_cb_sym(session, value)
        elif action == "page":
            return self._render_symbol_page(session, page=int(value))
        elif action == "int":
            return self._run_cb_int(session, value)
        elif action == "mode":
            return self._run_cb_mode(session, value)
        elif action == "confirm":
            return self._run_cb_confirm(session, value)
        else:
            return TelegramCommandResult(
                text="Invalid selection, please start again with /run\\."
            )

    def _render_symbol_page(
        self, session, page: int = 0
    ) -> TelegramCommandResult:
        """Render a paginated symbol picker."""
        _SYMBOLS_PER_PAGE = 6
        symbols = _get_symbols(self._metadata_provider)
        total_pages = (len(symbols) + _SYMBOLS_PER_PAGE - 1) // _SYMBOLS_PER_PAGE
        page = max(0, min(page, total_pages - 1))

        sid = session.session_id
        start = page * _SYMBOLS_PER_PAGE
        page_symbols = symbols[start : start + _SYMBOLS_PER_PAGE]

        # Symbol buttons (2 rows of 3)
        keyboard_rows = []
        row = []
        for sym in page_symbols:
            row.append(
                {"text": sym, "callback_data": f"run:{sid}:sym:{sym}"}
            )
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
        nav_row.append(
            {"text": f"{page + 1}/{total_pages}", "callback_data": "none"}
        )
        if page < total_pages - 1:
            nav_row.append(
                {"text": "Next \u25b6", "callback_data": f"run:{sid}:page:{page + 1}"}
            )
        keyboard_rows.append(nav_row)

        # Search hint row
        keyboard_rows.append([
            {"text": "\u2315 Tip: /run BTC skips this step", "callback_data": "none"}
        ])

        return TelegramCommandResult(
            text=(
                f"Select symbol \\({len(symbols)} available,"
                f" page {page + 1}/{total_pages}\\):"
            ),
            parse_mode="MarkdownV2",
            reply_markup={"inline_keyboard": keyboard_rows},
        )

    def _run_cb_strat(
        self, session, idx_str: str
    ) -> TelegramCommandResult:
        """User selected a strategy — show symbol picker."""
        strategies = self._strategy_dir.list_strategies()
        try:
            idx = int(idx_str)
            strategy_name = strategies[idx]
        except (ValueError, IndexError):
            return TelegramCommandResult(
                text="Invalid strategy selection. "
                     "Please start again with /run\\."
            )

        session.strategy_path = self._strategy_dir.get_strategy_path(
            strategy_name
        )
        self._session_store.save(session)

        # If symbol was pre-filled via "/run BTC", skip the picker
        if session.symbol:
            return self._run_cb_sym(session, session.symbol)

        return self._render_symbol_page(session, page=0)

    def _run_cb_sym(
        self, session, symbol: str
    ) -> TelegramCommandResult:
        """User selected a symbol — show interval picker."""
        session.symbol = symbol
        self._session_store.save(session)

        sid = session.session_id
        buttons = []
        for interval in _DEFAULT_INTERVALS:
            buttons.append(
                {"text": interval, "callback_data": f"run:{sid}:int:{interval}"}
            )
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

    def _run_cb_int(
        self, session, interval: str
    ) -> TelegramCommandResult:
        """User selected an interval — show mode picker."""
        session.interval = interval
        self._session_store.save(session)

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

    def _run_cb_mode(
        self, session, mode: str
    ) -> TelegramCommandResult:
        """User selected a mode — start bot or show live confirmation."""
        if mode == "live":
            return self._run_cb_mode_live(session)
        return self._start_bot_from_session(session, mode)

    def _run_cb_mode_live(self, session) -> TelegramCommandResult:
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

    def _run_cb_confirm(
        self, session, value: str
    ) -> TelegramCommandResult:
        """Handle live trading confirmation."""
        if value == "yes":
            return self._start_bot_from_session(session, "live")
        else:
            return self._run_cb_int(session, session.interval or "1h")

    def _read_execution_config(self, strategy_path: str):
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

    def _start_bot_from_session(
        self, session, mode: str
    ) -> TelegramCommandResult:
        """Call bot_manager.start() with the accumulated session state."""
        exec_config = self._read_execution_config(session.strategy_path or "")
        result = self._bot_manager.start(
            strategy_path=session.strategy_path or "",
            symbol=session.symbol or "",
            interval=session.interval or "1h",
            mode=mode,
            live_trading_ack=self._live_trading_ack,
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

    def _handle_panic_callback(
        self, request: CallbackQueryRequest, data: CallbackData
    ) -> TelegramCommandResult:
        """Handle panic action callbacks."""
        action = data.action
        symbol = data.value

        if action == "sym":
            # User selected a symbol while idle — show action options
            escaped_sym = _escape_mdv2(symbol)
            return TelegramCommandResult(
                text=f"\U0001f6a8 *EMERGENCY \u2014 {escaped_sym}*\nSelect action:",
                parse_mode="MarkdownV2",
                reply_markup={
                    "inline_keyboard": [
                        [
                            {
                                "text": "Cancel all orders",
                                "callback_data": f"panic:cancel:{symbol}",
                            },
                            {
                                "text": "Close position",
                                "callback_data": f"panic:close:{symbol}",
                            },
                        ],
                        [
                            {
                                "text": "Both",
                                "callback_data": f"panic:both:{symbol}",
                            },
                            {
                                "text": "\u274c Cancel",
                                "callback_data": "panic:abort",
                            },
                        ],
                    ]
                },
            )

        if action == "abort":
            return TelegramCommandResult(
                text="Panic cancelled\\.",
                parse_mode="MarkdownV2",
            )

        if action == "exec":
            # Execute the panic action
            return self._panic_execute(data.subvalue, symbol)

        # Action selected — show confirmation
        action_label = {
            "cancel": "Cancel all orders",
            "close": "Close position",
            "both": "Cancel all orders \\+ close position",
        }.get(action, action)

        return TelegramCommandResult(
            text=(
                "\u26a0\ufe0f *PANIC CONFIRMATION*\n"
                f"This will: {_escape_mdv2(action_label)} for"
                f" {_escape_mdv2(symbol)}\n"
                "Are you sure?"
            ),
            parse_mode="MarkdownV2",
            reply_markup={
                "inline_keyboard": [
                    [
                        {
                            "text": "\u2705 Confirm panic",
                            "callback_data": f"panic:exec:{symbol}:{action}",
                        },
                        {
                            "text": "\u274c Cancel",
                            "callback_data": "panic:abort",
                        },
                    ],
                ]
            },
        )

    def _panic_execute(self, action: str, symbol: str) -> TelegramCommandResult:
        """Execute the panic action: cancel orders, close position, or both."""
        mgr = self._bot_manager
        cancelled = 0
        position_closed = False

        if action in ("cancel", "both"):
            cancel_result = mgr.cancel_all_orders(symbol)
            if "error" not in cancel_result:
                cancelled = len(cancel_result) if isinstance(cancel_result, dict) else 0

        if action in ("close", "both"):
            close_result = mgr.close_position(symbol)
            if "error" not in close_result:
                position_closed = True

        # Stop the bot after panic
        self._bot_manager.stop()

        text_lines = [
            "\U0001f6a8 *PANIC executed:*",
        ]
        if action in ("cancel", "both"):
            text_lines.append(f"\u2022 Orders cancelled: {cancelled}")
        if action in ("close", "both"):
            status = "closed" if position_closed else "failed to close"
            text_lines.append(f"\u2022 Position {status}")
        text_lines.append("Bot has been stopped\\.")

        return TelegramCommandResult(
            text="\n".join(text_lines),
            parse_mode="MarkdownV2",
        )

    # ------------------------------------------------------------------
    # trading-control spec handlers
    # ------------------------------------------------------------------

    async def _handle_symbol(self, request: TelegramCommandRequest):
        """Activate a symbol (reads exchange leverage, no overwrite)."""
        args = request.args.strip()
        if not args:
            symbols = _get_symbols(getattr(self, "_metadata_provider", None))
            if not symbols:
                return TelegramCommandResult(text="No symbols available\\.")
            return self._render_symbol_picker(symbols, page=0)
        result = self._bot_manager.activate_symbol(args.split()[0].upper())
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

    def _render_symbol_picker(self, symbols, page=0):
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

    async def _handle_price(self, request: TelegramCommandRequest):
        """Show the current price for the active symbol."""
        active = self._bot_manager.get_active_symbol()
        if active is None:
            return TelegramCommandResult(
                text="No symbol selected\\. Use /symbol first\\.",
                parse_mode="MarkdownV2",
            )
        try:
            price = self._bot_manager.get_active_price()
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

    async def _handle_balance(self, request: TelegramCommandRequest):
        """Show wallet balance."""
        bal = self._bot_manager.get_balance()
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

    async def _handle_leverage(self, request: TelegramCommandRequest):
        """View or set leverage on the active symbol."""
        active = self._bot_manager.get_active_symbol()
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
        result = self._bot_manager.set_leverage(lev, mm)
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

    async def _handle_position(self, request: TelegramCommandRequest):
        """Show the current position + PnL for the active symbol."""
        active = self._bot_manager.get_active_symbol()
        if active is None:
            return TelegramCommandResult(
                text="No symbol selected\\. Use /symbol first\\.",
                parse_mode="MarkdownV2",
            )
        pos = self._bot_manager.get_active_position()
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

    async def _handle_long(self, request: TelegramCommandRequest):
        """Open a long position on the active symbol."""
        return await self._manual_entry(request, "buy")

    async def _handle_short(self, request: TelegramCommandRequest):
        """Open a short position on the active symbol."""
        return await self._manual_entry(request, "sell")

    async def _manual_entry(self, request, side):
        """Shared /long + /short flow: parse size + optional sl/tp brackets."""
        from decimal import Decimal

        from finbot.core.domain.entities.order_side import OrderSide

        active = self._bot_manager.get_active_symbol()
        if active is None:
            return TelegramCommandResult(
                text="No symbol selected\\. Use /symbol first\\.",
                parse_mode="MarkdownV2",
            )
        args = request.args.strip().split()
        if not args:
            cmd = "long" if side == "buy" else "short"
            return TelegramCommandResult(
                text=f"Usage: /{cmd} SIZE \\[sl PRICE\\] \\[tp PRICE\\]",
                parse_mode="MarkdownV2",
            )
        try:
            size = Decimal(args[0])
        except Exception:
            return TelegramCommandResult(
                text="Invalid size\\.", parse_mode="MarkdownV2"
            )
        # Optional bracket orders: "sl <price>" and "tp <price>"
        sl_price, tp_price, parse_err = _parse_brackets(args[1:])
        if parse_err is not None:
            return TelegramCommandResult(
                text=f"\u274c {_escape_mdv2(parse_err)}", parse_mode="MarkdownV2"
            )
        order_side = OrderSide.BUY if side == "buy" else OrderSide.SELL
        if sl_price is not None or tp_price is not None:
            result = self._bot_manager.submit_manual_order_with_brackets(
                order_side, size, sl_price=sl_price, tp_price=tp_price
            )
        else:
            result = self._bot_manager.submit_manual_order(order_side, size)
        if result.get("status") != "ok":
            return TelegramCommandResult(
                text=f"\u274c {_escape_mdv2(str(result.get('message', 'Rejected')))}",
                parse_mode="MarkdownV2",
            )
        extras = []
        if sl_price is not None:
            extras.append(f"SL={_escape_mdv2(str(sl_price))}")
        if tp_price is not None:
            extras.append(f"TP={_escape_mdv2(str(tp_price))}")
        extra_str = f" \\[{_escape_mdv2(' '.join(extras))}\\]" if extras else ""
        warnings = result.get("warnings") or []
        warn_text = ""
        if warnings:
            warn_text = "\n" + "\n".join(
                f"\u26a0\ufe0f {_escape_mdv2(w)}" for w in warnings
            )
        return TelegramCommandResult(
            text=(
                f"\u2705 {_escape_mdv2(active.symbol)} "
                f"{_escape_mdv2(str(size))} @ market{extra_str}{warn_text}"
            ),
            parse_mode="MarkdownV2",
        )

    async def _handle_close(self, request: TelegramCommandRequest):
        """Close the active position (reduce-only, clears SL/TP)."""
        result = self._bot_manager.close_active_position()
        if result.get("status") != "ok":
            return TelegramCommandResult(
                text=f"\u274c {_escape_mdv2(str(result.get('message', 'Rejected')))}",
                parse_mode="MarkdownV2",
            )
        return TelegramCommandResult(
            text="\u2705 Position closed\\.", parse_mode="MarkdownV2"
        )

    async def _handle_clear(self, request: TelegramCommandRequest):
        """Cancel all orders + close all positions (idle only)."""
        result = self._bot_manager.clear_all()
        if result.get("status") != "ok":
            return TelegramCommandResult(
                text=f"\u274c {_escape_mdv2(str(result.get('message', 'Rejected')))}",
                parse_mode="MarkdownV2",
            )
        return TelegramCommandResult(
            text=(
                "\U0001f9f9 Clear All\n"
                f"Cancelled orders: {result.get('cancelled_orders', 0)}\n"
                f"Closed positions: {result.get('closed_positions', 0)}"
            ),
            parse_mode="MarkdownV2",
        )

    async def _handle_sl(self, request: TelegramCommandRequest):
        """Attach or clear a stop-loss trigger order."""
        return await self._risk_order(request, "sl")

    async def _handle_tp(self, request: TelegramCommandRequest):
        """Attach or clear a take-profit trigger order."""
        return await self._risk_order(request, "tp")

    async def _risk_order(self, request, kind):
        """Shared /sl + /tp flow."""
        from decimal import Decimal

        active = self._bot_manager.get_active_symbol()
        if active is None:
            return TelegramCommandResult(
                text="No symbol selected\\. Use /symbol first\\.",
                parse_mode="MarkdownV2",
            )
        arg = request.args.strip()
        if arg.lower() == "clear":
            result = self._bot_manager.clear_risk_order(kind)
            if result.get("status") != "ok":
                return TelegramCommandResult(
                    text=f"\u274c {_escape_mdv2(str(result.get('message', 'Rejected')))}",
                    parse_mode="MarkdownV2",
                )
            return TelegramCommandResult(
                text=f"\u2705 {kind.upper()} cleared\\.", parse_mode="MarkdownV2"
            )
        if not arg:
            return TelegramCommandResult(
                text=f"Usage: /{kind} PRICE  \\(or /{kind} clear\\)",
                parse_mode="MarkdownV2",
            )
        try:
            price = Decimal(arg)
        except Exception:
            return TelegramCommandResult(
                text="Invalid price\\.", parse_mode="MarkdownV2"
            )
        method = (
            self._bot_manager.attach_stop_loss
            if kind == "sl"
            else self._bot_manager.attach_take_profit
        )
        result = method(price)
        if result.get("status") != "ok":
            return TelegramCommandResult(
                text=f"\u274c {_escape_mdv2(str(result.get('message', 'Rejected')))}",
                parse_mode="MarkdownV2",
            )
        return TelegramCommandResult(
            text=f"\u2705 {kind.upper()} set @ {_escape_mdv2(str(price))}\\.",
            parse_mode="MarkdownV2",
        )

    async def _handle_config(self, request: TelegramCommandRequest):
        """View or adjust runtime config, or manage named profiles."""
        args = request.args.strip().split(maxsplit=1)
        if not args:
            return self._render_config_view()
        key = args[0]
        # Profile subcommand: /config profile save|load|list [NAME]
        if key == "profile":
            return await self._handle_config_profile(args[1] if len(args) > 1 else "")
        if len(args) < 2:
            return TelegramCommandResult(
                text=f"Usage: /config {key} VALUE", parse_mode="MarkdownV2"
            )
        result = self._bot_manager.update_bot_config(key, args[1])
        if result.get("status") != "ok":
            return TelegramCommandResult(
                text=f"\u274c {_escape_mdv2(str(result.get('message', 'Rejected')))}",
                parse_mode="MarkdownV2",
            )
        return TelegramCommandResult(
            text=f"\u2705 {_escape_mdv2(key)} = {_escape_mdv2(args[1])}",
            parse_mode="MarkdownV2",
        )

    def _render_config_view(self):
        """Format the current config values for /config with no args."""
        cfg = self._bot_manager.get_bot_config()
        return TelegramCommandResult(
            text=(
                "\u2699\ufe0f Configuration\n"
                f"max_position: {_escape_mdv2(str(cfg.max_position_usd))} USD\n"
                f"daily_loss: {_escape_mdv2(str(cfg.max_daily_loss_usd))} USD\n"
                f"max_orders: {_escape_mdv2(str(cfg.max_open_orders))}\n"
                f"stale_data: {_escape_mdv2(str(cfg.stale_data_seconds))}s\n"
            ),
            parse_mode="MarkdownV2",
        )

    async def _handle_config_profile(self, rest: str):
        """Handle /config profile save|load|list [NAME]."""
        parts = rest.split(maxsplit=1)
        if not parts or not parts[0]:
            return TelegramCommandResult(
                text="Usage: /config profile save\\|load\\|list NAME",
                parse_mode="MarkdownV2",
            )
        sub = parts[0].lower()
        if sub == "list":
            result = self._bot_manager.list_config_profiles()
            names = result.get("profiles", [])
            shown = ", ".join(names) if names else "none"
            return TelegramCommandResult(
                text=f"Profiles: {_escape_mdv2(shown)}",
                parse_mode="MarkdownV2",
            )
        if len(parts) < 2:
            return TelegramCommandResult(
                text=f"Usage: /config profile {sub} NAME", parse_mode="MarkdownV2"
            )
        name = parts[1].strip()
        if sub == "save":
            result = self._bot_manager.save_config_profile(name)
        elif sub == "load":
            result = self._bot_manager.load_config_profile(name)
        else:
            return TelegramCommandResult(
                text=f"Unknown subcommand: {_escape_mdv2(sub)}\\. Use save/load/list\\.",
                parse_mode="MarkdownV2",
            )
        if result.get("status") != "ok":
            return TelegramCommandResult(
                text=f"\u274c {_escape_mdv2(str(result.get('message', 'Rejected')))}",
                parse_mode="MarkdownV2",
            )
        return TelegramCommandResult(
            text=f"\u2705 Profile {_escape_mdv2(name)} {sub}d\\.",
            parse_mode="MarkdownV2",
        )
    async def _handle_size(self, request: TelegramCommandRequest):
        """Set, view, or clear the default order size."""
        from decimal import Decimal

        arg = request.args.strip()
        if not arg:
            current = self._bot_manager.get_default_size()
            val = "not set" if current is None else str(current)
            return TelegramCommandResult(
                text=f"Default size: {val}\n"
                f"Set: /size 0\\.1  \\(or /size clear\\)",
                parse_mode="MarkdownV2",
            )
        if arg.lower() == "clear":
            self._bot_manager.clear_default_size()
            return TelegramCommandResult(
                text="\u2705 Default size cleared\\.", parse_mode="MarkdownV2"
            )
        try:
            size = Decimal(arg)
        except Exception:
            return TelegramCommandResult(
                text="Invalid size\\.", parse_mode="MarkdownV2"
            )
        result = self._bot_manager.set_default_size(size)
        if result.get("status") != "ok":
            return TelegramCommandResult(
                text=f"\u274c {_escape_mdv2(str(result.get('message', 'Rejected')))}",
                parse_mode="MarkdownV2",
            )
        return TelegramCommandResult(
            text=f"\u2705 Default size: {_escape_mdv2(str(size))}",
            parse_mode="MarkdownV2",
        )

    async def _handle_orders(self, request: TelegramCommandRequest):
        """List open orders for the active symbol."""
        active = self._bot_manager.get_active_symbol()
        if active is None:
            return TelegramCommandResult(
                text="No symbol selected\\. Use /symbol first\\.",
                parse_mode="MarkdownV2",
            )
        orders = self._bot_manager.list_active_orders()
        if not orders:
            return TelegramCommandResult(
                text=f"No open orders on {_escape_mdv2(active.symbol)}\\.",
                parse_mode="MarkdownV2",
            )
        lines = [f"\U0001f4cb Open Orders ({_escape_mdv2(active.symbol)})"]
        for o in orders:
            oid = _escape_mdv2(str(o.get("oid", o.get("cloid", ""))))
            side = _escape_mdv2(str(o.get("side", "")))
            sz = _escape_mdv2(str(o.get("sz", "")))
            px = _escape_mdv2(str(o.get("limit_px", "")))
            lines.append(f"\\#{oid} {side} {sz} @ {px}")
        return TelegramCommandResult(
            text="\n".join(lines), parse_mode="MarkdownV2"
        )

    async def _handle_cancel(self, request: TelegramCommandRequest):
        """Cancel a single order by oid on the active symbol."""
        active = self._bot_manager.get_active_symbol()
        if active is None:
            return TelegramCommandResult(
                text="No symbol selected\\. Use /symbol first\\.",
                parse_mode="MarkdownV2",
            )
        arg = request.args.strip()
        if not arg:
            return TelegramCommandResult(
                text="Usage: /cancel ORDER\\_ID", parse_mode="MarkdownV2"
            )
        # Strip leading # if user pasted from /orders output
        order_id = arg.lstrip("#")
        result = self._bot_manager.cancel_order(order_id)
        if result.get("status") != "ok":
            return TelegramCommandResult(
                text=f"\u274c {_escape_mdv2(str(result.get('message', 'Rejected')))}",
                parse_mode="MarkdownV2",
            )
        return TelegramCommandResult(
            text=f"\u2705 Cancelled order {_escape_mdv2(order_id)}\\.",
            parse_mode="MarkdownV2",
        )


# Command routing table (references handler methods defined above).
# Helpers (_escape_mdv2, _get_symbols, _parse_brackets, _DEFAULT_*) live in
# finbot.core.application.use_cases.telegram_helpers.

_COMMAND_HANDLERS: dict[str, object] = {
    "/start": HandleTelegramCommand._handle_start,
    "/help": HandleTelegramCommand._handle_help,
    "/status": HandleTelegramCommand._handle_status,
    "/stop": HandleTelegramCommand._handle_stop,
    "/run": HandleTelegramCommand._handle_run,
    "/list": HandleTelegramCommand._handle_list,
    "/history": HandleTelegramCommand._handle_history,
    "/panic": HandleTelegramCommand._handle_panic,
    "/mute": HandleTelegramCommand._handle_mute,
    "/unmute": HandleTelegramCommand._handle_unmute,
    # -- trading-control spec --
    "/symbol": HandleTelegramCommand._handle_symbol,
    "/price": HandleTelegramCommand._handle_price,
    "/balance": HandleTelegramCommand._handle_balance,
    "/leverage": HandleTelegramCommand._handle_leverage,
    "/position": HandleTelegramCommand._handle_position,
    "/long": HandleTelegramCommand._handle_long,
    "/short": HandleTelegramCommand._handle_short,
    "/close": HandleTelegramCommand._handle_close,
    "/clear": HandleTelegramCommand._handle_clear,
    "/sl": HandleTelegramCommand._handle_sl,
    "/tp": HandleTelegramCommand._handle_tp,
    "/config": HandleTelegramCommand._handle_config,
    "/size": HandleTelegramCommand._handle_size,
    "/orders": HandleTelegramCommand._handle_orders,
    "/cancel": HandleTelegramCommand._handle_cancel,
}
