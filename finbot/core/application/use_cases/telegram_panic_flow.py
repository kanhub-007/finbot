"""Extracted Telegram command handlers — telegram_panic_flow (S8 decomposition)."""

from __future__ import annotations

from finbot.core.application.dto.telegram_command_result import (
    TelegramCommandResult,
)
from finbot.core.application.use_cases.telegram_helpers import (
    _escape_mdv2,
    _get_symbols,
)


async def _handle_panic(uc, request: TelegramCommandRequest) -> TelegramCommandResult:
    """Emergency panic — show action options or pick symbol first."""
    if uc._bot_manager.is_running():
        status = uc._bot_manager.get_status()
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
        for sym in _get_symbols(uc._metadata_provider)[:30]:
            buttons.append({"text": sym, "callback_data": f"panic:sym:{sym}"})
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


def _handle_confirm_callback(uc, request, data) -> TelegramCommandResult:
    """Handle Confirm/Cancel for manual orders and /clear.

    Re-validates state on Confirm (prompt may be stale): re-checks the
    active symbol, reads the stashed draft, and submits. The
    BotManager re-runs risk gates internally, so a stale prompt that no
    longer passes gates is rejected cleanly.
    """
    session_id = data.action
    action = data.value
    session = uc._session_store.get(session_id)
    if session is None:
        return TelegramCommandResult(
            text="Session expired\\. Please start again\\.",
            parse_mode="MarkdownV2",
        )
    if session.chat_id != request.chat_id:
        return TelegramCommandResult(
            text="Invalid selection\\.", parse_mode="MarkdownV2"
        )
    uc._session_store.delete(session_id)

    if action == "cancel":
        return TelegramCommandResult(
            text="\u23f9 Cancelled\\.", parse_mode="MarkdownV2"
        )

    if action == "clearexec":
        return uc._execute_clear()

    if action == "exec":
        # Read the typed draft stashed at prompt time (M9).
        draft = session.manual_order_draft
        if draft is None:
            return TelegramCommandResult(
                text="Session corrupted\\. Please start again\\.",
                parse_mode="MarkdownV2",
            )
        active = uc._bot_manager.get_active_symbol()
        if active is None:
            return TelegramCommandResult(
                text="No active symbol\\.", parse_mode="MarkdownV2"
            )
        return uc._execute_manual_order(
            draft.side, active, draft.size, draft.sl_price, draft.tp_price
        )

    return TelegramCommandResult(
        text="Unknown confirmation action\\.", parse_mode="MarkdownV2"
    )


def _handle_panic_callback(
    uc, request: CallbackQueryRequest, data: CallbackData
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
        return uc._panic_execute(data.subvalue, symbol)

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


def _panic_execute(uc, action: str, symbol: str) -> TelegramCommandResult:
    """Execute the panic action: cancel orders, close position, or both.

    Counts come from the exchange result's ``cancelled`` field (H1) —
    never ``len(result)`` (which would report the dict's key count).
    """
    mgr = uc._bot_manager
    cancelled = 0
    cancel_error: str | None = None
    position_closed = False
    close_error: str | None = None

    if action in ("cancel", "both"):
        cancel_result = mgr.cancel_all_orders(symbol)
        if isinstance(cancel_result, dict) and "error" not in cancel_result:
            cancelled = int(cancel_result.get("cancelled", 0))
        elif isinstance(cancel_result, dict):
            cancel_error = str(cancel_result.get("error", "unknown"))

    if action in ("close", "both"):
        close_result = mgr.close_position(symbol)
        if isinstance(close_result, dict) and "error" not in close_result:
            position_closed = True
        elif isinstance(close_result, dict):
            close_error = str(close_result.get("error", "unknown"))

    # Stop the bot after panic
    uc._bot_manager.stop()

    text_lines = [
        "\U0001f6a8 *PANIC executed:*",
    ]
    if action in ("cancel", "both"):
        text_lines.append(f"\u2022 Orders cancelled: {cancelled}")
        if cancel_error is not None:
            text_lines.append(f"\u2022 Cancel failed: {_escape_mdv2(cancel_error)}")
    if action in ("close", "both"):
        status = "closed" if position_closed else "failed to close"
        text_lines.append(f"\u2022 Position {status}")
        if close_error is not None:
            text_lines.append(f"\u2022 Close failed: {_escape_mdv2(close_error)}")
    text_lines.append("Bot has been stopped\\.")

    return TelegramCommandResult(
        text="\n".join(text_lines),
        parse_mode="MarkdownV2",
    )
