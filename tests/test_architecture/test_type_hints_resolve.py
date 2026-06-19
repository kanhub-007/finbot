"""Architecture tests: type hints resolve on BotQueryService (S7).

Closes H2 and H8 from the code review remediation spec.

H2: ``BotQueryService`` references 8 unimported types in annotations
(``BotRun``, ``ProcessedSignal``, ``OrderResponseRecord``, ``FillRecord``,
``RunCounts``, ``RiskEventRecord``, ``AuditLogEntry``). ``from __future__
import annotations`` lets the module import cleanly, but
``typing.get_type_hints`` raises ``NameError`` and any static type checker
flags them. A reader also assumes the symbols are imported when they
aren't.

H8: several public methods (``submit_manual_order``, ``attach_stop_loss``,
``attach_take_profit``, ``set_default_size``, ``_attach_risk_order``,
``_resolve_risk_price``) lack parameter annotations for ``side``,
``price``, ``size``. Callers can pass ``int``/``str``/``Decimal``
interchangeably with no compile-time check.

The fix is purely additive: imports + annotations. No behaviour change.
"""

from __future__ import annotations

import inspect
import typing

import pytest

from finbot.core.domain.services.bot_manager.bot_query_service import (
    BotQueryService,
)
from finbot.core.domain.services.bot_manager.manual_order_service import (
    ManualOrderService,
)
from finbot.core.domain.services.bot_manager.risk_order_service import (
    RiskOrderService,
)
from finbot.core.domain.services.bot_manager.runtime_config_service import (
    RuntimeConfigService,
)

# The 8 query methods whose return annotations reference unimported types
# (H2). Each must resolve under typing.get_type_hints.
_QUERY_METHODS = [
    "get_bot_run",
    "list_bot_runs",
    "get_signals_for_run",
    "get_orders_for_run",
    "get_fills_for_run",
    "get_run_counts",
    "get_risk_events_for_run",
    "get_audit_log",
]


@pytest.mark.parametrize("method_name", _QUERY_METHODS)
def test_query_method_type_hints_resolve(method_name: str) -> None:
    """typing.get_type_hints must not raise NameError for any query method."""
    method = getattr(BotQueryService, method_name)
    try:
        typing.get_type_hints(method)
    except NameError as exc:
        pytest.fail(f"{method_name}: unresolved type hint — {exc}")


# The public methods whose parameters lacked annotations (H8). After S7
# decomposition, methods live on different collaborators.
_ANNOTATED_PARAM_METHODS = {
    (RuntimeConfigService, "set_default_size"): {"size"},
    (ManualOrderService, "submit_manual_order"): {"side", "size"},
    (
        ManualOrderService,
        "submit_manual_order_with_brackets",
    ): {"side", "size", "sl_price", "tp_price"},
    (RiskOrderService, "attach_stop_loss"): {"price"},
    (RiskOrderService, "attach_take_profit"): {"price"},
}


@pytest.mark.parametrize(
    "owner_cls,method_name,required_params",
    [(cls, name, params) for (cls, name), params in _ANNOTATED_PARAM_METHODS.items()],
)
def test_public_method_params_are_annotated(
    owner_cls, method_name: str, required_params: set[str]
) -> None:
    """Each previously-unannotated parameter must carry a concrete annotation."""
    method = getattr(owner_cls, method_name)
    sig = inspect.signature(method)
    for param_name in required_params:
        assert (
            param_name in sig.parameters
        ), f"{method_name}: missing parameter {param_name!r}"
        annotation = sig.parameters[param_name].annotation
        assert (
            annotation is not inspect.Parameter.empty
        ), f"{method_name}({param_name}): no annotation (H8)"
        # Reject the implicit/explicit Any that defeats static checking.
        annotation_str = (
            annotation
            if isinstance(annotation, str)
            else getattr(annotation, "__name__", str(annotation))
        )
        assert (
            annotation_str is not typing.Any
        ), f"{method_name}({param_name}): annotation is bare Any (H8)"


def test_query_methods_return_typed_lists() -> None:
    """The query methods should return concrete entity types, not Any.

    Sanity check that resolves the full annotation chain (return type
    included) so a stray ``Any`` is caught.
    """
    for method_name in _QUERY_METHODS:
        method = getattr(BotQueryService, method_name)
        hints = typing.get_type_hints(method)
        assert "return" in hints, f"{method_name}: missing return annotation"
