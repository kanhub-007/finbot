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
    ) -> None:
        self._bot_manager = bot_manager
        self._chat_repo = chat_repo
        self._strategy_dir = strategy_dir
        self._session_store = session_store
        self._allowed_users = allowed_users
        self._live_trading_ack = live_trading_ack

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
            f"Signals: {total_signals} | Orders: {total_orders} "
            f"| Fills: {total_fills}"
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
            for sym in _DEFAULT_SYMBOLS:
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

        session.strategy_path = strategy_name
        self._session_store.save(session)

        sid = session.session_id
        buttons = []
        for sym in _DEFAULT_SYMBOLS:
            buttons.append(
                {"text": sym, "callback_data": f"run:{sid}:sym:{sym}"}
            )
        keyboard_rows = []
        for i in range(0, len(buttons), 3):
            keyboard_rows.append(buttons[i : i + 3])

        return TelegramCommandResult(
            text=f"Strategy: {_escape_mdv2(strategy_name)}\nSelect symbol:",
            parse_mode="MarkdownV2",
            reply_markup={"inline_keyboard": keyboard_rows},
        )

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

    def _start_bot_from_session(
        self, session, mode: str
    ) -> TelegramCommandResult:
        """Call bot_manager.start() with the accumulated session state."""
        result = self._bot_manager.start(
            strategy_path=session.strategy_path or "",
            symbol=session.symbol or "",
            interval=session.interval or "1h",
            mode=mode,
            live_trading_ack=self._live_trading_ack,
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
# Module constants
# ------------------------------------------------------------------

_DEFAULT_SYMBOLS = ("BTC", "ETH", "SOL", "ARB", "DOGE")
_DEFAULT_INTERVALS = ("1m", "5m", "15m", "1h", "4h", "1d")

# Characters that MUST be escaped in Telegram MarkdownV2.
# See: https://core.telegram.org/bots/api#markdownv2-style
_MDV2_ESCAPE_CHARS = str.maketrans({
    '_': '\\_', '*': '\\*', '[': '\\[', ']': '\\]',
    '(': '\\(', ')': '\\)', '~': '\\~', '`': '\\`',
    '>': '\\>', '#': '\\#', '+': '\\+', '-': '\\-',
    '=': '\\=', '|': '\\|', '{': '\\{', '}': '\\}',
    '.': '\\.', '!': '\\!',
})


def _escape_mdv2(text: str) -> str:
    """Escape special characters for Telegram MarkdownV2."""
    return str(text).translate(_MDV2_ESCAPE_CHARS)

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
}
