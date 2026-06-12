"""Tests for RetryPolicy domain service."""

import pytest

from finbot.core.domain.entities.non_retryable_error import (
    NonRetryableError,
)
from finbot.core.domain.services.retry_policy import RetryPolicy


class TestRetryPolicy:
    def test_transient_error_retries_with_backoff(self) -> None:
        policy = RetryPolicy(max_retries=2, base_delay=0.01, max_delay=0.05)
        attempts = []

        def flaky() -> str:
            attempts.append(1)
            if len(attempts) < 3:
                raise ConnectionError("transient")
            return "ok"

        result = policy.execute(flaky)
        assert result == "ok"
        assert len(attempts) == 3  # initial + 2 retries

    def test_non_retryable_error_does_not_retry(self) -> None:
        policy = RetryPolicy(max_retries=3, base_delay=0.01)

        def bad_order() -> str:
            raise RuntimeError("insufficient margin for order")

        with pytest.raises(NonRetryableError, match="insufficient margin"):
            policy.execute(bad_order)

    def test_non_retryable_error_subclass_stops_immediately(self) -> None:
        policy = RetryPolicy(max_retries=3)

        def bad() -> str:
            raise NonRetryableError("bad signature")

        with pytest.raises(NonRetryableError, match="bad signature"):
            policy.execute(bad)

    def test_order_retry_requires_cloid(self) -> None:
        policy = RetryPolicy()

        def submit() -> str:
            return "ok"

        # No cloid = should reject
        with pytest.raises(NonRetryableError, match="cloid"):
            policy.execute(submit, require_cloid="")

        # With cloid = should succeed
        result = policy.execute(submit, require_cloid="cloid-123")
        assert result == "ok"

    def test_exhausted_retries_raises_runtime_error(self) -> None:
        policy = RetryPolicy(max_retries=1, base_delay=0.01)

        def always_fails() -> str:
            raise ConnectionError("timeout")

        with pytest.raises(RuntimeError, match="failed after"):
            policy.execute(always_fails)

    def test_non_retryable_substring_match_is_case_insensitive(self) -> None:
        policy = RetryPolicy(max_retries=2)

        def fail() -> str:
            raise RuntimeError("Unauthorized access")

        with pytest.raises(NonRetryableError, match="Unauthorized"):
            policy.execute(fail)

    def test_unknown_symbol_detected_as_non_retryable(self) -> None:
        policy = RetryPolicy(non_retryable_substrings=["unknown symbol"])

        def fail() -> str:
            raise RuntimeError("order rejected: unknown symbol")

        with pytest.raises(NonRetryableError):
            policy.execute(fail)
