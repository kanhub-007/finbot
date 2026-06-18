"""Architecture tests: dead numpy/pandas domain code is removed (S12).

Closes H7 from the code review remediation spec.

H7 (High): ``volume_profile.py`` (456 lines), ``amt_signals.py`` (215),
``auction_state.py`` (117), ``_profile_utils.py`` live in
``core/domain/services/`` but (a) import ``numpy``/``pandas`` — heavy
scientific frameworks the AGENTS.md purity rule forbids in domain — (b)
reimplement indicator computation the ``finbar-strategy-runtime`` package
owns, and (c) are not imported by any production code under ``finbot/``.
They predate the package migration and were left behind.

The fix deletes the four files + the corresponding test, and tightens
the architecture purity test to forbid ``numpy``/``pandas`` under
``core/domain/`` so the regression is locked out.
"""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DOMAIN_SERVICES = ROOT / "finbot" / "core" / "domain" / "services"


DEAD_DOMAIN_MODULES = [
    "volume_profile.py",
    "amt_signals.py",
    "auction_state.py",
    "_profile_utils.py",
]


@pytest.mark.parametrize("module", DEAD_DOMAIN_MODULES)
def test_dead_domain_module_removed(module: str) -> None:
    """The four dead numpy/pandas domain modules must be gone."""
    target = DOMAIN_SERVICES / module
    assert not target.exists(), (
        f"Dead domain module still present: {target}. "
        f"These files import numpy/pandas (violating domain purity) and "
        f"are not imported by any production code — delete them (H7)."
    )


@pytest.mark.parametrize(
    "path",
    sorted(
        p.relative_to(ROOT) for p in (ROOT / "finbot" / "core" / "domain").rglob("*.py")
    ),
    ids=lambda p: str(p),
)
def test_domain_file_does_not_import_numpy_or_pandas(path: Path) -> None:
    """No file under core/domain/ may import numpy or pandas.

    Domain entities/services must be pure (AGENTS.md §4). numpy/pandas are
    framework dependencies belonging in infrastructure/ only. The deleted
    volume_profile module was the sole offender; this test locks the rule
    in so it can't regress.
    """
    text = (ROOT / path).read_text(encoding="utf-8")
    assert "import numpy" not in text, f"{path}: numpy imported in domain (H7)"
    assert "from numpy" not in text, f"{path}: numpy imported in domain (H7)"
    assert "import pandas" not in text, f"{path}: pandas imported in domain (H7)"
    assert "from pandas" not in text, f"{path}: pandas imported in domain (H7)"
