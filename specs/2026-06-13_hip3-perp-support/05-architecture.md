# ADR-8: HIP-3 symbols detected via `:` separator, not config flag

**Context:**
HIP-3 perpetuals use `dex:COIN` format (e.g. `flx:TSLA`) while standard perps use plain names (e.g. `BTC`). We could use a config flag or a symbol registry to indicate which symbols are HIP-3, but this adds configuration burden and can drift.

**Decision:**
Detect HIP-3 symbols by the presence of `:` in the symbol string. A pure `SymbolParser` domain service splits on `:` and validates the format. The API routing happens in infrastructure adapters (market data stream, metadata provider, bar source) — the application layer never sees the difference.

**Consequences:**
- Zero configuration needed — just pass `xyz:AAPL` as the symbol
- Standard perps are completely unaffected (no `:` in name)
- If Hyperliquid ever adds a standard perp with `:` in its name, this breaks. Unlikely given current naming conventions.
- The `SymbolParser` is a pure domain service, testable without any I/O.

---

# ADR-9: DEX provider list is cached, not discovered per-request

**Context:**
The list of HIP-3 DEX providers changes infrequently. Calling `info.perp_dexs()` on every metadata or candle request adds latency and rate-limit consumption.

**Decision:**
Cache the DEX list for 5 minutes (matching Finbar's convention). Use a class-level cache in the metadata provider. Individual token metadata within a DEX is fetched on-demand (not pre-cached).

**Consequences:**
- New DEXes appear within 5 minutes of being added
- No rate-limit penalty for DEX discovery
- Token-level metadata (szDecimals, etc.) is still fetched per-request (acceptable since it's infrequent)
