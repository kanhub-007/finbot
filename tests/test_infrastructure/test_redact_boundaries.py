"""Tests for redact() word boundaries (S23: L4)."""
from finbot.infrastructure.services.log_redactor import redact

class TestRedactBoundaries:
    def test_substring_in_identifier_does_not_over_redact(self):
        """'secretsManager' (compound identifier) should NOT trigger full redaction.

        Before the \b fix, the regex matched 'secret' inside 'secretsManager',
        redacting legitimate identifiers. Word boundaries fix this.
        """
        result = redact("Initializing secretsManager pool")
        assert result != "***REDACTED***"

    def test_private_key_assignment_still_redacts(self):
        assert redact("private_key=abc123") == "***REDACTED***"

    def test_secret_still_redacts(self):
        assert redact("the secret is 42") == "***REDACTED***"
