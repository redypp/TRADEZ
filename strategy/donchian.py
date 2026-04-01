import pandas as pd
import numpy as np
import ta
import logging
from config import settings

logger = logging.getLogger(__name__)


def prepare_donchian(df: pd.DataFrame, long_only: bool = False) -> pd.DataFrame:
    """
    Prepare daily OHLCV data for Donchian Channel Breakout strategy.

    Based on the Turtle Trading system:
        - Enter LONG  when close breaks above 20-day high
        - Enter SHORT when close breaks below 20-day low
        - Exit  LONG  when close drops below 10-day low  (trailing stop)
        - Exit  SHORT when close rises above 10-day high (trailing stop)
        - Hard stop: 2x ATR from entry

    Adds columns:
        dc_upper     — 20-day highest high (entry channel)
        dc_lower     — 20-day lowest low  (entry channel)
        dc_exit_high — 10-day highest high (exit channel)
        dc_exit_low  — 10-day lowest low  (exit channel)
        atr          — ATR(20) for stop sizing
        signal       — 1=long, -1=short, 0=flat
        stop_loss    — ATR-based hard stop
        take_profit  — set to 0 (Donchian uses trailing exit, not fixed TP)
    """
    df = df.copy()

    n_entry = settings.DONCHIAN_ENTRY_PERIOD
    n_exit  = settings.DONCHIAN_EXIT_PERIOD

    # Entry channels (shifted by 1 to avoid lookahead bias)
    df["dc_upper"] = df["high"].shift(1).rolling(n_entry).max()
    df["dc_lower"] = df["low"].shift(1).rolling(n_entry).min()

    # Exit channels (trailing stop)
    df["dc_exit_high"] = df["high"].shift(1).rolling(n_exit).max()
    df["dc_exit_low"]  = df["low"].shift(1).rolling(n_exit).min()

    # ATR for hard stop
    atr_ind = ta.volatility.AverageTrueRange(
        df["high"], df["low"], df["close"],
        window=settings.DONCHIAN_ATR_PERIOD
    )
    df["atr"] = atr_ind.average_true_range()

    # Signals
    df["signal"] = 0
    df.loc[df["close"] > df["dc_upper"], "signal"] = 1   # Breakout above 20-day high
    if not long_only:
        df.loc[df["close"] < df["dc_lower"], "signal"] = -1  # Breakdown below 20-day low

    # Hard stop loss (ATR-based)
    df["stop_loss"] = np.where(
        df["signal"] == 1,
        df["close"] - settings.DONCHIAN_ATR_SL * df["atr"],
        np.where(
            df["signal"] == -1,
            df["close"] + settings.DONCHIAN_ATR_SL * df["atr"],
            np.nan
        )
    )

    # No fixed TP — Donchian uses trailing channel exit
    df["take_profit"] = 0.0

    df.dropna(subset=["dc_upper", "dc_lower", "atr"], inplace=True)
    logger.info(f"Donchian signals generated — total entry signals: {(df['signal'] != 0).sum()}")
    return df


def get_latest_donchian_signal(df: pd.DataFrame) -> dict:
    """Return the latest Donchian signal."""
    last = df.iloc[-1]
    return {
        "signal": int(last["signal"]),
        "close": float(last["close"]),
        "dc_upper": float(last["dc_upper"]),
        "dc_lower": float(last["dc_lower"]),
        "dc_exit_high": float(last["dc_exit_high"]),
        "dc_exit_low": float(last["dc_exit_low"]),
        "atr": float(last["atr"]),
        "stop_loss": float(last["stop_loss"]) if pd.notna(last["stop_loss"]) else None,
    }


# ── Strategy class (self-registers with orchestrator) ─────────────────────────

from strategy.base import AbstractStrategy
from strategy.registry import register


@register
class DonchianStrategy(AbstractStrategy):
    """
    Donchian Channel Breakout — metals and commodities (daily candles).
    Turtle Trading system: enter on 20-day high/low, trail on 10-day channel.
    Runs once per day (checked in the 9 AM ET session window).
    """

    name              = "DONCHIAN"
    timeframe_minutes = 1440   # daily
    priority          = 30
    strategy_type     = "daily"  # holds 5-60 days — overnight gap risk

    def __init__(self):
        from config import settings as _s
        self.symbols = _s.STRATEGY_SYMBOLS.get("DONCHIAN", ["MGC", "SIL", "MNQ"])

    def is_eligible(self, symbol: str, regime: str, session_hour: int, fundamentals: dict) -> bool:
        if regime == "NO_TRADE":
            return False
        # Daily strategy — only evaluate once, at session open
        return 9 <= session_hour < 10

    def prepare(self, df, long_only: bool = False, **kwargs):
        return prepare_donchian(df, long_only=long_only)

    def get_signal(self, df, **kwargs) -> dict:
        sig = get_latest_donchian_signal(df)
        # Ensure take_profit key present (Donchian uses trailing exit, no fixed TP)
        sig.setdefault("take_profit", 0.0)
        return sig
