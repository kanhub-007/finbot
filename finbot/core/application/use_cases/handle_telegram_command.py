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


from finbot.core.application.use_cases.telegram_run_flow import (
    _handle_run,
    _handle_run_callback,
    _read_execution_config,
    _render_symbol_page,
    _run_cb_confirm,
    _run_cb_int,
    _run_cb_mode,
    _run_cb_mode_live,
    _run_cb_strat,
    _run_cb_sym,
    _start_bot_from_session,
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
from finbot.core.application.use_cases.telegram_config_flow import (
    _handle_config,
    _handle_config_profile,
    _handle_config_save,
    _handle_size,
    _render_config_view,
)

from finbot.core.application.use_cases.telegram_lifecycle import (
    _handle_start,
    _handle_help,
    _handle_status,
    _format_running_status,
    _format_idle_status,
    _handle_stop,
    _handle_list,
    _handle_mute,
    _handle_unmute,
    _handle_history,
    _handle_balance,
    _handle_leverage,
    _handle_position,
    _handle_price,
    _handle_symbol,
    _render_symbol_picker,
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
        mode: str = "dry_run",
        metadata_provider: object | None = None,
    ) -> None:
        self._bot_manager = bot_manager
        self._chat_repo = chat_repo
        self._strategy_dir = strategy_dir
        self._session_store = session_store
        self._allowed_users = allowed_users
        self._live_trading_ack = live_trading_ack
        self._mode = mode
        self._metadata_provider = metadata_provider

    async def _handle_start(
        self, request: TelegramCommandRequest
    ) -> TelegramCommandResult:
        return await _handle_start(self, request)

    async def _handle_help(
        self, request: TelegramCommandRequest
    ) -> TelegramCommandResult:
        return await _handle_help(self, request)

    async def _handle_status(
        self, request: TelegramCommandRequest
    ) -> TelegramCommandResult:
        return await _handle_status(self, request)

    def _format_running_status(
        self, request: TelegramCommandRequest
    ) -> TelegramCommandResult:
        return _format_running_status(self, request)

    def _format_idle_status(
        self, request: TelegramCommandRequest
    ) -> TelegramCommandResult:
        return _format_idle_status(self, request)

    async def _handle_stop(
        self, request: TelegramCommandRequest
    ) -> TelegramCommandResult:
        return await _handle_stop(self, request)

    async def _handle_list(
        self, request: TelegramCommandRequest
    ) -> TelegramCommandResult:
        return await _handle_list(self, request)

    async def _handle_mute(
        self, request: TelegramCommandRequest
    ) -> TelegramCommandResult:
        return await _handle_mute(self, request)

    async def _handle_unmute(
        self, request: TelegramCommandRequest
    ) -> TelegramCommandResult:
        return await _handle_unmute(self, request)

    async def _handle_history(
        self, request: TelegramCommandRequest
    ) -> TelegramCommandResult:
        return await _handle_history(self, request)

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

        # Confirmation callbacks (manual orders + clear): confirm:<sid>:<action>
        if data.has_prefix("confirm") and data.segment_count >= 3:
            return self._handle_confirm_callback(request, data)

        # Panic callbacks
        if data.has_prefix("panic") and data.segment_count >= 2:
            return self._handle_panic_callback(request, data)

        return TelegramCommandResult(
            text="Invalid selection, please start again with /run\\."
        )

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

    def _handle_whoami(self, request: TelegramCommandRequest) -> TelegramCommandResult:
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

    async def _handle_run(
        self, request: TelegramCommandRequest
    ) -> TelegramCommandResult:
        return await _handle_run(self, request)

    async def _handle_panic(
        self, request: TelegramCommandRequest
    ) -> TelegramCommandResult:
        return await _handle_panic(self, request)

    async def _handle_run_callback(
        self, request: CallbackQueryRequest, data: CallbackData
    ) -> TelegramCommandResult:
        return await _handle_run_callback(self, request, data)

    def _render_symbol_page(self, session, page: int) -> TelegramCommandResult:
        return _render_symbol_page(self, session, page)

    def _run_cb_strat(self, session, idx_str: str) -> TelegramCommandResult:
        return _run_cb_strat(self, session, idx_str)

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

    def _read_execution_config(self, strategy_path: str):
        return _read_execution_config(self, strategy_path)

    def _start_bot_from_session(self, session, mode: str) -> TelegramCommandResult:
        return _start_bot_from_session(self, session, mode)

    def _handle_confirm_callback(self, request, data) -> TelegramCommandResult:
        return _handle_confirm_callback(self, request, data)

    def _handle_panic_callback(
        self, request: CallbackQueryRequest, data: CallbackData
    ) -> TelegramCommandResult:
        return _handle_panic_callback(self, request, data)

    def _panic_execute(self, action: str, symbol: str) -> TelegramCommandResult:
        return _panic_execute(self, action, symbol)

    async def _handle_symbol(self, request: TelegramCommandRequest):
        return await _handle_symbol(self, request)

    def _render_symbol_picker(self, symbols, page):
        return _render_symbol_picker(self, symbols, page)

    async def _handle_price(self, request: TelegramCommandRequest):
        return await _handle_price(self, request)

    async def _handle_balance(self, request: TelegramCommandRequest):
        return await _handle_balance(self, request)

    async def _handle_leverage(self, request: TelegramCommandRequest):
        return await _handle_leverage(self, request)

    async def _handle_position(self, request: TelegramCommandRequest):
        return await _handle_position(self, request)

    async def _handle_long(self, request: TelegramCommandRequest):
        return await _handle_long(self, request)

    async def _handle_short(self, request: TelegramCommandRequest):
        return await _handle_short(self, request)

    async def _manual_entry(self, request, side):
        return await _manual_entry(self, request, side)

    def _needs_confirmation(self) -> bool:
        return _needs_confirmation(self)

    def _live_trading_ack_mode(self) -> str:
        return _live_trading_ack_mode(self)

    def _render_order_confirmation(
        self, request, side, active, size, sl_price, tp_price
    ) -> TelegramCommandResult:
        return _render_order_confirmation(
            self, request, side, active, size, sl_price, tp_price
        )

    def _execute_manual_order(
        self, order_side, active, size, sl_price, tp_price
    ) -> TelegramCommandResult:
        return _execute_manual_order(self, order_side, active, size, sl_price, tp_price)

    async def _handle_close(self, request: TelegramCommandRequest):
        return await _handle_close(self, request)

    async def _handle_clear(self, request: TelegramCommandRequest):
        return await _handle_clear(self, request)

    def _render_clear_confirmation(self, request) -> TelegramCommandResult:
        return _render_clear_confirmation(self, request)

    def _execute_clear(self) -> TelegramCommandResult:
        return _execute_clear(self)

    async def _handle_sl(self, request: TelegramCommandRequest):
        return await _handle_sl(self, request)

    async def _handle_tp(self, request: TelegramCommandRequest):
        return await _handle_tp(self, request)

    async def _risk_order(self, request, kind):
        return await _risk_order(self, request, kind)

    async def _handle_config(self, request: TelegramCommandRequest):
        return await _handle_config(self, request)

    def _render_config_view(self):
        return _render_config_view(self)

    async def _handle_config_save(self):
        return await _handle_config_save(self)

    async def _handle_config_profile(self, rest: str):
        return await _handle_config_profile(self, rest)

    async def _handle_size(self, request: TelegramCommandRequest):
        return await _handle_size(self, request)

    async def _handle_orders(self, request: TelegramCommandRequest):
        return await _handle_orders(self, request)

    async def _handle_cancel(self, request: TelegramCommandRequest):
        return await _handle_cancel(self, request)


# Command routing table — references handler methods defined above.
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
