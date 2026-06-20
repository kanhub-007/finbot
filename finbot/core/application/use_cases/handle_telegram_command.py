"""HandleTelegramCommand — central use case for Telegram bot commands.

Routes commands via a module-level handler table.  The 40+ thin
delegator methods that forwarded ``_handle_xxx(self, request)`` to
``_handle_xxx(self, request)`` (the module-level function) have been
removed — the routing table maps command strings directly to those
module-level functions, and the *uc* (use case) instance is passed as
the first argument at dispatch time.
"""

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
from finbot.core.application.use_cases.telegram_config_flow import (
    _handle_config,
    _handle_config_profile,
    _handle_config_save,
    _handle_size,
    _render_config_view,
)
from finbot.core.application.use_cases.telegram_lifecycle import (
    _format_idle_status,
    _format_running_status,
    _handle_balance,
    _handle_help,
    _handle_history,
    _handle_leverage,
    _handle_list,
    _handle_log,
    _handle_mode,
    _handle_mute,
    _handle_position,
    _handle_price,
    _handle_start,
    _handle_status,
    _handle_stop,
    _handle_symbol,
    _handle_unmute,
    _render_symbol_picker,
)
from finbot.core.application.use_cases.telegram_manual_orders import (
    _execute_clear,
    _execute_manual_order,
    _handle_cancel,
    _handle_clear,
    _handle_close,
    _handle_long,
    _handle_orders,
    _handle_short,
    _handle_sl,
    _handle_tp,
    _live_trading_ack_mode,
    _manual_entry,
    _needs_confirmation,
    _render_clear_confirmation,
    _render_order_confirmation,
    _risk_order,
)
from finbot.core.application.use_cases.telegram_panic_flow import (
    _handle_confirm_callback,
    _handle_panic,
    _handle_panic_callback,
    _panic_execute,
)
from finbot.core.application.use_cases.telegram_run_flow import (
    _handle_run,
    _handle_run_callback,
    _read_execution_config,
    _render_symbol_page,
    _render_symbol_type_menu,
    _run_cb_confirm,
    _run_cb_int,
    _run_cb_mode,
    _run_cb_mode_live,
    _run_cb_strat,
    _run_cb_sym,
    _run_cb_symidx,
    _start_bot_from_session,
)
from finbot.core.domain.entities.callback_data import CallbackData
from finbot.core.domain.interfaces.bot_manager_port import BotManagerPort
from finbot.core.domain.interfaces.market_metadata_provider import (
    MarketMetadataProvider,
)
from finbot.core.domain.interfaces.strategy_definition_loader import (
    StrategyDefinitionLoader,
)
from finbot.core.domain.interfaces.strategy_directory import StrategyDirectory
from finbot.core.domain.interfaces.strategy_log_reader import (
    StrategyLogReader,
)
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

    The command routing table maps ``/command`` strings directly to
    module-level handler functions.  ``execute()`` looks up the handler
    and calls ``handler(self, request)`` — the use case instance is the
    first argument so handlers can reach ``uc._bot_manager`` etc.
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
        mode: str = "dry_run",
        hyperliquid_testnet: bool = True,
        metadata_provider: MarketMetadataProvider | None = None,
        log_reader: StrategyLogReader | None = None,
        strategy_loader: StrategyDefinitionLoader | None = None,
    ) -> None:
        self._bot_manager = bot_manager
        self._chat_repo = chat_repo
        self._strategy_dir = strategy_dir
        self._session_store = session_store
        self._allowed_users = allowed_users
        self._live_trading_ack = live_trading_ack
        self._mode = mode
        self._testnet = hyperliquid_testnet
        self._metadata_provider = metadata_provider
        self._log_reader = log_reader
        self._strategy_loader = strategy_loader

    # -- helpers exposed to module-level handlers ---------------------------

    def _needs_confirmation(self) -> bool:
        """True when the configured mode requires confirmation."""
        return _needs_confirmation(self)

    def _live_trading_ack_mode(self) -> str:
        """Return the configured mode for confirmation/display."""
        return _live_trading_ack_mode(self)

    def _read_execution_config(self, strategy_path: str):
        """Parse the optional execution block from a strategy file."""
        return _read_execution_config(self, strategy_path)

    def _render_symbol_type_menu(self, session) -> TelegramCommandResult:
        """Render the crypto-vs-HIP-3 symbol category picker."""
        return _render_symbol_type_menu(self, session)

    def _render_symbol_page(
        self, session, page: int, symbol_type: str = "crypto"
    ) -> TelegramCommandResult:
        """Render a paginated symbol picker for one market type."""
        return _render_symbol_page(self, session, page, symbol_type)

    def _render_symbol_picker(self, symbols, page):
        """Render a paginated symbol picker for /symbol with no args."""
        return _render_symbol_picker(self, symbols, page)

    # -- run-flow callbacks (called from handle_callback) -------------------

    def _run_cb_strat(self, session, idx_str: str) -> TelegramCommandResult:
        return _run_cb_strat(self, session, idx_str)

    def _run_cb_symidx(self, session, value: str) -> TelegramCommandResult:
        return _run_cb_symidx(self, session, value)

    def _run_cb_sym(self, session, symbol: str) -> TelegramCommandResult:
        return _run_cb_sym(self, session, symbol)

    def _run_cb_int(self, session, interval: str) -> TelegramCommandResult:
        return _run_cb_int(self, session, interval)

    def _run_cb_mode(self, session, mode: str) -> TelegramCommandResult:
        return _run_cb_mode(self, session, mode)

    def _run_cb_mode_live(self, session) -> TelegramCommandResult:
        return _run_cb_mode_live(self, session)

    def _run_cb_confirm(self, session, value: str) -> TelegramCommandResult:
        return _run_cb_confirm(self, session, value)

    def _start_bot_from_session(self, session, mode: str) -> TelegramCommandResult:
        return _start_bot_from_session(self, session, mode)

    # -- manual-order helpers (called from handle_callback and handlers) ---

    async def _manual_entry(self, request, side):
        """Shared /long + /short entry flow."""
        return await _manual_entry(self, request, side)

    async def _risk_order(self, request, kind):
        """Shared /sl + /tp flow."""
        return await _risk_order(self, request, kind)

    def _render_order_confirmation(
        self,
        request,
        side,
        active,
        size,
        sl_price,
        tp_price,
        limit_px=None,
        usd_notional=None,
    ) -> TelegramCommandResult:
        return _render_order_confirmation(
            self, request, side, active, size, sl_price,
            tp_price, limit_px, usd_notional,
        )

    def _execute_manual_order(
        self, order_side, active, size, sl_price, tp_price,
        limit_px=None, usd_notional=None,
    ) -> TelegramCommandResult:
        return _execute_manual_order(
            self, order_side, active, size, sl_price, tp_price,
            limit_px, usd_notional,
        )

    def _render_clear_confirmation(self, request) -> TelegramCommandResult:
        return _render_clear_confirmation(self, request)

    def _execute_clear(self) -> TelegramCommandResult:
        return _execute_clear(self)

    # -- config helpers (called from telegram_config_flow) -----------------

    def _render_config_view(self):
        """Render the current runtime config view."""
        return _render_config_view(self)

    async def _handle_config_save(self):
        """Save current runtime config to .env."""
        return await _handle_config_save(self)

    async def _handle_config_profile(self, rest: str):
        """Save or load a named config profile."""
        return await _handle_config_profile(self, rest)

    # -- panic callbacks (called from handle_callback) ----------------------

    def _panic_execute(self, action: str, symbol: str) -> TelegramCommandResult:
        return _panic_execute(self, action, symbol)

    # -- status formatting --------------------------------------------------

    def _format_running_status(self, status: dict) -> TelegramCommandResult:
        return _format_running_status(self, status)

    def _format_idle_status(self, status: dict) -> TelegramCommandResult:
        return _format_idle_status(self, status)

    # -- public API ---------------------------------------------------------

    async def execute(
        self, request: TelegramCommandRequest
    ) -> TelegramCommandResult:
        """Route a Telegram command to the appropriate handler.

        Commands mapped to module-level functions via *handler_table*;
        the use case instance is passed as the first argument so
        handlers can access ``uc._bot_manager``, ``uc._metadata_provider``,
        etc.
        """
        cmd = request.command

        # /whoami is always allowed — no authorization check
        if cmd == "/whoami":
            return self._handle_whoami(request)

        # Authorization check for all other commands
        auth_error = self._authorize(request)
        if auth_error is not None:
            return auth_error

        # Route to module-level handler
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
            return await self._dispatch_run_callback(request, data)

        # Confirmation callbacks (manual orders + clear): confirm:<sid>:<action>
        if data.has_prefix("confirm") and data.segment_count >= 3:
            return self._dispatch_confirm_callback(request, data)

        # Panic callbacks
        if data.has_prefix("panic") and data.segment_count >= 2:
            return self._dispatch_panic_callback(request, data)

        return TelegramCommandResult(
            text="Invalid selection, please start again with /run\\."
        )

    # -- internal dispatch helpers ------------------------------------------

    async def _dispatch_run_callback(
        self, request: CallbackQueryRequest, data: CallbackData
    ) -> TelegramCommandResult:
        """Forward a run-flow callback to the module-level handler."""
        return await _handle_run_callback(self, request, data)

    def _dispatch_confirm_callback(
        self, request, data
    ) -> TelegramCommandResult:
        """Forward a confirmation callback to the module-level handler."""
        return _handle_confirm_callback(self, request, data)

    def _dispatch_panic_callback(
        self, request: CallbackQueryRequest, data: CallbackData
    ) -> TelegramCommandResult:
        """Forward a panic callback to the module-level handler."""
        return _handle_panic_callback(self, request, data)

    # -- authorization ------------------------------------------------------

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


# -- command routing table ---------------------------------------------------

# Maps /command strings directly to module-level async handler functions.
# At dispatch time ``handler(uc, request)`` is called where *uc* is the
# ``HandleTelegramCommand`` instance.
_COMMAND_HANDLERS: dict[str, object] = {
    "/start":    _handle_start,
    "/help":     _handle_help,
    "/status":   _handle_status,
    "/stop":     _handle_stop,
    "/run":      _handle_run,
    "/list":     _handle_list,
    "/history":  _handle_history,
    "/panic":    _handle_panic,
    "/mute":     _handle_mute,
    "/unmute":   _handle_unmute,
    "/symbol":   _handle_symbol,
    "/price":    _handle_price,
    "/balance":  _handle_balance,
    "/leverage": _handle_leverage,
    "/log":      _handle_log,
    "/mode":     _handle_mode,
    "/position": _handle_position,
    "/long":     _handle_long,
    "/short":    _handle_short,
    "/close":    _handle_close,
    "/clear":    _handle_clear,
    "/sl":       _handle_sl,
    "/tp":       _handle_tp,
    "/config":   _handle_config,
    "/size":     _handle_size,
    "/orders":   _handle_orders,
    "/cancel":   _handle_cancel,
}
