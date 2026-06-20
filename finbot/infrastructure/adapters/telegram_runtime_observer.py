"""TelegramRuntimeObserver — subscribes to runtime events, forwards to Telegram."""

from __future__ import annotations

from finbot.core.domain.events.risk_event_triggered import RiskEventTriggered
from finbot.core.domain.events.runtime_events import (
    EnrichmentRejectedEvent,
    RiskTriggeredEvent,
)
from finbot.core.domain.events.trade_executed import TradeExecuted
from finbot.core.domain.interfaces.bot_notification_sender import (
    BotNotificationSender,
)


class TelegramRuntimeObserver:
    """Converts runtime events to domain notification events and dispatches.

    Subscribes to the runtime's ``RuntimeEventEmitter``. When events are
    emitted (synchronously from the trading thread), converts them to the
    domain event types that ``BotNotificationSender`` expects, and schedules
    async send via the thread-safe dispatcher.
    """

    def __init__(self, sender: BotNotificationSender) -> None:
        self._sender = sender

    def on_risk_triggered(self, event: RiskTriggeredEvent) -> None:
        """Forward a risk event to the notification sender."""
        self._sender.notify_risk(
            RiskEventTriggered(
                run_id=event.run_id,
                event_type=event.event_type,
                reason=event.reason,
                bot_stopped=event.bot_stopped,
            )
        )

    def on_trade_executed(self, event: TradeExecuted) -> None:
        """Forward a trade fill to the notification sender."""
        self._sender.notify_trade(event)

    def on_enrichment_rejected(self, event: EnrichmentRejectedEvent) -> None:
        """Forward an enrichment rejection as a risk notification."""
        self._sender.notify_risk(
            RiskEventTriggered(
                run_id=event.run_id,
                event_type="enrichment_validation",
                reason=event.reason,
                bot_stopped=False,
            )
        )
