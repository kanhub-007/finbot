"""FormulaNode — expression AST node for formula features."""

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class FormulaNode:
    """A node in a formula expression tree.

    Leaf nodes have a kind (field, indicator, feature, literal) and value.
    Operator nodes have an op and left/right children.
    """

    op: str = ""
    """Operator: >, <, +, -, *, /, and, or, not, abs, or empty for leaf."""

    kind: str = ""
    """Operand kind for leaf nodes: field, indicator, feature, literal."""

    value: Any = None
    """Value for leaf nodes."""

    label: str = ""
    """Original label for explanations."""

    left: "FormulaNode | None" = None
    """Left child for binary operators."""

    right: "FormulaNode | None" = None
    """Right child for binary operators."""

    children: list["FormulaNode"] = field(default_factory=list)
    """Children for n-ary operators like and/or."""
