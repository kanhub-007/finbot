"""Architecture guardrail tests for Finbot dependency rules.

These tests enforce Clean Architecture boundaries and verify that Finbot
is standalone (no runtime dependency on Finbar).
"""

import ast
from pathlib import Path

import pytest


def _is_init_only_module(import_path: str) -> bool:
    """Return True when the *only* reason a module appears is an __init__.py
    with zero substantive code.

    We do allow empty __init__.py files everywhere.
    """
    return import_path.endswith("__init__.py")


def _collect_imports(file_path: Path) -> dict[str, set[str]]:
    """Parse a .py file and return {toplevel_module: {full_import_names}}."""
    tree = ast.parse(file_path.read_text(encoding="utf-8"))
    imports: dict[str, set[str]] = {}

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                top = alias.name.split(".")[0]
                imports.setdefault(top, set()).add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module is None:
                continue
            top = node.module.split(".")[0]
            full = node.module
            if node.level and node.level > 0:
                full = "." * node.level + (node.module or "")
            imports.setdefault(top, set()).add(full)

    return imports


def _walk_finbot_sources(layer_dir: str) -> list[Path]:
    """Return all .py files under finbot/layer_dir (relative to project root)."""
    root = Path(__file__).resolve().parents[2]
    target = root / "finbot" / layer_dir
    if not target.is_dir():
        return []
    return sorted(target.rglob("*.py"))


def _all_finbot_production_sources() -> list[Path]:
    """Return every .py file under finbot/ (production code only)."""
    root = Path(__file__).resolve().parents[2]
    target = root / "finbot"
    return sorted(target.rglob("*.py"))


class TestDomainLayerImports:
    """finbot/core/domain must not import infrastructure, adapters, or
    external heavy libraries."""

    FORBIDDEN = {"finbar", "hyperliquid", "sqlalchemy", "fastapi"}

    @pytest.mark.parametrize(
        "file_path",
        [
            p
            for p in _walk_finbot_sources("core/domain")
            if not _is_init_only_module(str(p))
        ],
        ids=lambda p: str(p.relative_to(Path(__file__).resolve().parents[2])),
    )
    def test_domain_file_has_no_forbidden_imports(self, file_path: Path):
        imports = _collect_imports(file_path)
        violations: set[str] = set()
        for forbidden in self.FORBIDDEN:
            if forbidden in imports:
                violations.update(imports[forbidden])

        assert not violations, (
            f"{file_path.name} imports forbidden modules: "
            f"{sorted(violations)}. "
            f"Domain layer must not import finbar, hyperliquid, sqlalchemy, "
            f"or fastapi."
        )

    @pytest.mark.parametrize(
        "file_path",
        [
            p
            for p in _walk_finbot_sources("core/domain")
            if not _is_init_only_module(str(p))
        ],
        ids=lambda p: str(p.relative_to(Path(__file__).resolve().parents[2])),
    )
    def test_domain_file_has_no_infrastructure_imports(self, file_path: Path):
        imports = _collect_imports(file_path)
        violations: set[str] = set()
        if "finbot" in imports:
            for imp in imports["finbot"]:
                parts = imp.split(".")
                if len(parts) >= 3 and parts[1] == "infrastructure":
                    violations.add(imp)

        assert not violations, (
            f"{file_path.name} imports infrastructure: "
            f"{sorted(violations)}. "
            f"Domain layer must not import finbot.infrastructure."
        )

    @pytest.mark.parametrize(
        "file_path",
        [
            p
            for p in _walk_finbot_sources("core/domain")
            if not _is_init_only_module(str(p))
        ],
        ids=lambda p: str(p.relative_to(Path(__file__).resolve().parents[2])),
    )
    def test_domain_file_has_no_pydantic_settings_imports(self, file_path: Path):
        imports = _collect_imports(file_path)
        violations: set[str] = set()
        if "pydantic_settings" in imports:
            violations.update(imports["pydantic_settings"])

        assert not violations, (
            f"{file_path.name} imports pydantic_settings: "
            f"{sorted(violations)}. "
            f"Domain layer must not import pydantic_settings."
        )


class TestApplicationLayerImports:
    """finbot/core/application must not import infrastructure, adapters, or
    external heavy libraries."""

    FORBIDDEN = {"finbar", "hyperliquid", "sqlalchemy", "fastapi"}

    @pytest.mark.parametrize(
        "file_path",
        [
            p
            for p in _walk_finbot_sources("core/application")
            if not _is_init_only_module(str(p))
        ],
        ids=lambda p: str(p.relative_to(Path(__file__).resolve().parents[2])),
    )
    def test_application_file_has_no_forbidden_imports(self, file_path: Path):
        imports = _collect_imports(file_path)
        violations: set[str] = set()
        for forbidden in self.FORBIDDEN:
            if forbidden in imports:
                violations.update(imports[forbidden])

        assert not violations, (
            f"{file_path.name} imports forbidden modules: "
            f"{sorted(violations)}. "
            f"Application layer must not import finbar, hyperliquid, "
            f"sqlalchemy, or fastapi."
        )

    @pytest.mark.parametrize(
        "file_path",
        [
            p
            for p in _walk_finbot_sources("core/application")
            if not _is_init_only_module(str(p))
        ],
        ids=lambda p: str(p.relative_to(Path(__file__).resolve().parents[2])),
    )
    def test_application_file_has_no_infrastructure_imports(self, file_path: Path):
        imports = _collect_imports(file_path)
        violations: set[str] = set()
        if "finbot" in imports:
            for imp in imports["finbot"]:
                parts = imp.split(".")
                if len(parts) >= 3 and parts[1] == "infrastructure":
                    violations.add(imp)

        assert not violations, (
            f"{file_path.name} imports infrastructure: "
            f"{sorted(violations)}. "
            f"Application layer must not import finbot.infrastructure."
        )


class TestNoFinbarInProductionCode:
    """No production code under finbot/ may import finbar at runtime."""

    @pytest.mark.parametrize(
        "file_path",
        [
            p
            for p in _all_finbot_production_sources()
            if not _is_init_only_module(str(p))
        ],
        ids=lambda p: str(p.relative_to(Path(__file__).resolve().parents[2])),
    )
    def test_production_code_does_not_import_finbar(self, file_path: Path):
        imports = _collect_imports(file_path)
        violations: set[str] = set()
        if "finbar" in imports:
            violations.update(imports["finbar"])

        assert not violations, (
            f"{file_path.name} imports finbar: {sorted(violations)}. "
            f"Finbot must be standalone at runtime."
        )


_PACKAGE_INFRA_ONLY_SUBPACKAGES = {"parser", "evaluation", "indicators"}


class TestPackageSubpackageAllowlist:
    """finbar_strategy_runtime.parser/evaluation/indicators are infra-only.

    The package's pure ``domain.entities.*`` / ``domain.interfaces.*``
    subpackages are a legitimate domain-layer dependency (ADR-5). The
    ``parser`` (PyYAML), ``evaluation`` (stateful engine), and
    ``indicators`` (pandas/numpy) subpackages are infrastructure-tier and
    must stay out of Finbot's domain/application/presentation layers —
    they live behind concrete adapters in infrastructure/, wired in
    startup/.
    """

    @staticmethod
    def _package_imports(file_path: Path) -> set[str]:
        """Return the set of finbar_strategy_runtime.* import roots in a file."""
        imports = _collect_imports(file_path).get("finbar_strategy_runtime", set())
        return imports

    def _violation_for(self, imp: str) -> str | None:
        """Return the offending subpackage name, or None if the import is pure."""
        parts = imp.split(".")
        if len(parts) >= 2 and parts[1] in _PACKAGE_INFRA_ONLY_SUBPACKAGES:
            return imp
        return None

    @pytest.mark.parametrize(
        "file_path",
        [
            p
            for p in (
                _walk_finbot_sources("core/domain")
                + _walk_finbot_sources("core/application")
                + _walk_finbot_sources("presentation")
            )
            if not _is_init_only_module(str(p))
        ],
        ids=lambda p: str(p.relative_to(Path(__file__).resolve().parents[2])),
    )
    def test_inner_layers_do_not_import_package_infra_subpackages(
        self, file_path: Path
    ):
        violations = [
            imp
            for imp in self._package_imports(file_path)
            if self._violation_for(imp)
        ]
        assert not violations, (
            f"{file_path.name} imports package infra subpackages: "
            f"{sorted(violations)}. Only finbar_strategy_runtime.domain.* "
            f"is permitted in domain/application/presentation layers; "
            f"parser/evaluation/indicators belong to infrastructure only."
        )


class TestCopiedRuntimeModules:
    """Guardrails for code copied from Finbar into finbot/infrastructure/strategy/.

    These tests will be empty (trivially pass) until files are copied in
    later phases. Once files exist they prevent accidental Finbar imports
    and ban Finbar presentation/startup code.
    """

    @staticmethod
    def _strategy_runtime_files() -> list[Path]:
        root = Path(__file__).resolve().parents[2]
        target = root / "finbot" / "infrastructure" / "strategy"
        if not target.is_dir():
            return []
        return sorted(
            p for p in target.rglob("*.py") if not _is_init_only_module(str(p))
        )

    def test_copied_runtime_modules_do_not_import_finbar(self) -> None:
        """Every file under infrastructure/strategy/ must not import finbar."""
        files = self._strategy_runtime_files()
        if not files:
            pytest.skip("No copied runtime modules yet")

        root = Path(__file__).resolve().parents[2]
        violations: dict[str, set[str]] = {}
        for file_path in files:
            imports = _collect_imports(file_path)
            if "finbar" in imports:
                violations[str(file_path.relative_to(root))] = imports["finbar"]

        assert not violations, (
            f"Copied runtime modules import finbar: {violations}. "
            f"All imports must be rewritten to finbot.*."
        )

    def test_copied_runtime_no_finbar_presentation_or_startup(self) -> None:
        """Copied modules must not transitively pull in Finbar presentation/startup."""
        files = self._strategy_runtime_files()
        if not files:
            pytest.skip("No copied runtime modules yet")

        root = Path(__file__).resolve().parents[2]
        violations: dict[str, set[str]] = {}
        for file_path in files:
            imports = _collect_imports(file_path)
            if "finbar" in imports:
                for imp in imports["finbar"]:
                    parts = imp.split(".")
                    if len(parts) >= 3 and parts[1] in (
                        "presentation",
                        "startup",
                    ):
                        key = str(file_path.relative_to(root))
                        violations.setdefault(key, set()).add(imp)

        assert not violations, (
            f"Copied runtime modules import Finbar presentation/startup: "
            f"{violations}. Only strategy runtime code may be copied."
        )
