"""Shared helpers for MCP tool modules.

Follows the same pattern as finbar's ``_shared.py``: lazy factories and a
helper to retrieve the BotManager from the FastMCP instance.
"""

from fastmcp import FastMCP


def _get_bot_manager(mcp: FastMCP):
    """Return the BotManager stored on the FastMCP instance.

    ``_finbot_bot_manager`` is set by the composition root in
    :mod:`finbot.startup.mcp`.
    """
    return mcp._finbot_bot_manager  # type: ignore[attr-defined]
