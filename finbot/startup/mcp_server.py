"""FinbotMcpServer — typed wrapper around FastMCP (S15: M19).

Replaces the monkey-patched ``server.bot_manager = ...`` /
``server._finbot_telegram = ...`` pattern (which forced
``# type: ignore[attr-defined]``) with a typed dataclass so the
composition root returns a properly-typed object.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class FinbotMcpServer:
    """Typed wrapper holding the FastMCP server and wired Finbot components.

    Attributes
    ----------
    server:
        The FastMCP instance with all tools registered.
    bot_manager:
        The wired BotManager (for composition-root tests).
    telegram:
        Optional Telegram control plane (None when Telegram is disabled).
    """

    server: Any
    bot_manager: Any
    telegram: Any | None = None
