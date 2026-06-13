"""Deterministic client order ID (cloid) generator.

Pure domain service — produces collision-resistant, idempotent
order IDs so the exchange gateway can safely retry submissions.
"""

from uuid import uuid4


class CloidGenerator:
    """Generate deterministic client order IDs for idempotent submission.

    Each call to ``generate()`` produces a unique ID.  When a strategy
    signal contains a known prefix, the ID is derived from it so the
    same signal always maps to the same cloid.
    """

    def generate(self, signal_key: str = "", attempt: int = 0) -> str:
        """Return a cloid string.

        Args:
            signal_key: Optional signal key to seed the cloid for
                        deterministic reuse.
            attempt: Retry attempt number appended as suffix.
        """
        if signal_key:
            safe = signal_key.replace(":", "_").replace(" ", "_")[:80]
            return f"finbot_{safe}_{attempt}"
        return f"finbot_{uuid4().hex[:8]}"
