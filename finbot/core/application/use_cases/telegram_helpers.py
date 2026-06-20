"""Module-level helpers for Telegram command handlers.

Extracted from handle_telegram_command.py to keep that file under the
project's size limits. Pure functions + constants, no class state.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from finbot.core.domain.services.symbol_parser import parse_symbol

# Characters that MUST be escaped in Telegram MarkdownV2.
# See: https://core.telegram.org/bots/api#markdownv2-style
_MDV2_ESCAPE_CHARS = str.maketrans(
    {
        "_": "\\_",
        "*": "\\*",
        "[": "\\[",
        "]": "\\]",
        "(": "\\(",
        ")": "\\)",
        "~": "\\~",
        "`": "\\`",
        ">": "\\>",
        "#": "\\#",
        "+": "\\+",
        "-": "\\-",
        "=": "\\=",
        "|": "\\|",
        "{": "\\{",
        "}": "\\}",
        ".": "\\.",
        "!": "\\!",
    }
)

_DEFAULT_SYMBOLS = ("BTC", "ETH", "SOL", "ARB", "DOGE")
_DEFAULT_INTERVALS = ("1m", "5m", "15m", "1h", "4h", "1d")


def _escape_mdv2(text: str) -> str:
    """Escape special characters for Telegram MarkdownV2."""
    return str(text).translate(_MDV2_ESCAPE_CHARS)


def _normalize_symbol(raw: str) -> str:
    """Normalize a standard or HIP-3 symbol for API/callback use."""
    parsed = parse_symbol(raw.strip())
    return parsed.api_symbol.upper() if not parsed.is_hip3 else parsed.api_symbol


def _get_symbol_groups(
    metadata_provider: object | None,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Return ``(crypto_perps, hip3_perps)`` from Hyperliquid or defaults.

    Standard crypto perps are symbols without ``:``. HIP-3 vault perps use
    ``dex:COIN`` and are separated so Telegram can show a category menu before
    rendering a potentially huge symbol list.
    """
    symbols: tuple[str, ...] = _DEFAULT_SYMBOLS
    if metadata_provider is not None and hasattr(metadata_provider, "list_symbols"):
        try:
            listed = metadata_provider.list_symbols()
            if listed:
                symbols = tuple(_normalize_symbol(str(s)) for s in listed)
        except Exception:
            symbols = _DEFAULT_SYMBOLS

    crypto = tuple(sorted(s for s in symbols if ":" not in s))
    hip3 = tuple(sorted(s for s in symbols if ":" in s))
    return crypto, hip3


def _get_symbols(metadata_provider: object | None) -> tuple[str, ...]:
    """Return available symbols from Hyperliquid, or defaults on failure."""
    crypto, hip3 = _get_symbol_groups(metadata_provider)
    return crypto + hip3


def _parse_brackets(tokens: list[str]):
    """Parse optional ``sl <price>`` and ``tp <price>`` from arg tokens.

    Returns ``(sl_price, tp_price, error)``. Prices are Decimal or None.
    ``error`` is a human-readable string when parsing fails, else None.
    """
    sl_price = None
    tp_price = None
    i = 0
    while i < len(tokens):
        tok = tokens[i].lower()
        if tok in ("sl", "tp"):
            if i + 1 >= len(tokens):
                return None, None, f"{tok.upper()} requires a price"
            try:
                val = Decimal(tokens[i + 1])
            except (InvalidOperation, ValueError):
                return None, None, f"Invalid {tok.upper()} price"
            if tok == "sl":
                sl_price = val
            else:
                tp_price = val
            i += 2
            continue
        return None, None, f"Unexpected token: {tokens[i]}"
    return sl_price, tp_price, None
