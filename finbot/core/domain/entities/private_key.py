"""PrivateKey — a secret-bearing value object that never exposes the raw
key via ``__repr__`` / ``__str__``.

The Hyperliquid private key is correctly typed ``SecretStr`` in
:class:`Settings`, but it used to be unwrapped to a plain ``str`` that
flowed through :class:`BotConfig` and the exchange gateway as a bare
attribute. Any ``repr`` of those objects (or an accidental
``logger.debug(obj.__dict__)`` bypassing the log redactor) would expose
the key.

``PrivateKey`` wraps the raw value so ``repr``/``str`` redact, while a
single ``raw`` accessor exposes it for the signing boundary
(``HyperliquidExchangeGateway._ensure_exchange``).

The entity is a **pure data holder**: no ``eth_account`` import (that
conversion stays in infrastructure) and no validation (an empty key is
allowed so dry-run can run without one; format validation stays at the
gateway boundary via ``validate_private_key``).
"""

from __future__ import annotations

from typing import Any

_REPR = "PrivateKey(***)"


class PrivateKey:
    """Redacting holder for a wallet private key.

    Parameters
    ----------
    raw:
        The raw key string. May be empty (dry-run). Never validated here —
        format validation happens at the gateway boundary.
    """

    __slots__ = ("_raw",)

    def __init__(self, raw: str = "") -> None:
        self._raw = raw

    @property
    def raw(self) -> str:
        """Return the raw key for use at the signing boundary."""
        return self._raw

    def __repr__(self) -> str:
        return _REPR

    def __str__(self) -> str:
        return _REPR

    def __eq__(self, other: object) -> bool:
        if isinstance(other, PrivateKey):
            return self._raw == other._raw
        return NotImplemented

    def __hash__(self) -> int:
        return hash(self._raw)

    def __len__(self) -> int:
        return len(self._raw)

    @classmethod
    def _coerce(cls, value: PrivateKey | str | None) -> PrivateKey:
        """Coerce a str/None to a PrivateKey; pass through if already one.

        Used by constructors that accept backward-compatible ``str`` inputs.
        """
        if value is None:
            return cls("")
        if isinstance(value, PrivateKey):
            return value
        if isinstance(value, str):
            return cls(value)
        return cls(str(value))


def coerce_private_key(value: Any) -> PrivateKey:
    """Public helper: coerce ``str | PrivateKey | None`` to ``PrivateKey``."""
    return PrivateKey._coerce(value)
