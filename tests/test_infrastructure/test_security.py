"""Tests for security — secrets, redaction, and validation."""

import pytest
from pydantic import SecretStr

from finbot.config.settings import Settings
from finbot.infrastructure.services.log_redactor import (
    SecretRedactingFilter,
    redact,
    setup_logging,
    validate_private_key,
)


class TestSettingsSecrets:
    def test_settings_repr_does_not_expose_private_key(self) -> None:
        settings = Settings(hyperliquid_private_key=SecretStr("0xabcd1234"))
        rep = repr(settings)
        assert "0xabcd1234" not in rep
        assert "SecretStr" in rep or "**********" in rep

    def test_private_key_is_not_required_for_dry_run(self, monkeypatch) -> None:
        """Dry-run mode must work with an empty private key."""
        # Isolate from the local .env so the test is deterministic.
        monkeypatch.setenv("FINBOT_HYPERLIQUID_PRIVATE_KEY", "")
        settings = Settings(_env_file=None, mode="dry_run")
        assert settings.hyperliquid_private_key.get_secret_value() == ""


class TestLogRedaction:
    def test_hex_key_is_redacted(self) -> None:
        result = redact("key=0x" + "a" * 64)
        assert "0x" + "a" * 64 not in result
        assert "REDACTED" in result

    def test_sentinel_words_trigger_redaction(self) -> None:
        assert redact("private_key=abc123") == "***REDACTED***"
        assert redact("the secret is 42") == "***REDACTED***"
        assert redact("mnemonic phrase here") == "***REDACTED***"

    def test_normal_text_passes_through(self) -> None:
        result = redact("order submitted: BTC BUY 0.001 @ 50000")
        assert result == "order submitted: BTC BUY 0.001 @ 50000"

    def test_filter_redacts_log_record(self) -> None:
        import logging

        filt = SecretRedactingFilter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="secret=0x" + "a" * 64,
            args=(),
            exc_info=None,
        )
        assert filt.filter(record) is True
        assert "0x" + "a" * 64 not in str(record.msg)
        assert "REDACTED" in str(record.msg)

    def test_filter_installed_by_setup(self) -> None:
        import logging

        root = logging.getLogger()
        was_empty = len(root.filters) == 0
        setup_logging()
        assert any(isinstance(f, SecretRedactingFilter) for f in root.filters)
        # Idempotent.
        before = len(root.filters)
        setup_logging()
        assert len(root.filters) == before
        if was_empty:
            root.filters.clear()


class TestPrivateKeyValidation:
    def test_valid_key_passes(self) -> None:
        key = "0x" + "a" * 64
        assert validate_private_key(key) == key

    def test_key_without_prefix_passes(self) -> None:
        key = "a" * 64
        assert validate_private_key(key) == key

    def test_empty_key_raises(self) -> None:
        with pytest.raises(ValueError, match="empty"):
            validate_private_key("")

    def test_short_key_raises(self) -> None:
        with pytest.raises(ValueError, match="too short"):
            validate_private_key("abc")

    def test_non_hex_key_raises(self) -> None:
        with pytest.raises(ValueError, match="not valid hex"):
            validate_private_key("g" * 64)
