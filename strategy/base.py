"""
strategy/base.py

Abstract base class for all TRADEZ strategies.

Each strategy must:
    1. Set class attributes: name, symbols, timeframe_minutes, priority
    2. Implement is_eligible() — declares when this strategy should run
    3. Implement prepare()     — enriches raw OHLCV data with indicators
    4. Implement get_signal()  — returns the latest signal dict

Signal dict contract (minimum required keys):
    signal      : int   — 1 (long), -1 (short), 0 (flat)
    close       : float — current close price
    stop_loss   : float — stop loss price (or None if signal=0)
    take_profit : float — take profit price (or None if signal=0)

The orchestrator automatically stamps:
    strategy : str   — strategy name
    symbol   : str   — trading symbol
"""

from abc import ABC, abstractmethod
import pandas as pd


class AbstractStrategy(ABC):
    """
    Base class for all trading strategies.

    Class attributes (override on each subclass):
        name              : str   — unique strategy identifier (e.g. "BRT")
        symbols           : list  — symbols this strategy can trade (e.g. ["MES"])
                                    Overridden at runtime from STRATEGY_SYMBOLS in settings.
        timeframe_minutes : int   — candle size in minutes (1440 = daily)
        priority          : int   — conflict-resolution priority; lower number wins
    """

    name: str = ""
    symbols: list = []
    timeframe_minutes: int = 15
    priority: int = 50

    @abstractmethod
    def is_eligible(
        self,
        symbol: str,
        regime: str,
        session_hour: int,
        fundamentals: dict,
    ) -> bool:
        """
        Return True if this strategy should evaluate signals right now.

        The orchestrator calls this before fetching any data, so it is cheap.
        Gate on regime, session hour, VIX, day-of-week, or any other condition
        that can be evaluated without a full data fetch.

        Args:
            symbol       : Symbol being evaluated (e.g. "MES")
            regime       : Current market regime (e.g. "TRENDING", "HIGH_VOL", "NO_TRADE")
            session_hour : Current ET hour (0-23)
            fundamentals : Live fundamentals dict — vix, yield_10y, dxy, spy_vol_ratio
        """
        ...

    @abstractmethod
    def prepare(self, df: pd.DataFrame, **kwargs) -> pd.DataFrame:
        """
        Add indicators and signal columns to a raw OHLCV DataFrame.

        Args:
            df     : Raw OHLCV DataFrame from data.fetcher (not modified in-place)
            kwargs : Strategy-specific context (regime_params, long_only, etc.)

        Returns:
            Enriched DataFrame with at minimum: signal, stop_loss, take_profit columns.
        """
        ...

    @abstractmethod
    def get_signal(self, df: pd.DataFrame, **kwargs) -> dict:
        """
        Extract the latest signal from a prepared DataFrame.

        Returns a dict with at minimum:
            signal      : int   — 1 (long), -1 (short), 0 (flat)
            close       : float — current close price
            stop_loss   : float or None
            take_profit : float or None
        """
        ...

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}"
            f"(name={self.name!r}, symbols={self.symbols}, "
            f"tf={self.timeframe_minutes}m, priority={self.priority})"
        )
