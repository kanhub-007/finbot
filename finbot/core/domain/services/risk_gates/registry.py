"""Risk gate registry — single place to build the default gate chain.

Replaces the import-and-list ceremony in ``runtime_factory.py``.
Adding a new gate only needs one new class + one line here instead
of editing 3+ files.
"""

from __future__ import annotations

from typing import Any

from finbot.core.domain.entities.runtime_bot_config import RuntimeBotConfig
from finbot.core.domain.interfaces.bot_state_repository import (
    BotStateRepository,
)
from finbot.core.domain.interfaces.manual_order_gate import ManualOrderGate
from finbot.core.domain.interfaces.risk_gate import RiskGate
from finbot.core.domain.services.risk_gates.daily_loss_gate import (
    DailyLossGate,
)
from finbot.core.domain.services.risk_gates.duplicate_signal_gate import (
    DuplicateSignalGate,
)
from finbot.core.domain.services.risk_gates.manual_max_position_gate import (
    ManualMaxPositionGate,
)
from finbot.core.domain.services.risk_gates.manual_mode_gate import (
    ManualModeGate,
)
from finbot.core.domain.services.risk_gates.max_leverage_gate import (
    MaxLeverageGate,
)
from finbot.core.domain.services.risk_gates.max_open_orders_gate import (
    MaxOpenOrdersGate,
)
from finbot.core.domain.services.risk_gates.max_position_gate import (
    MaxPositionGate,
)
from finbot.core.domain.services.risk_gates.mode_gate import ModeGate
from finbot.core.domain.services.risk_gates.reduce_only_gate import (
    ReduceOnlyGate,
)
from finbot.core.domain.services.risk_gates.stale_data_gate import (
    StaleDataGate,
)


def build_default_gates(
    *,
    mode: str = "dry_run",
    live_trading_ack: bool = False,
    stale_data_seconds: int = 120,
    max_position_usd: Any = 100,
    max_leverage: int = 20,
    max_open_orders: int = 3,
    max_daily_loss_usd: Any = 25,
    repo: BotStateRepository | None = None,
) -> list[RiskGate]:
    """Build the default strategy risk-gate chain in order.

    Gates are ordered: mode → staleness → position → leverage →
    open-orders → daily-loss → reduce-only → duplicate-signal.
    The first rejection stops the chain.

    Parameters
    ----------
    repo:
        Required by ``DuplicateSignalGate``. When ``None``, the
        duplicate-signal gate is omitted.
    """
    gates: list[RiskGate] = [
        ModeGate(mode=mode, live_trading_ack=live_trading_ack),
        StaleDataGate(max_age_seconds=stale_data_seconds),
        MaxPositionGate(max_notional_usd=max_position_usd),
        MaxLeverageGate(max_leverage=max_leverage),
        MaxOpenOrdersGate(max_orders=max_open_orders),
        DailyLossGate(max_loss_usd=max_daily_loss_usd),
        ReduceOnlyGate(),
    ]
    if repo is not None:
        gates.append(DuplicateSignalGate(repo))
    return gates


def build_default_manual_gates(
    *,
    mode: str = "dry_run",
    live_trading_ack: bool = False,
    config: RuntimeBotConfig | None = None,
) -> list[ManualOrderGate]:
    """Build the default manual-order gate chain.

    Used by :class:`ManualOrderService` to validate trader-initiated orders
    before exchange submission.  Keep in sync with ``build_default_gates``
    for gates that apply to both pipelines.
    """
    return [
        ManualModeGate(mode=mode, live_trading_ack=live_trading_ack),
        ManualMaxPositionGate(config),
    ]
