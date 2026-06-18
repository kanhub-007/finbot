"""BotManager package — lifecycle + trading control.

Re-exports BotManager from _manager for backward-compatible imports::

    from finbot.core.domain.services.bot_manager import BotManager
"""

from finbot.core.domain.services.bot_manager._manager import BotManager

__all__ = ["BotManager"]
