"""Domain interface for trading strategies.

Strategies implement on_bar() — called once per bar by the backtest
engine. Strategies contain pure trading logic with no framework
dependencies. This is the contract that custom (AI-generated) strategies
must fulfill.
"""

from abc import ABC, abstractmethod

from finbot.core.domain.entities.signal_result import SignalResult
from finbot.core.domain.entities.strategy_meta import StrategyMeta


class TradingStrategy(ABC):
    """Abstract trading strategy — called once per bar by the backtest engine.

    Implementations define ``meta()`` (static metadata) and ``on_bar()``
    (trading logic). The engine provides the current bar and position state;
    the strategy returns a SignalResult.
    """

    @abstractmethod
    def meta(self) -> StrategyMeta:
        """Return strategy metadata.

        Returns:
            StrategyMeta with name, variant, description, required indicators,
            and default parameters.
        """
        ...

    def on_reset(self) -> None:
        """Reset internal strategy state for a new backtest run.

        Called by the backtest engine before starting a new run.
        Stateful strategies (e.g. SMA crossover) should clear their
        internal tracking variables here. Stateless strategies can
        leave this as a no-op.
        """

    @abstractmethod
    def on_bar(self, bar: dict, position: dict) -> SignalResult:
        """Evaluate one bar and return a trading signal.

        Called by the backtest engine for each bar in sequence. The strategy
        examines the bar's OHLCV + indicator columns and the current position
        state, then returns buy/sell/hold.

        Args:
            bar: Dict with OHLCV columns plus any indicator columns.
                Keys include: open, high, low, close, volume, plus
                indicator columns like sma_20, rsi_14, proxy_ibs, etc.
            position: Dict describing current position state:
                - size: int (0 when flat)
                - direction: str ("long", "short", or "")
                - entry_price: float
                - entry_date: str
                - stop_price: float
                - target_price: float
                - bars_held: int

        Returns:
            SignalResult with action ("buy"|"sell"|"hold"), direction,
            and optional stop/target/confidence.
        """
        ...
