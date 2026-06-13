"""Tests for SymbolParser — HIP-3 symbol parsing."""

import pytest

from finbot.core.domain.services.symbol_parser import ParsedSymbol, parse_symbol


class TestSymbolParser:
    """SymbolParser converts a raw symbol string into a ParsedSymbol."""

    # ── Standard perps ──

    def test_standard_perp_btc(self) -> None:
        result = parse_symbol("BTC")
        assert result.is_hip3 is False
        assert result.raw == "BTC"
        assert result.api_symbol == "BTC"
        assert result.dex == ""
        assert result.coin == ""

    def test_standard_perp_eth(self) -> None:
        result = parse_symbol("ETH")
        assert result.is_hip3 is False
        assert result.api_symbol == "ETH"

    def test_standard_perp_lowercase_is_preserved(self) -> None:
        """Standard perps pass through as-is — no coercion."""
        result = parse_symbol("btc")
        assert result.is_hip3 is False
        assert result.api_symbol == "btc"

    # ── HIP-3 perps ──

    def test_hip3_xyz_aapl(self) -> None:
        result = parse_symbol("xyz:AAPL")
        assert result.is_hip3 is True
        assert result.raw == "xyz:AAPL"
        assert result.dex == "xyz"
        assert result.coin == "AAPL"
        assert result.api_symbol == "xyz:AAPL"

    def test_hip3_flx_tsla(self) -> None:
        result = parse_symbol("flx:TSLA")
        assert result.is_hip3 is True
        assert result.dex == "flx"
        assert result.coin == "TSLA"
        assert result.api_symbol == "flx:TSLA"

    def test_hip3_km_aapl(self) -> None:
        result = parse_symbol("km:AAPL")
        assert result.is_hip3 is True
        assert result.dex == "km"
        assert result.coin == "AAPL"
        assert result.api_symbol == "km:AAPL"

    def test_hip3_normalizes_dex_to_lowercase(self) -> None:
        """DEX part is always lowercased for API consistency."""
        result = parse_symbol("FLX:TSLA")
        assert result.dex == "flx"
        assert result.api_symbol == "flx:TSLA"

    def test_hip3_normalizes_coin_to_uppercase(self) -> None:
        """Coin part is always uppercased."""
        result = parse_symbol("xyz:aapl")
        assert result.coin == "AAPL"
        assert result.api_symbol == "xyz:AAPL"

    def test_hip3_dex_preserves_internal_case(self) -> None:
        """Only lowercased for API; raw is preserved."""
        result = parse_symbol("vNTL:AAPL")
        assert result.dex == "vntl"
        assert result.api_symbol == "vntl:AAPL"

    # ── Edge cases & validation ──

    def test_empty_symbol_raises(self) -> None:
        with pytest.raises(ValueError, match="must not be empty"):
            parse_symbol("")

    def test_whitespace_only_raises(self) -> None:
        with pytest.raises(ValueError, match="must not be empty"):
            parse_symbol("   ")

    def test_only_colon_raises(self) -> None:
        with pytest.raises(ValueError, match="Invalid HIP-3"):
            parse_symbol(":")

    def test_missing_dex_raises(self) -> None:
        with pytest.raises(ValueError, match="Invalid HIP-3"):
            parse_symbol(":AAPL")

    def test_missing_coin_raises(self) -> None:
        with pytest.raises(ValueError, match="Invalid HIP-3"):
            parse_symbol("xyz:")

    def test_too_many_colons_raises(self) -> None:
        with pytest.raises(ValueError, match="Invalid HIP-3"):
            parse_symbol("a:b:c")

    def test_parsed_symbol_dataclass(self) -> None:
        p = ParsedSymbol(raw="xyz:AAPL", is_hip3=True, dex="xyz", coin="AAPL", api_symbol="xyz:AAPL")
        assert p.raw == "xyz:AAPL"
        assert p.is_hip3 is True
