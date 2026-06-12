"""Non-retryable error — signals a permanent failure that must not retry."""


class NonRetryableError(RuntimeError):
    """Raised when an operation should not be retried.

    Use for: invalid order, insufficient margin, bad signature,
    unknown symbol, and other exchange errors where retrying would
    either be pointless or dangerous.
    """
