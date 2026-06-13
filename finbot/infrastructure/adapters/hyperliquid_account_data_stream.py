"""Hyperliquid account data stream — user fills and order updates via WebSocket.

Subscribes to the Hyperliquid ``userFills`` and ``orderUpdates`` channels
and enqueues normalized events into a shared ``EventQueue``.

Requires a private key (via ``SecretStr``) to authenticate the WebSocket
connection.  Works with the SDK's ``Exchange`` websocket manager which
handles signing internally.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from finbot.core.domain.entities.bot_event import BotEvent
from finbot.core.domain.entities.bot_event_type import BotEventType
from finbot.core.domain.interfaces.event_queue import EventQueue

if TYPE_CHECKING:

    from hyperliquid.exchange import Exchange

logger = logging.getLogger(__name__)


class HyperliquidAccountDataStream:
    """Subscribes to Hyperliquid user-fills and order-update websocket channels.

    Does NOT implement ``MarketDataStream`` — it uses the ``EventQueue``
    directly so events flow through the same loop as candles.

    Parameters
    ----------
    exchange:
        An authenticated ``Exchange`` instance whose websocket manager
        is reused for the account subscriptions.
    queue:
        Thread-safe event queue shared with the bot event loop.
    user_address:
        The account address for which to subscribe.  Derived from the
        private key if not provided.
    """

    def __init__(
        self,
        exchange: Exchange,
        queue: EventQueue,
        user_address: str = "",
    ) -> None:
        self._exchange = exchange
        self._queue = queue
        self._user_address = user_address or exchange.address
        self._fill_sub_id: int | None = None
        self._order_sub_id: int | None = None

    # -- public API --------------------------------------------------------

    def start(self) -> None:
        """Subscribe to user fills and order updates."""
        ws = self._exchange.ws_manager
        if ws is None:
            logger.warning(
                "No websocket manager on Exchange — skipping account subscriptions"
            )
            return

        try:
            self._fill_sub_id = ws.subscribe(
                {"type": "userFills", "user": self._user_address},
                self._on_user_fill,
            )
            logger.info("Subscribed to userFills for %s", self._user_address)
        except Exception as exc:
            logger.warning("Failed to subscribe to userFills: %s", exc)

        try:
            self._order_sub_id = ws.subscribe(
                {"type": "orderUpdates"},
                self._on_order_update,
            )
            logger.info("Subscribed to orderUpdates")
        except Exception as exc:
            logger.warning("Failed to subscribe to orderUpdates: %s", exc)

    def stop(self) -> None:
        """Unsubscribe from account channels."""
        ws = self._exchange.ws_manager
        if ws is None:
            return
        for sub_id in (self._fill_sub_id, self._order_sub_id):
            if sub_id is not None:
                try:
                    subscription = (
                        {"type": "orderUpdates"}
                        if sub_id == self._order_sub_id
                        else {"type": "userFills", "user": self._user_address}
                    )
                    ws.unsubscribe(subscription, sub_id)
                except Exception:
                    pass
        self._fill_sub_id = None
        self._order_sub_id = None

    # -- internal -----------------------------------------------------------

    def _on_user_fill(self, ws_msg: dict[str, Any]) -> None:
        """SDK callback — runs on websocket thread."""
        data = ws_msg.get("data", {})
        if not data or data.get("channel") != "userFills":
            return
        fill_data = data.get("data", data)
        normalized = _normalize_fill(fill_data)
        if normalized:
            event = BotEvent(type=BotEventType.FILL, data=normalized)
            if not self._queue.enqueue(event):
                logger.warning("Event queue full — dropping fill event")

    def _on_order_update(self, ws_msg: dict[str, Any]) -> None:
        """SDK callback — runs on websocket thread."""
        data = ws_msg.get("data", {})
        if not data:
            return
        normalized = _normalize_order_update(data)
        if normalized:
            event = BotEvent(type=BotEventType.ORDER_UPDATE, data=normalized)
            if not self._queue.enqueue(event):
                logger.warning("Event queue full — dropping order update event")


# ---------------------------------------------------------------------------
# Normalization helpers — convert SDK types to domain-friendly dicts
# ---------------------------------------------------------------------------


def _normalize_fill(data: dict[str, Any]) -> dict[str, Any] | None:
    """Normalize a Hyperliquid fill message to the account-event shape.

    Returns a dict with: type, order_id, fill_id, side, size, price, fee.
    """
    fill = data if isinstance(data, dict) else {}
    if not fill:
        return None
    return {
        "type": "fill",
        "order_id": str(fill.get("oid", "")),
        "fill_id": str(fill.get("tid", fill.get("hash", ""))),
        "side": str(fill.get("side", "")),
        "size": str(fill.get("sz", "0")),
        "price": str(fill.get("px", "0")),
        "fee": str(fill.get("fee", "0")),
    }


def _normalize_order_update(data: dict[str, Any]) -> dict[str, Any] | None:
    """Normalize a Hyperliquid order update to the account-event shape.

    Returns a dict with: type, order_id, cloid, status.
    """
    if not isinstance(data, dict):
        return None
    # Order updates come as a list or single dict
    order = data
    if "order" in data:
        order = data["order"]
    status = str(data.get("status", order.get("status", "")))
    return {
        "type": "order_update",
        "order_id": str(order.get("oid", "")),
        "cloid": str(order.get("cloid", "")),
        "status": status.lower(),
    }
