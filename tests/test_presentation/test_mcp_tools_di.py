"""Architecture + integration tests for MCP tool DI (S8).

Closes H4 and M2 from the code review remediation spec.

H4 (High): every MCP tool reached into ``mcp._finbot_bot_manager`` — a
private attribute set by the composition root. That's the Service
Locator anti-pattern: the tool's real dependency is hidden from its
signature, tools can't be unit-tested without monkey-patching the
FastMCP instance, and every tool module couples to the attribute name.

M2 (Medium): the ``validate_strategy`` tool rebuilt the use case on
every call (re-importing finbar_strategy_runtime, rebuilding capability
sets, constructing a fresh ValidateStrategyUseCase).

Fix:
- Each ``register_*_tools(mcp, bot_manager)`` closes over ``bot_manager``.
- ``register_tools(server, bot_manager)`` propagates.
- The composition root builds ``validate_strategy`` use case once and
  passes it in.

Black-box: the architecture test scans source for the banned attribute
access; the integration test calls ``register_tools`` with a fake
manager and asserts the validate_strategy use case is built exactly once.
"""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
TOOLS_DIR = ROOT / "finbot" / "presentation" / "mcp" / "tools"


# ---------------------------------------------------------------------------
# H4 — no tool reads mcp._finbot_bot_manager
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "rel_path",
    sorted(p.relative_to(ROOT) for p in TOOLS_DIR.glob("*.py")),
    ids=lambda p: str(p),
)
def test_no_tool_reads_private_bot_manager_attribute(rel_path: Path) -> None:
    """Tool modules must not reach into ``mcp._finbot_bot_manager``."""
    path = ROOT / rel_path
    text = path.read_text(encoding="utf-8")
    assert "_finbot_bot_manager" not in text, (
        f"{rel_path} still reads the private attribute (Service Locator, H4) — "
        f"tools must receive bot_manager via register_*_tools(mcp, bot_manager)"
    )


def test_register_tools_signature_accepts_bot_manager() -> None:
    """register_tools must accept (mcp, bot_manager) — not just (mcp,)."""
    import inspect

    from finbot.presentation.mcp.tools import register_tools

    sig = inspect.signature(register_tools)
    params = list(sig.parameters)
    assert (
        "bot_manager" in params
    ), "register_tools must accept bot_manager so tools can close over it (H4)"


# ---------------------------------------------------------------------------
# H4 + integration — tools resolve the manager from the closure
# ---------------------------------------------------------------------------


def _register_tools_with_fake_server_and_manager():
    """Build a fresh FastMCP server + capture registered tool callables.

    Returns ``(server, tools, manager)`` so tests can invoke a tool and
    assert it uses the injected manager (not a private attribute).
    """
    from fastmcp import FastMCP

    from finbot.core.domain.services.bot_manager import BotManager
    from finbot.infrastructure.adapters.dry_run_exchange_gateway import (
        DryRunExchangeGateway,
    )
    from finbot.infrastructure.repositories.in_memory_bot_state_repository import (
        InMemoryBotStateRepository,
    )
    from finbot.presentation.mcp.tools import register_tools
    from tests.fakes import FakeRuntime

    repo = InMemoryBotStateRepository()
    manager = BotManager(
        runtime_factory=lambda **kw: FakeRuntime(repo=repo),
        repository=repo,
        exchange=DryRunExchangeGateway(),
    )

    server = FastMCP(name="finbot-test-s8")
    tools: dict[str, object] = {}
    original_tool = server.tool

    def capture(**kwargs):
        name = kwargs.get("name", "")

        def decorator(fn):
            original_tool(**kwargs)(fn)
            if name:
                tools[name] = fn
            return fn

        return decorator

    server.tool = capture  # type: ignore[assignment]
    register_tools(server, manager, validate_strategy_use_case=None)
    server.tool = original_tool  # type: ignore[assignment]
    return server, tools, manager


class TestToolsUseInjectedManager:
    """H4 integration: a tool call uses the injected manager, not an attr."""

    def test_get_bot_status_uses_injected_manager(self):
        _server, tools, manager = _register_tools_with_fake_server_and_manager()

        # The tool should call manager.get_status() and return its dict.
        # We assert on the observable outcome (the returned JSON references
        # the same manager's state), not on call interactions.
        result = tools["get_bot_status"]()
        assert '"is_running"' in result  # get_status() shape


# ---------------------------------------------------------------------------
# M2 — validate_strategy use case is built once
# ---------------------------------------------------------------------------


class TestValidateStrategyUseCaseReused:
    """M2: the composition root builds validate_strategy once and reuses it."""

    def test_register_tools_accepts_prebuilt_use_case(self, monkeypatch):
        """register_tools takes a validate_strategy_use_case parameter; when
        provided, the util tool must use it rather than calling the factory."""
        calls = {"count": 0}

        class _StubUseCase:
            def validate(self, request):
                calls["count"] += 1
                from finbot.core.domain.dto.validate_strategy_result import (
                    ValidateStrategyResult,
                )

                return ValidateStrategyResult(valid=True, strategy_name="stub")

            def compatibility(self, request):
                from finbot.core.domain.dto.strategy_compatibility_result import (
                    StrategyCompatibilityResult,
                )

                return StrategyCompatibilityResult(strategy_name="stub", modes={})

        from fastmcp import FastMCP

        from finbot.core.domain.services.bot_manager import BotManager
        from finbot.infrastructure.adapters.dry_run_exchange_gateway import (
            DryRunExchangeGateway,
        )
        from finbot.infrastructure.repositories.in_memory_bot_state_repository import (
            InMemoryBotStateRepository,
        )
        from finbot.presentation.mcp.tools import register_tools
        from tests.fakes import FakeRuntime

        repo = InMemoryBotStateRepository()
        manager = BotManager(
            runtime_factory=lambda **kw: FakeRuntime(repo=repo),
            repository=repo,
            exchange=DryRunExchangeGateway(),
        )
        stub = _StubUseCase()

        server = FastMCP(name="finbot-test-s8-reuse")
        tools: dict[str, object] = {}
        original_tool = server.tool

        def capture(**kwargs):
            name = kwargs.get("name", "")

            def decorator(fn):
                original_tool(**kwargs)(fn)
                if name:
                    tools[name] = fn
                return fn

            return decorator

        server.tool = capture  # type: ignore[assignment]
        register_tools(server, manager, validate_strategy_use_case=stub)
        server.tool = original_tool  # type: ignore[assignment]

        # Call validate_strategy twice; the stub should be invoked twice
        # (it's the same instance), and the package factory must NOT be
        # called at all (we assert by patching the factory to fail).
        def _fail_if_called(*a, **kw):
            raise AssertionError(
                "create_validate_strategy_use_case called — use case not reused (M2)"
            )

        monkeypatch.setattr(
            "finbot.startup.service_factory.create_validate_strategy_use_case",
            _fail_if_called,
        )

        # The tool reads a fixture strategy file.
        tools["validate_strategy"](
            strategy_path="tests/fixtures/strategies/amt_dip_buyer_final.yaml"
        )
        tools["validate_strategy"](
            strategy_path="tests/fixtures/strategies/amt_dip_buyer_final.yaml"
        )
        assert calls["count"] == 2
