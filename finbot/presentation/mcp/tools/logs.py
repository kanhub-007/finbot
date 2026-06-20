"""MCP tools — strategy evaluation log viewer."""

import json
from typing import Any

from fastmcp import FastMCP


def register_log_tools(
    mcp: FastMCP, bot_manager: Any, log_reader: Any | None = None
) -> None:
    """Register strategy-log MCP tools."""

    if log_reader is None:
        return

    @mcp.tool(
        name="list_strategy_logs",
        description="List available strategy evaluation log files.",
    )
    def list_strategy_logs() -> str:
        return json.dumps(log_reader.list_logs(), indent=2)

    @mcp.tool(
        name="get_strategy_log",
        description=(
            "Read the last N entries from a strategy evaluation log. "
            "NAME is the log file name from list_strategy_logs. "
            "N defaults to 20."
        ),
    )
    def get_strategy_log(name: str, n: int = 20) -> str:
        strategy, symbol = log_reader.parse_log_name(name)
        entries = log_reader.read_tail(strategy, symbol, n=n)
        return json.dumps(entries, indent=2, default=str)
