"""Mode/URL consistency guard — pure domain helper.

Rejects mode / ``FINBOT_HYPERLIQUID_TESTNET`` combinations that would route
orders to the wrong environment. Both the CLI and the MCP ``start_bot`` tool
call this so there is a single authority for the rule (C4 from the code
review remediation spec).

Mirrors the shape of :func:`live_mode_guard.check_live_mode`:
pure (no Settings, no I/O, no exceptions), returns a reasons list
(empty = consistent).
"""

from __future__ import annotations


def check_mode_url_consistency(
    *,
    mode: str,
    hyperliquid_testnet: bool,
) -> list[str]:
    """Return reasons why *mode* and the testnet flag are inconsistent.

    Parameters
    ----------
    mode:
        Requested execution mode (``"dry_run"``, ``"testnet"``, ``"live"``).
    hyperliquid_testnet:
        Value of ``FINBOT_HYPERLIQUID_TESTNET`` — selects the SDK base URL.

    Returns
    -------
    list[str]
        Empty when consistent. One human-readable reason per violation.
        ``dry_run`` never submits orders so it is always considered consistent.
    """
    reasons: list[str] = []

    if mode == "testnet" and not hyperliquid_testnet:
        reasons.append(
            "FINBOT_HYPERLIQUID_TESTNET must be true for testnet mode "
            "(otherwise orders would route to mainnet)"
        )

    if mode == "live" and hyperliquid_testnet:
        reasons.append(
            "FINBOT_HYPERLIQUID_TESTNET must be false for live mode "
            "(otherwise orders would route to testnet)"
        )

    return reasons
