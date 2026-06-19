"""Tests for PrivateKey value-object hygiene (S4: M5).

The Hyperliquid private key is correctly typed ``SecretStr`` in
``Settings``, but ``create_bot_config`` previously unwrapped it to a plain
``str`` that flowed through ``BotConfig.private_key`` to
``HyperliquidExchangeGateway._private_key``. Any ``repr(bot_config)`` or
``repr(gateway)`` (or an accidental ``logger.debug(gateway.__dict__)``
bypassing the redacting filter) would expose the key.

This pins the contract: the key is carried as a ``PrivateKey`` value
object whose ``__repr__``/``__str__`` redact, and is unwrapped only at
the signing boundary inside the gateway.
"""

from __future__ import annotations

import logging

import pytest

from finbot.core.domain.entities.bot_config import BotConfig
from finbot.core.domain.entities.private_key import PrivateKey
from finbot.infrastructure.adapters.hyperliquid_exchange_gateway import (
    HyperliquidExchangeGateway,
)
from finbot.infrastructure.services.log_redactor import SecretRedactingFilter

_KEY = "0x" + "a" * 64


class TestPrivateKeyRedaction:
    def test_private_key_repr_does_not_leak(self) -> None:
        pk = PrivateKey(_KEY)
        assert _KEY not in repr(pk)
        assert _KEY not in str(pk)
        assert "REDACTED" in repr(pk) or "***" in repr(pk)

    def test_private_key_raw_is_available(self) -> None:
        """The raw value is available for the signing boundary."""
        pk = PrivateKey(_KEY)
        assert pk.raw == _KEY

    def test_private_key_empty_allowed_for_dry_run(self) -> None:
        """An empty key must not raise (dry-run runs without a key)."""
        pk = PrivateKey("")
        assert pk.raw == ""


class TestBotConfigSecretHygiene:
    def test_bot_config_field_is_private_key_not_str(self) -> None:
        cfg = BotConfig(private_key=PrivateKey(_KEY))
        assert isinstance(cfg.private_key, PrivateKey)

    def test_bot_config_repr_does_not_leak_key(self) -> None:
        cfg = BotConfig(private_key=PrivateKey(_KEY))
        assert _KEY not in repr(cfg)

    def test_bot_config_accepts_str_and_wraps(self) -> None:
        """Backward-compat: a raw str is coerced to PrivateKey on construction."""
        cfg = BotConfig(private_key=_KEY)
        assert isinstance(cfg.private_key, PrivateKey)
        assert _KEY not in repr(cfg)


class TestGatewaySecretHygiene:
    def test_gateway_repr_does_not_leak_key(self) -> None:
        gw = HyperliquidExchangeGateway(private_key=PrivateKey(_KEY), base_url="x")
        assert _KEY not in repr(gw)

    def test_gateway_stored_attribute_is_private_key(self) -> None:
        gw = HyperliquidExchangeGateway(private_key=PrivateKey(_KEY), base_url="x")
        assert isinstance(gw._private_key, PrivateKey)
        assert _KEY not in repr(gw._private_key)

    def test_gateway_accepts_str_and_wraps(self) -> None:
        gw = HyperliquidExchangeGateway(private_key=_KEY, base_url="x")
        assert isinstance(gw._private_key, PrivateKey)
        assert _KEY not in repr(gw)

    def test_accidental_debug_log_of_gateway_repr_does_not_leak(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Defence in depth: even ``logger.debug('gateway=%r', gw)`` is
        redacted by the SecretRedactingFilter (in case repr changes)."""
        gw = HyperliquidExchangeGateway(private_key=PrivateKey(_KEY), base_url="x")
        logger = logging.getLogger("test_secret_hygiene")
        logger.addFilter(SecretRedactingFilter())
        logger.setLevel(logging.DEBUG)
        with caplog.at_level(logging.DEBUG, logger="test_secret_hygiene"):
            logger.debug("gateway=%r", gw)
        for record in caplog.records:
            assert _KEY not in str(record.msg)
