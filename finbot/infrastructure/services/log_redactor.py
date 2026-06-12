"""Log redaction — strips secrets from log messages before emission."""

import re
from typing import Any

# Hex-encoded private key pattern (with or without 0x prefix).
_PK_RE = re.compile(r"(?:0x)?[0-9a-fA-F]{64}", re.IGNORECASE)

# Sentinel value patterns that should never appear in logs.
_SENTINEL_RE = re.compile(r"secret|private.?key|mnemonic|passphrase", re.IGNORECASE)

# Values to replace matched patterns with.
_REDACTED = "***REDACTED***"


def redact(value: Any, max_len: int = 200) -> str:
    """Return a string representation of *value* with secrets redacted.

    * Hex strings ≥ 64 characters are replaced.
    * The word "secret", "private_key", "mnemonic", or "passphrase"
      followed by any value triggers full redaction.

    Parameters
    ----------
    value:
        Any object (str, int, dict, Exception, etc.).
    max_len:
        Maximum length of the returned string before truncation.
    """
    text = str(value)
    if _SENTINEL_RE.search(text):
        return _REDACTED
    return _PK_RE.sub(_REDACTED, text)[:max_len]


def validate_private_key(key: str) -> str:
    """Validate a private key and raise if missing or malformed.

    Returns the key unchanged when valid.

    Raises
    ------
    ValueError
        When the key is empty, too short, or non-hex.
    """
    if not key:
        raise ValueError("Private key is empty — set FINBOT_HYPERLIQUID_PRIVATE_KEY")
    if len(key) < 64:
        raise ValueError(
            f"Private key too short ({len(key)} chars) — expected 64 hex chars"
        )
    # Accept with or without 0x prefix.
    stripped = key[2:] if key.startswith("0x") else key
    try:
        int(stripped, 16)
    except ValueError:
        raise ValueError("Private key is not valid hex") from None
    return key
