"""Retry policy — exponential backoff with non-retryable error detection.

Pure domain service with no I/O.  Used by exchange gateways and
websocket reconnect logic.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import TypeVar

from finbot.core.domain.entities.non_retryable_error import NonRetryableError

T = TypeVar("T")

# Substrings in exchange error messages that should never be retried.
_DEFAULT_NON_RETRYABLE = [
    "invalid order",
    "insufficient margin",
    "bad signature",
    "unknown symbol",
    "order does not exist",
    "not found",
    "unauthorized",
    "rate limited",
]


class RetryPolicy:
    """Exponential backoff with non-retryable error classification.

    Parameters
    ----------
    max_retries:
        Maximum number of retry attempts (not including the initial
        try).  Default 3.
    base_delay:
        Initial delay in seconds between retries.  Doubles each
        attempt, capped at *max_delay*.  Default 1 second.
    max_delay:
        Maximum delay in seconds.  Default 30 seconds.
    non_retryable_substrings:
        List of substrings that, when found in an exception message,
        classify the error as non-retryable.
    """

    def __init__(
        self,
        max_retries: int = 3,
        base_delay: float = 1.0,
        max_delay: float = 30.0,
        non_retryable_substrings: list[str] | None = None,
    ) -> None:
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self._non_retryable = non_retryable_substrings or list(_DEFAULT_NON_RETRYABLE)

    # -- public API --------------------------------------------------------

    def is_non_retryable(self, error: Exception) -> bool:
        """Return True when *error* should not be retried.

        ``NonRetryableError`` instances always return True.  Other
        exceptions are checked against the configured substring list.
        """
        if isinstance(error, NonRetryableError):
            return True
        msg = str(error).lower()
        for sub in self._non_retryable:
            if sub in msg:
                return True
        return False

    def execute(
        self,
        operation: Callable[[], T],
        require_cloid: str | None = None,
    ) -> T:
        """Execute *operation* with retries and backoff.

        Parameters
        ----------
        operation:
            Callable to invoke.
        require_cloid:
            When set, a ``NonRetryableError`` is raised if no
            idempotent client-order-ID is provided.  This prevents
            blind retries of order submissions.

        Returns
        -------
        The return value of *operation*.

        Raises
        ------
        NonRetryableError
            When *require_cloid* is set but empty, or when the
            error is classified as non-retryable.
        RuntimeError
            When max retries are exhausted.
        """
        if require_cloid is not None and not require_cloid:
            raise NonRetryableError("Order retry requires an idempotent cloid")

        delay = self.base_delay
        last_error: Exception | None = None

        for attempt in range(self.max_retries + 1):
            try:
                return operation()
            except NonRetryableError:
                raise
            except Exception as exc:
                last_error = exc
                if self.is_non_retryable(exc):
                    raise NonRetryableError(str(exc)) from exc
                if attempt < self.max_retries:
                    time.sleep(delay)
                    delay = min(delay * 2, self.max_delay)

        raise RuntimeError(
            f"Operation failed after {self.max_retries} retries: " f"{last_error}"
        ) from last_error
