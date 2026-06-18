"""MCP tools — utilities (ping, validate_strategy, audit log).

S8 (M2): the ``validate_strategy`` use case is built once at server
startup and passed into ``register_util_tools`` via the
``validate_strategy_use_case`` parameter. When the caller does not
supply one (legacy callers), it falls back to constructing one per call
— but the composition root always supplies the prebuilt instance.
"""

import json
from pathlib import Path
from typing import Any

from fastmcp import FastMCP

from finbot.core.domain.dto.validate_strategy_request import (
    ValidateStrategyRequest,
)


def register_util_tools(
    mcp: FastMCP,
    bot_manager: Any,
    validate_strategy_use_case: Any | None = None,
) -> None:
    """Register ping, validate_strategy, and get_audit_log MCP tools.

    Parameters
    ----------
    mcp:
        FastMCP server tools are registered on.
    bot_manager:
        Captured in each tool closure (S8 / H4).
    validate_strategy_use_case:
        Pre-built ``ValidateStrategyUseCase``. When supplied, the
        ``validate_strategy`` tool reuses it on every call instead of
        rebuilding (M2). When ``None``, the tool builds one per call
        (legacy behaviour, retained for ad-hoc callers).
    """

    @mcp.tool(
        name="ping",
        description=(
            "Health check — returns server status, uptime, and whether "
            "the Hyperliquid connection is available."
        ),
    )
    def ping() -> str:
        """Return server health status."""
        status = bot_manager.get_status()
        return json.dumps(
            {
                "status": "ok",
                "uptime_seconds": status.get("uptime_seconds", 0),
                "hyperliquid_connected": bot_manager.has_exchange,
                "bot_running": status.get("is_running", False),
            },
            indent=2,
            default=str,
        )

    @mcp.tool(
        name="validate_strategy",
        description=(
            "Validate a YAML strategy file without starting a bot. "
            "Returns whether the strategy is valid, its name, primary "
            "timeframe, indicator count, and any errors."
        ),
    )
    def validate_strategy(strategy_path: str) -> str:
        """Validate a strategy file."""
        if not Path(strategy_path).exists():
            return json.dumps(
                {
                    "valid": False,
                    "errors": [f"File not found: {strategy_path}"],
                },
                indent=2,
            )

        content = Path(strategy_path).read_text(encoding="utf-8")
        use_case = validate_strategy_use_case
        if use_case is None:
            # Legacy path for ad-hoc callers that don't supply a prebuilt
            # use case. The composition root always supplies one (M2).
            from finbot.startup.service_factory import (
                create_validate_strategy_use_case,
            )

            use_case = create_validate_strategy_use_case()
        request = ValidateStrategyRequest(
            strategy_path=strategy_path, strategy_content=content
        )
        result = use_case.validate(request)

        return json.dumps(
            {
                "valid": result.valid,
                "strategy_name": result.strategy_name,
                "schema_version": result.schema_version,
                "primary_timeframe": result.primary_timeframe,
                "indicator_count": result.indicator_count,
                "errors": result.errors,
            },
            indent=2,
        )

    @mcp.tool(
        name="get_audit_log",
        description=(
            "Retrieve recent audit log entries. Optionally filter by "
            "event_type (e.g. 'enrichment_validation_failed'). "
            "Returns entries in reverse chronological order."
        ),
    )
    def get_audit_log(
        limit: int = 50,
        event_type: str | None = None,
    ) -> str:
        """Return recent audit log entries."""
        entries = bot_manager.get_audit_log(limit=limit, event_type=event_type)
        return json.dumps(
            {
                "count": len(entries),
                "entries": [
                    {
                        "entry_id": e.entry_id,
                        "bot_run_id": e.bot_run_id,
                        "event_type": e.event_type,
                        "event_data_json": e.event_data_json,
                        "created_at": (
                            e.created_at.isoformat() if e.created_at else None
                        ),
                    }
                    for e in entries
                ],
            },
            indent=2,
        )
