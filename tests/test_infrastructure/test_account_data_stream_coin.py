"""Regression test for H3: order-update normalisation must include 'coin'."""

from finbot.infrastructure.adapters.hyperliquid_account_data_stream import (
    _normalize_order_update,
)


def test_order_update_includes_coin() -> None:
    """H3: 'coin' must be present so cache invalidation can run."""
    normalized = _normalize_order_update(
        {"order": {"oid": "1", "cloid": "c", "coin": "BTC"}, "status": "open"}
    )
    assert normalized["coin"] == "BTC"
    assert normalized["order_id"] == "1"


def test_order_update_coin_defaults_to_empty() -> None:
    normalized = _normalize_order_update({"order": {"oid": "9"}, "status": "filled"})
    assert normalized["coin"] == ""
