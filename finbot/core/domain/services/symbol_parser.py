"""Pure domain service: parse a symbol string into a ParsedSymbol.

Detects HIP-3 vault perpetuals (dex:COIN format) vs standard perps.
No I/O — testable without any infrastructure.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class ParsedSymbol:
    """Result of parsing a symbol string.

    Attributes:
        raw: The original symbol string as passed by the user.
        is_hip3: True if this is a HIP-3 vault perp (contains `:`).
        dex: Lowercase DEX provider name (e.g. "flx"). Empty for standard perps.
        coin: Uppercase coin ticker (e.g. "TSLA"). Empty for standard perps.
        api_symbol: Normalized symbol for API calls.
            "dex:coin" for HIP-3, raw for standard.
    """

    raw: str
    is_hip3: bool
    dex: str = ""
    coin: str = ""
    api_symbol: str = ""


def parse_symbol(raw: str) -> ParsedSymbol:
    """Parse a symbol string into a structured ParsedSymbol.

    Standard perps: "BTC", "ETH" → is_hip3=False, api_symbol="BTC"
    HIP-3 perps: "flx:TSLA", "xyz:AAPL" → is_hip3=True, dex="flx", coin="TSLA"

    Args:
        raw: The symbol string to parse.

    Returns:
        ParsedSymbol with normalized dex (lowercase), coin (uppercase), and api_symbol.

    Raises:
        ValueError: If the symbol is empty, whitespace-only, or has an invalid
            HIP-3 format (missing dex, missing coin, or too many colons).
    """
    if not raw or not raw.strip():
        raise ValueError("symbol must not be empty")

    if ":" not in raw:
        return ParsedSymbol(raw=raw, is_hip3=False, api_symbol=raw)

    parts = raw.split(":")
    if len(parts) != 2 or not parts[0] or not parts[1]:
        raise ValueError(f"Invalid HIP-3 symbol format: {raw!r}")

    dex = parts[0].lower()
    coin = parts[1].upper()
    api_symbol = f"{dex}:{coin}"

    return ParsedSymbol(
        raw=raw,
        is_hip3=True,
        dex=dex,
        coin=coin,
        api_symbol=api_symbol,
    )
