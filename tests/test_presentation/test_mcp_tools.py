"""Integration tests for MCP tools.

Tests the MCP presentation layer with a fake BotManager wired in.
Tool functions are registered on a FastMCP server via
``register_tools(server, manager)`` (S8) — each tool closes over the
manager instead of reading a private attribute off the server.

Each tool function is called directly (the functions are captured during
registration). This avoids coupling to FastMCP 3.x internal call_tool API.

Design note: the tools dict is cached at module level because FastMCP
tool registration is one-shot and server construction is expensive.
Tests that mutate state (start/stop) must clean up with ``stop_bot()``
in their teardown.  This is acceptable because pytest runs tests in
this file sequentially.
"""

import json
import time

from finbot.core.domain.services.bot_manager import BotManager
from finbot.infrastructure.adapters.dry_run_exchange_gateway import (
    DryRunExchangeGateway,
)
from finbot.infrastructure.repositories.in_memory_bot_state_repository import (
    InMemoryBotStateRepository,
)
from tests.fakes import FakeRuntime

# ---------------------------------------------------------------------------
# Fixture — shared across all tests in this module (see design note above)
# ---------------------------------------------------------------------------


def _build_tools():
    """Build a FastMCP server with a fake BotManager and register all tools.

    The tool functions are captured during registration and returned in a
    dict mapping tool_name -> callable.
    """
    from fastmcp import FastMCP
    from pathlib import Path

    repo = InMemoryBotStateRepository()
    exchange = DryRunExchangeGateway()

    def _factory(**kw):
        path = kw.get("strategy_path", "")
        if path and not Path(path).exists():
            return {
                "status": "rejected",
                "message": f"Strategy file not found: {path}",
            }
        return FakeRuntime(repo=repo)

    manager = BotManager(
        runtime_factory=_factory,
        repository=repo,
        exchange=exchange,
        startup_time=time.time(),
    )

    server = FastMCP(name="finbot-test")

    # Capture tool functions during registration by intercepting @mcp.tool()
    tools: dict[str, object] = {}
    _original_tool = server.tool

    def _capture(**kwargs):
        name = kwargs.get("name", "")

        def decorator(fn):
            _original_tool(**kwargs)(fn)
            if name:
                tools[name] = fn
            return fn

        return decorator

    server.tool = _capture  # type: ignore[assignment]

    from finbot.presentation.mcp.tools import register_tools

    register_tools(server, manager)
    server.tool = _original_tool  # type: ignore[assignment]

    return tools


_tools_cache: dict[str, object] | None = None


def _tools():
    """Lazy-load the shared tools dict (module-level, see design note)."""
    global _tools_cache
    if _tools_cache is None:
        _tools_cache = _build_tools()
    return _tools_cache


# ---------------------------------------------------------------------------
# Tests — Slice 1: bot_control tools
# ---------------------------------------------------------------------------


class TestMCPStartBot:
    """start_bot tool."""

    def test_start_dry_run_returns_running(self):
        tools = _tools()
        result = tools["start_bot"](
            strategy_path="tests/fixtures/strategies/amt_dip_buyer_final.yaml",
            symbol="BTC",
            interval="1h",
            mode="dry_run",
            warmup_bars=0,
        )
        data = json.loads(result)
        assert data["status"] == "running"
        assert data["bot_run_id"]
        tools["stop_bot"]()

    def test_start_invalid_strategy_rejected(self):
        tools = _tools()
        result = tools["start_bot"](
            strategy_path="/nonexistent/path.yaml",
            symbol="BTC",
            interval="1h",
            mode="dry_run",
            warmup_bars=0,
        )
        data = json.loads(result)
        assert data["status"] == "rejected"

    def test_start_while_running_rejected(self):
        tools = _tools()
        tools["start_bot"](
            strategy_path="tests/fixtures/strategies/amt_dip_buyer_final.yaml",
            symbol="BTC",
            interval="1h",
            mode="dry_run",
            warmup_bars=0,
        )
        result = tools["start_bot"](
            strategy_path="tests/fixtures/strategies/amt_dip_buyer_final.yaml",
            symbol="ETH",
            interval="1h",
            mode="dry_run",
            warmup_bars=0,
        )
        data = json.loads(result)
        assert data["status"] == "rejected"
        tools["stop_bot"]()


class TestMCPStopBot:
    """stop_bot tool."""

    def test_stop_running_bot(self):
        tools = _tools()
        tools["start_bot"](
            strategy_path="tests/fixtures/strategies/amt_dip_buyer_final.yaml",
            symbol="BTC",
            interval="1h",
            mode="dry_run",
            warmup_bars=0,
        )
        result = tools["stop_bot"]()
        data = json.loads(result)
        assert data["status"] == "stopped"

    def test_stop_when_no_bot(self):
        tools = _tools()
        result = tools["stop_bot"]()
        data = json.loads(result)
        assert data["status"] == "no_bot_running"


class TestMCPGetBotStatus:
    """get_bot_status tool."""

    def test_status_when_no_bot(self):
        tools = _tools()
        tools["stop_bot"]()  # ensure clean
        result = tools["get_bot_status"]()
        data = json.loads(result)
        assert data["is_running"] is False

    def test_status_when_bot_running(self):
        tools = _tools()
        tools["start_bot"](
            strategy_path="tests/fixtures/strategies/amt_dip_buyer_final.yaml",
            symbol="BTC",
            interval="1h",
            mode="dry_run",
            warmup_bars=0,
        )
        result = tools["get_bot_status"]()
        data = json.loads(result)
        assert data["is_running"] is True
        assert data["symbol"] == "BTC"
        assert data["mode"] == "dry_run"
        tools["stop_bot"]()


# ---------------------------------------------------------------------------
# Tests — Slice 2: bot_history tools
# ---------------------------------------------------------------------------


class TestMCPListBotRuns:
    """list_bot_runs tool."""

    def test_list_runs_empty(self):
        tools = _tools()
        tools["stop_bot"]()
        result = tools["list_bot_runs"]()
        data = json.loads(result)
        assert data["count"] >= 0

    def test_list_runs_after_bot(self):
        tools = _tools()
        tools["stop_bot"]()
        before = json.loads(tools["list_bot_runs"]())["count"]

        tools["start_bot"](
            strategy_path="tests/fixtures/strategies/amt_dip_buyer_final.yaml",
            symbol="BTC",
            interval="1h",
            mode="dry_run",
            warmup_bars=0,
        )
        tools["stop_bot"]()

        after = json.loads(tools["list_bot_runs"]())["count"]
        assert after >= before + 1


class TestMCPGetBotRunResults:
    """get_bot_run_results tool."""

    def test_nonexistent_run_returns_error(self):
        tools = _tools()
        result = tools["get_bot_run_results"](run_id="nonexistent")
        data = json.loads(result)
        assert "error" in data


# ---------------------------------------------------------------------------
# Tests — Slice 3: safety and utility tools
# ---------------------------------------------------------------------------


class TestMCPPanic:
    """panic tool."""

    def test_panic_stops_bot(self):
        tools = _tools()
        tools["start_bot"](
            strategy_path="tests/fixtures/strategies/amt_dip_buyer_final.yaml",
            symbol="BTC",
            interval="1h",
            mode="dry_run",
            warmup_bars=0,
        )
        result = tools["panic"](cancel_orders=True, symbol="BTC")
        data = json.loads(result)
        assert data["bot_stopped"] is True

    def test_panic_when_no_bot(self):
        tools = _tools()
        result = tools["panic"](cancel_orders=True, symbol="BTC")
        data = json.loads(result)
        assert "bot_stopped" in data


class TestMCPPing:
    """ping tool."""

    def test_ping_returns_ok(self):
        tools = _tools()
        result = tools["ping"]()
        data = json.loads(result)
        assert data["status"] == "ok"
        assert "uptime_seconds" in data


class TestMCPValidateStrategy:
    """validate_strategy tool."""

    def test_validate_valid_strategy(self):
        tools = _tools()
        result = tools["validate_strategy"](
            strategy_path="tests/fixtures/strategies/amt_dip_buyer_final.yaml",
        )
        data = json.loads(result)
        assert data["valid"] is True
        assert data["strategy_name"]

    def test_validate_nonexistent_strategy(self):
        tools = _tools()
        result = tools["validate_strategy"](
            strategy_path="/nonexistent/path.yaml",
        )
        data = json.loads(result)
        assert data["valid"] is False


class TestMCPGetAuditLog:
    """get_audit_log tool."""

    def test_audit_log_empty(self):
        tools = _tools()
        result = tools["get_audit_log"]()
        data = json.loads(result)
        assert data["count"] == 0
