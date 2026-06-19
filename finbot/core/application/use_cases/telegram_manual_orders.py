"""Extracted Telegram command handlers — telegram_manual_orders (S8 decomposition)."""

from __future__ import annotations

from finbot.core.application.dto.telegram_command_result import (
    TelegramCommandResult,
)
from finbot.core.application.use_cases.telegram_helpers import (
    _escape_mdv2,
    _parse_brackets,
)


async def _handle_long(uc, request: TelegramCommandRequest):
    """Open a long position on the active symbol."""
    return await uc._manual_entry(request, "buy")


async def _handle_short(uc, request: TelegramCommandRequest):
    """Open a short position on the active symbol."""
    return await uc._manual_entry(request, "sell")


async def _manual_entry(uc, request, side):
    """Shared /long + /short flow: parse, validate, confirm (live), submit."""
    from decimal import Decimal

    from finbot.core.domain.entities.order_side import OrderSide

    active = uc._bot_manager.get_active_symbol()
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
        return TelegramCommandResult(text="Invalid size\\.", parse_mode="MarkdownV2")
    # Optional bracket orders: "sl <price>" and "tp <price>"
    sl_price, tp_price, parse_err = _parse_brackets(args[1:])
    if parse_err is not None:
        return TelegramCommandResult(
            text=f"\u274c {_escape_mdv2(parse_err)}", parse_mode="MarkdownV2"
        )
    order_side = OrderSide.BUY if side == "buy" else OrderSide.SELL

    # In testnet/live, require an explicit Confirm before real orders.
    # Dry-run skips confirmation (no real risk).
    if uc._needs_confirmation():
        return uc._render_order_confirmation(
            request, side, active, size, sl_price, tp_price
        )

    return uc._execute_manual_order(order_side, active, size, sl_price, tp_price)


def _needs_confirmation(uc) -> bool:
    """True when the configured mode requires confirmation before real orders.

    Decided from the injected ``mode`` (M4) — not from
    ``bot_manager.get_status()``, which returns 'dry_run' whenever the
    bot isn't running and would silently skip confirmation for an idle
    live deployment.
    """
    return uc._mode in ("testnet", "live")


def _live_trading_ack_mode(uc) -> str:
    """Return the configured mode for confirmation/display decisions."""
    return uc._mode


def _render_order_confirmation(
    uc, request, side, active, size, sl_price, tp_price
) -> TelegramCommandResult:
    """Show a Confirm/Cancel prompt for a live/testnet manual order."""
    from finbot.core.domain.entities.manual_order_draft import (
        ManualOrderDraft,
    )
    from finbot.core.domain.entities.order_side import OrderSide

    session = uc._session_store.create(request.chat_id, request.message_id)
    sid = session.session_id
    action = "long" if side == "buy" else "short"
    # Stash the order params as a typed draft for re-validation on confirm (M9).
    session.symbol = active.symbol
    session.manual_order_draft = ManualOrderDraft(
        side=(OrderSide.BUY if side == "buy" else OrderSide.SELL),
        size=size,
        sl_price=sl_price,
        tp_price=tp_price,
    )
    uc._session_store.save(session)

    extras = []
    if sl_price is not None:
        extras.append(f"SL={_escape_mdv2(str(sl_price))}")
    if tp_price is not None:
        extras.append(f"TP={_escape_mdv2(str(tp_price))}")
    extra_str = f" {_escape_mdv2(' '.join(extras))}" if extras else ""
    mode = uc._live_trading_ack_mode().upper()
    return TelegramCommandResult(
        text=(
            f"\u26a0\ufe0f Open {action.upper()}\n"
            f"Symbol: {_escape_mdv2(active.symbol)}\n"
            f"Size: {_escape_mdv2(str(size))}{extra_str}\n"
            f"Mode: {mode}\n\n"
            "Real orders WILL be placed\\."
        ),
        parse_mode="MarkdownV2",
        reply_markup={
            "inline_keyboard": [
                [
                    {
                        "text": "\u2705 Confirm",
                        "callback_data": f"confirm:{sid}:exec",
                    },
                    {
                        "text": "\u274c Cancel",
                        "callback_data": f"confirm:{sid}:cancel",
                    },
                ]
            ]
        },
    )


def _execute_manual_order(
    uc, order_side, active, size, sl_price, tp_price
) -> TelegramCommandResult:
    """Submit the manual order (no confirmation step)."""
    if sl_price is not None or tp_price is not None:
        result = uc._bot_manager.submit_manual_order_with_brackets(
            order_side, size, sl_price=sl_price, tp_price=tp_price
        )
    else:
        result = uc._bot_manager.submit_manual_order(order_side, size)
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


async def _handle_close(uc, request: TelegramCommandRequest):
    """Close the active position (reduce-only, clears SL/TP)."""
    result = uc._bot_manager.close_active_position()
    if result.get("status") != "ok":
        return TelegramCommandResult(
            text=f"\u274c {_escape_mdv2(str(result.get('message', 'Rejected')))}",
            parse_mode="MarkdownV2",
        )
    return TelegramCommandResult(
        text="\u2705 Position closed\\.", parse_mode="MarkdownV2"
    )


async def _handle_clear(uc, request: TelegramCommandRequest):
    """Cancel all orders + close all positions (idle only)."""
    # Require confirmation in testnet/live (design decision #6).
    if uc._needs_confirmation():
        return uc._render_clear_confirmation(request)
    return uc._execute_clear()


def _render_clear_confirmation(uc, request) -> TelegramCommandResult:
    """Show a Confirm/Cancel prompt for /clear in live/testnet."""
    session = uc._session_store.create(request.chat_id, request.message_id)
    sid = session.session_id
    session.interval = "clear"  # marker
    uc._session_store.save(session)
    mode = uc._live_trading_ack_mode().upper()
    return TelegramCommandResult(
        text=(
            "\u26a0\ufe0f CLEAR ALL\n"
            "This cancels ALL orders and closes ALL positions\\.\n"
            f"Mode: {mode}"
        ),
        parse_mode="MarkdownV2",
        reply_markup={
            "inline_keyboard": [
                [
                    {
                        "text": "\u2705 Confirm clear",
                        "callback_data": f"confirm:{sid}:clearexec",
                    },
                    {
                        "text": "\u274c Cancel",
                        "callback_data": f"confirm:{sid}:cancel",
                    },
                ]
            ]
        },
    )


def _execute_clear(uc) -> TelegramCommandResult:
    """Execute the clear (no confirmation step)."""
    result = uc._bot_manager.clear_all()
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


async def _handle_sl(uc, request: TelegramCommandRequest):
    """Attach or clear a stop-loss trigger order."""
    return await uc._risk_order(request, "sl")


async def _handle_tp(uc, request: TelegramCommandRequest):
    """Attach or clear a take-profit trigger order."""
    return await uc._risk_order(request, "tp")


async def _risk_order(uc, request, kind):
    """Shared /sl + /tp flow."""
    from decimal import Decimal

    active = uc._bot_manager.get_active_symbol()
    if active is None:
        return TelegramCommandResult(
            text="No symbol selected\\. Use /symbol first\\.",
            parse_mode="MarkdownV2",
        )
    arg = request.args.strip()
    if arg.lower() == "clear":
        result = uc._bot_manager.clear_risk_order(kind)
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
        return TelegramCommandResult(text="Invalid price\\.", parse_mode="MarkdownV2")
    method = (
        uc._bot_manager.attach_stop_loss
        if kind == "sl"
        else uc._bot_manager.attach_take_profit
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


async def _handle_orders(uc, request: TelegramCommandRequest):
    """List open orders for the active symbol."""
    active = uc._bot_manager.get_active_symbol()
    if active is None:
        return TelegramCommandResult(
            text="No symbol selected\\. Use /symbol first\\.",
            parse_mode="MarkdownV2",
        )
    orders = uc._bot_manager.list_active_orders()
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
    return TelegramCommandResult(text="\n".join(lines), parse_mode="MarkdownV2")


async def _handle_cancel(uc, request: TelegramCommandRequest):
    """Cancel a single order by oid on the active symbol."""
    active = uc._bot_manager.get_active_symbol()
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
    result = uc._bot_manager.cancel_order(order_id)
    if result.get("status") != "ok":
        return TelegramCommandResult(
            text=f"\u274c {_escape_mdv2(str(result.get('message', 'Rejected')))}",
            parse_mode="MarkdownV2",
        )
    return TelegramCommandResult(
        text=f"\u2705 Cancelled order {_escape_mdv2(order_id)}\\.",
        parse_mode="MarkdownV2",
    )
