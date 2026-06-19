"""BotManagerState — shared mutable context for BotManager collaborators.

Holds the fields accessed by more than one collaborator (active symbol,
runtime reference, runtime config, default size, config profiles). Each
collaborator receives this object + a :class:`BotManagerLock` rather than
referencing each other, so there are no cross-collaborator attribute
accesses (the S7 constraint: no ``self._lifecycle._runtime``).

This is the standard shared-context pattern for decomposing a God Class:
behaviour is split into focused services; state is shared through a
narrow, documented context object.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from finbot.core.domain.entities.active_symbol_state import ActiveSymbolState
from finbot.core.domain.entities.runtime_bot_config import RuntimeBotConfig


@dataclass
class BotManagerState:
    """Mutable state shared by all BotManager collaborators.

    Fields are intentionally public — collaborators read/write them under
    the shared :class:`BotManagerLock`.
    """

    active_symbol: ActiveSymbolState | None = None
    runtime: Any | None = None
    thread: threading.Thread | None = None
    runtime_config: RuntimeBotConfig = field(default_factory=RuntimeBotConfig)
    default_size: Decimal | None = None
    config_profiles: dict[str, Any] = field(default_factory=dict)
