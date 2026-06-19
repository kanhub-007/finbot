"""Extracted Telegram command handlers — telegram_config_flow (S8 decomposition)."""

from __future__ import annotations

from finbot.core.application.dto.telegram_command_result import (
    TelegramCommandResult,
)
from finbot.core.application.use_cases.telegram_helpers import (
    _escape_mdv2,
)


async def _handle_config(uc, request: TelegramCommandRequest):
    """View or adjust runtime config, or manage named profiles."""
    args = request.args.strip().split(maxsplit=1)
    if not args:
        return uc._render_config_view()
    key = args[0]
    # Profile subcommand: /config profile save|load|list [NAME]
    if key == "profile":
        return await uc._handle_config_profile(args[1] if len(args) > 1 else "")
    # Persist runtime config to .env: /config save
    if key == "save":
        return await uc._handle_config_save()
    if len(args) < 2:
        return TelegramCommandResult(
            text=f"Usage: /config {key} VALUE", parse_mode="MarkdownV2"
        )
    result = uc._bot_manager.update_bot_config(key, args[1])
    if result.get("status") != "ok":
        return TelegramCommandResult(
            text=f"\u274c {_escape_mdv2(str(result.get('message', 'Rejected')))}",
            parse_mode="MarkdownV2",
        )
    return TelegramCommandResult(
        text=f"\u2705 {_escape_mdv2(key)} = {_escape_mdv2(args[1])}",
        parse_mode="MarkdownV2",
    )


def _render_config_view(uc):
    """Format the current config values for /config with no args."""
    cfg = uc._bot_manager.get_bot_config()
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


async def _handle_config_save(uc):
    """Handle /config save — persist runtime config to .env."""
    result = uc._bot_manager.save_config_to_env()
    if result.get("status") != "ok":
        return TelegramCommandResult(
            text=f"\u274c {_escape_mdv2(str(result.get('message', 'Rejected')))}",
            parse_mode="MarkdownV2",
        )
    saved = result.get("saved", 0)
    return TelegramCommandResult(
        text=f"\u2705 Saved {saved} settings to \\ .env\\.",
        parse_mode="MarkdownV2",
    )


async def _handle_config_profile(uc, rest: str):
    """Handle /config profile save|load|list [NAME]."""
    parts = rest.split(maxsplit=1)
    if not parts or not parts[0]:
        return TelegramCommandResult(
            text="Usage: /config profile save\\|load\\|list NAME",
            parse_mode="MarkdownV2",
        )
    sub = parts[0].lower()
    if sub == "list":
        result = uc._bot_manager.list_config_profiles()
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
        result = uc._bot_manager.save_config_profile(name)
    elif sub == "load":
        result = uc._bot_manager.load_config_profile(name)
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


async def _handle_size(uc, request: TelegramCommandRequest):
    """Set, view, or clear the default order size."""
    from decimal import Decimal

    arg = request.args.strip()
    if not arg:
        current = uc._bot_manager.get_default_size()
        val = "not set" if current is None else str(current)
        return TelegramCommandResult(
            text=f"Default size: {val}\n" f"Set: /size 0\\.1  \\(or /size clear\\)",
            parse_mode="MarkdownV2",
        )
    if arg.lower() == "clear":
        uc._bot_manager.clear_default_size()
        return TelegramCommandResult(
            text="\u2705 Default size cleared\\.", parse_mode="MarkdownV2"
        )
    try:
        size = Decimal(arg)
    except Exception:
        return TelegramCommandResult(text="Invalid size\\.", parse_mode="MarkdownV2")
    result = uc._bot_manager.set_default_size(size)
    if result.get("status") != "ok":
        return TelegramCommandResult(
            text=f"\u274c {_escape_mdv2(str(result.get('message', 'Rejected')))}",
            parse_mode="MarkdownV2",
        )
    return TelegramCommandResult(
        text=f"\u2705 Default size: {_escape_mdv2(str(size))}",
        parse_mode="MarkdownV2",
    )
