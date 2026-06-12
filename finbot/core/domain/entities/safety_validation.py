"""Safety validation result — Result/Either pattern for validation outcomes."""

from dataclasses import dataclass


@dataclass(frozen=True)
class SafetyValidation:
    """Collects all validation errors at once instead of returning early.

    Usage:
        SafetyValidation.success()
        SafetyValidation.failure("live mode requires ...", "stale_data_seconds ...")
    """

    is_valid: bool
    errors: tuple[str, ...]

    @classmethod
    def success(cls) -> "SafetyValidation":
        """Return a passing validation with zero errors."""
        return cls(is_valid=True, errors=())

    @classmethod
    def failure(cls, *errors: str) -> "SafetyValidation":
        """Return a failing validation with one or more error messages."""
        if not errors:
            raise ValueError("failure() requires at least one error message")
        return cls(is_valid=False, errors=errors)

    def merge(self, other: "SafetyValidation") -> "SafetyValidation":
        """Combine two validations into one.

        If both are valid the result is valid; otherwise concatenate errors.
        """
        return SafetyValidation(
            is_valid=self.is_valid and other.is_valid,
            errors=self.errors + other.errors,
        )
