"""MCP tools — bot run history queries."""

import json

from fastmcp import FastMCP

from ._shared import _get_bot_manager


def register_bot_history_tools(mcp: FastMCP) -> None:
    """Register list_bot_runs and get_bot_run_results MCP tools."""

    @mcp.tool(
        name="list_bot_runs",
        description=(
            "List completed bot runs. Returns run summaries with run_id, "
            "strategy name, symbol, interval, mode, start/end timestamps, "
            "and signal/order/fill counts. "
            "Optionally filter by mode (dry_run, testnet, live) and "
            "limit the number of results."
        ),
    )
    def list_bot_runs(
        limit: int = 20,
        mode: str | None = None,
    ) -> str:
        """Return recent bot runs ordered by most recent first."""
        manager = _get_bot_manager(mcp)
        runs = manager.list_bot_runs(limit=limit, mode_filter=mode)
        counts = manager.get_run_counts([r.run_id for r in runs])
        result = {
            "count": len(runs),
            "runs": [
                {
                    "run_id": r.run_id,
                    "strategy_name": r.strategy_name,
                    "symbol": r.symbol,
                    "interval": r.interval,
                    "mode": r.mode,
                    "started_at": (r.started_at.isoformat() if r.started_at else None),
                    "ended_at": (r.ended_at.isoformat() if r.ended_at else None),
                    "signal_count": counts[r.run_id].signals,
                    "order_count": counts[r.run_id].orders,
                    "fill_count": counts[r.run_id].fills,
                }
                for r in runs
            ],
        }
        return json.dumps(result, indent=2, default=str)

    @mcp.tool(
        name="get_bot_run_results",
        description=(
            "Get detailed results for a specific bot run. "
            "Returns the run summary plus arrays of signals, orders, "
            "fills, and risk events for that run."
        ),
    )
    def get_bot_run_results(run_id: str) -> str:
        """Return full results for a bot run."""
        manager = _get_bot_manager(mcp)

        run = manager.get_bot_run(run_id)
        if run is None:
            return json.dumps({"error": f"Run not found: {run_id}"})

        signals = manager.get_signals_for_run(run_id)
        orders = manager.get_orders_for_run(run_id)
        fills = manager.get_fills_for_run(run_id)
        risk_events = manager.get_risk_events_for_run(run_id)

        return json.dumps(
            {
                "run": {
                    "run_id": run.run_id,
                    "strategy_name": run.strategy_name,
                    "symbol": run.symbol,
                    "interval": run.interval,
                    "mode": run.mode,
                    "started_at": (
                        run.started_at.isoformat() if run.started_at else None
                    ),
                    "ended_at": (run.ended_at.isoformat() if run.ended_at else None),
                },
                "summary": {
                    "signal_count": len(signals),
                    "order_count": len(orders),
                    "fill_count": len(fills),
                    "risk_event_count": len(risk_events),
                },
                "signals": [
                    {
                        "signal_key": s.signal_key,
                        "action": s.signal_action,
                        "bar_timestamp": s.bar_timestamp,
                    }
                    for s in signals
                ],
                "orders": [
                    {
                        "intent_id": o.intent_id,
                        "status": o.status,
                    }
                    for o in orders
                ],
                "risk_events": [
                    {
                        "event_type": e.event_type,
                        "decision": e.decision,
                        "reason": e.reason,
                    }
                    for e in risk_events
                ],
            },
            indent=2,
            default=str,
        )
