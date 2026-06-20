"""Recorded order submission helper for manual bot-manager actions."""

from __future__ import annotations

import json
import uuid
from typing import Any

from finbot.core.domain.entities.order_intent import OrderIntent
from finbot.core.domain.entities.order_response_record import OrderResponseRecord
from finbot.core.domain.interfaces.bot_state_repository import BotStateRepository
from finbot.core.domain.interfaces.exchange_gateway import ExchangeGateway


def submit_and_record(
    exchange: ExchangeGateway,
    repo: BotStateRepository,
    intent: OrderIntent,
    symbol: str,
    *,
    cloid_prefix: str,
    bot_run_id: str = "manual",
) -> dict[str, Any]:
    """Persist an intent before and after exchange submission.

    The helper is used by manual entry/exit and SL/TP paths so every manual
    external order effect has a durable intent row and a response/error row.
    """
    if not intent.cloid:
        intent = intent.with_cloid(f"{cloid_prefix}:{symbol}:{uuid.uuid4().hex}")
    intent_id = repo.record_order_intent(intent)
    try:
        response = exchange.submit_order(intent)
    except Exception as exc:  # noqa: BLE001 - persist failed external effect
        response = {"status": "error", "error": str(exc)}
        _record_response(repo, intent_id, bot_run_id, response, status="error")
        return {"status": "error", "message": str(exc), "intent_id": intent_id}

    status = str(response.get("status", "unknown"))
    _record_response(repo, intent_id, bot_run_id, response, status=status)
    return {
        "status": "ok",
        "response": response,
        "symbol": symbol,
        "intent_id": intent_id,
    }


def _record_response(
    repo: BotStateRepository,
    intent_id: str,
    bot_run_id: str,
    response: dict[str, Any],
    *,
    status: str,
) -> None:
    """Persist one order response row."""
    repo.record_order_response(
        OrderResponseRecord(
            intent_id=intent_id,
            bot_run_id=bot_run_id,
            response_json=json.dumps(response, default=str),
            status=status,
        )
    )
