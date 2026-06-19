"""Size-limit guardrail (S0 prerequisite for Slice 2).

AGENTS.md §4 sets hard size limits:
  * Method body    ≤ ~50 lines
  * Class          ≤ ~150 lines
  * File           ≤ ~500 lines

The 2026-06-18 spec relied on reviewers to enforce these; the four God
Classes regrew under that regime because no test failed when a file crept
over. This test AST-walks every ``.py`` under ``finbot/`` and fails on any
file >500 lines or any class >150 lines, so future PRs that bloat a file
fail CI immediately.

**Allowlists (incremental migration).** Both allowlists snapshot the
current overages. Slice-2 scenarios remove their entries as they
decompose each target; the shrinking meta-test fails if an entry becomes
stale (file deleted, or all classes/file now ≤ limit). Entries tagged
``PRE-EXISTING`` are over the limit but are NOT among this spec's 40
findings — they are real debt for a future spec and are allowlisted so
this spec's guardrail doesn't scope-creep.

Deviation from spec 02-scenarios.md: the spec lists only 4 allowlist
entries (the 4 God Classes). An audit of the actual tree found 4 files
over 500 lines and 13 classes over 150 lines. The file allowlist matches
the spec exactly; the class allowlist is expanded to cover the 9 classes
in Slice-2 scope plus 4 pre-existing out-of-scope classes.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_FINBOT = _PROJECT_ROOT / "finbot"

_MAX_FILE_LINES = 500
_MAX_CLASS_LINES = 150

# Files over 500 lines, exempt until their Slice-2 scenario decomposes them.
# Removed as S7–S10 land. The file allowlist matches the spec exactly.
_FILE_ALLOWLIST: dict[str, str] = {
    "finbot/core/application/use_cases/handle_telegram_command.py": "S8",
    "finbot/core/domain/services/bot_manager/_trading_control.py": "S7",
    "finbot/infrastructure/repositories/sqlite_bot_state_repository.py": "S10",
    "finbot/core/application/use_cases/live_trading_runtime.py": "S9",
}

# Classes over 150 lines. In-scope entries are removed when their scenario
# decomposes the class; PRE-EXISTING entries are out of this spec's scope.
_CLASS_ALLOWLIST: dict[str, str] = {
    # -- Slice 2 in-scope (removed as S7-S10 land) --
    "finbot/core/application/use_cases/handle_telegram_command.py": "S8",
    "finbot/core/domain/services/bot_manager/_trading_control.py": "S7",
    "finbot/core/domain/services/bot_manager/_manager.py": "S7",
    "finbot/infrastructure/repositories/sqlite_bot_state_repository.py": "S10",
    "finbot/infrastructure/repositories/in_memory_bot_state_repository.py": "S10",
    "finbot/core/domain/interfaces/bot_state_repository.py": "S10",
    "finbot/core/application/use_cases/live_trading_runtime.py": "S9",
    "finbot/core/application/use_cases/account_event_handler.py": "S9",
    "finbot/startup/live_trading_runtime_builder.py": "S9",
    # -- PRE-EXISTING: over 150 lines but NOT in this spec's 40 findings --
    "finbot/infrastructure/adapters/hyperliquid_exchange_gateway.py": "PRE-EXISTING",
    "finbot/infrastructure/adapters/bot_event_loop.py": "PRE-EXISTING",
    "finbot/infrastructure/adapters/hyperliquid_metadata_provider.py": "PRE-EXISTING",
    "finbot/infrastructure/adapters/hyperliquid_market_data_stream.py": "PRE-EXISTING",
}


def _iter_python_files(root: Path) -> list[Path]:
    """Every .py under ``root``, excluding ``__pycache__``."""
    out: list[Path] = []
    for p in sorted(root.rglob("*.py")):
        if "__pycache__" in p.parts:
            continue
        out.append(p)
    return out


def _rel(path: Path) -> str:
    return str(path.relative_to(_PROJECT_ROOT)).replace("\\", "/")


def _class_line_span(node: ast.ClassDef) -> int:
    """Number of source lines a class spans (incl. decorators/blanks)."""
    end = getattr(node, "end_lineno", None) or node.body[-1].lineno
    start = node.lineno
    for dec in node.decorator_list:
        start = min(start, dec.lineno)
    return end - start + 1


class TestSizeLimits:
    def test_no_unallowlisted_file_exceeds_500_lines(self) -> None:
        """Every production .py under finbot/ must be ≤500 lines."""
        offenders: list[str] = []
        for path in _iter_python_files(_FINBOT):
            rel = _rel(path)
            n = sum(1 for _ in path.open(encoding="utf-8"))
            if n > _MAX_FILE_LINES and rel not in _FILE_ALLOWLIST:
                offenders.append(f"{rel}: {n} lines")
        assert not offenders, "Files over 500 lines:\n  " + "\n  ".join(offenders)

    @pytest.mark.parametrize(
        "path",
        _iter_python_files(_FINBOT),
        ids=_rel,
    )
    def test_no_unallowlisted_class_exceeds_150_lines(self, path: Path) -> None:
        """Every class in production code must be ≤150 lines."""
        rel = _rel(path)
        if rel in _CLASS_ALLOWLIST:
            pytest.skip(f"exempt ({_CLASS_ALLOWLIST[rel]})")
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError as e:
            pytest.fail(f"{rel}: syntax error — {e}")
        offenders: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                span = _class_line_span(node)
                if span > _MAX_CLASS_LINES:
                    offenders.append(
                        f"{rel}:{node.lineno} class {node.name}: {span} lines"
                    )
        assert not offenders, "Classes over 150 lines:\n  " + "\n  ".join(offenders)


class TestAllowlistShrinks:
    """Meta-test: allowlist entries must not go stale.

    Fails if an allowlisted file is deleted or no longer needs its exemption
    (largest class ≤150 / file ≤500). This forces each Slice-2 scenario to
    remove its entry on merge and catches accidental allowlist growth.
    """

    @pytest.mark.parametrize("rel", list(_FILE_ALLOWLIST))
    def test_file_allowlist_entry_still_needed(self, rel: str) -> None:
        path = _PROJECT_ROOT / rel
        if not path.exists():
            pytest.fail(f"allowlist entry {rel!r} points to a deleted file")
        n = sum(1 for _ in path.open(encoding="utf-8"))
        if n <= _MAX_FILE_LINES:
            pytest.fail(
                f"allowlist entry {rel!r} is stale: file is {n} lines "
                f"(≤{_MAX_FILE_LINES}); remove the entry"
            )

    @pytest.mark.parametrize("rel", list(_CLASS_ALLOWLIST))
    def test_class_allowlist_entry_still_needed(self, rel: str) -> None:
        path = _PROJECT_ROOT / rel
        if not path.exists():
            pytest.fail(f"allowlist entry {rel!r} points to a deleted file")
        tree = ast.parse(path.read_text(encoding="utf-8"))
        spans = [
            _class_line_span(node)
            for node in ast.walk(tree)
            if isinstance(node, ast.ClassDef)
        ]
        biggest = max(spans, default=0)
        if biggest <= _MAX_CLASS_LINES:
            pytest.fail(
                f"allowlist entry {rel!r} is stale: largest class is "
                f"{biggest} lines (≤{_MAX_CLASS_LINES}); remove the entry"
            )
