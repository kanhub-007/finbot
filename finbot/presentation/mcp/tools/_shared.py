"""Shared helpers for MCP tool modules.

S8 (H4): tool modules receive ``bot_manager`` via the
``register_*_tools(mcp, bot_manager)`` closure rather than reading a
private attribute off the FastMCP instance. This module is retained as
the canonical import target for any future cross-tool helpers; it
currently exports nothing because no shared helper is needed.
"""

from __future__ import annotations
