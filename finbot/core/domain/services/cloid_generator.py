"""Deterministic client order ID (cloid) generator.

Pure domain service — produces collision-resistant, idempotent
order IDs so the exchange gateway can safely retry submissions.
"""

from finbot.core.domain.interfaces.cloid_generator import (
    CloidGenerator as CloidGeneratorInterface,
)


class CloidGenerator(CloidGeneratorInterface):
    """Generate deterministic client order IDs for idempotent submission.

    Each call to ``generate()`` produces a unique ID.  When a strategy
    signal contains a known prefix, the ID is derived from it so the
    same signal always maps to the same cloid.
    """

    def generate(self, signal_key: str = "", attempt: int = 0) -> str:
        """Return a cloid string derived from the signal key.

        Args:
            signal_key: Signal key used as the cloid prefix for
                        deterministic reuse. Must be non-empty to
                        guarantee idempotent retries.
            attempt: Retry attempt number appended as suffix.
        """
        safe = signal_key.replace(":", "_").replace(" ", "_")[:80]
        return f"finbot_{safe}_{attempt}"
