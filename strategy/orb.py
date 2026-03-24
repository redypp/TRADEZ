import pandas as pd
import numpy as np
import ta
import pytz
import logging
from config import settings

logger = logging.getLogger(__name__)

EASTERN = pytz.timezone("America/New_York")


def prepare_orb(df: pd.DataFrame) -> pd.DataFrame:
    """
    Prepare hourly OHLCV data for Opening Range Breakout strategy.

    Opening Range = first 1h candle of the regular session (9:30 AM ET).

    Adds columns:
        or_high      — opening range high for the day
        or_low       — opening range low for the day
        or_size      — opening range size (high - low)
        atr          — ATR(14) for range quality filter
        date_et      — date in Eastern time
        hour_et      — hour in Eastern time
        signal       — 1=long, -1=short, 0=flat
        stop_loss    — stop loss price
        take_profit  — take profit price
        eod_exit     — True if this is the last tradeable candle of the day
    """
    df = df.copy()

    # Convert index to Eastern time
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC").tz_convert(EASTERN)
    else:
        df.index = df.index.tz_convert(EASTERN)

    df["date_et"] = df.index.normalize()
    df["hour_et"] = df.index.hour
    df["minute_et"] = df.index.minute

    # ATR for range quality filter
    atr_ind = ta.volatility.AverageTrueRange(df["high"], df["low"], df["close"], window=settings.ATR_PERIOD)
    df["atr"] = atr_ind.average_true_range()

    # Trend filter: 20-period SMA on the hourly close
    # Only take longs above SMA, only take shorts below SMA
    df["sma20"] = df["close"].rolling(20).mean()

    # Opening range candle = 9:00 AM ET (first regular session candle in yfinance hourly data)
    # yfinance aligns ES futures to whole hours; the 9:00 candle captures the 9:30 open
    or_mask = (df["hour_et"] == 9) & (df["minute_et"] == 0)
    or_candles = df[or_mask][["date_et", "high", "low"]].copy()
    or_candles.columns = ["date_et", "or_high", "or_low"]
    or_candles = or_candles.set_index("date_et")

    df = df.join(or_candles, on="date_et")
    df["or_size"] = df["or_high"] - df["or_low"]

    # Mark end-of-day candle — exit at 15:00 ET (last candle before close)
    df["eod_exit"] = (df["hour_et"] == 15) & (df["minute_et"] == 0)

    # Generate signals — only in entry window, after opening range
    df["signal"] = 0
    df["stop_loss"] = np.nan
    df["take_profit"] = np.nan

    in_entry_window = df["hour_et"].isin(settings.ORB_ENTRY_HOURS)
    has_or = df["or_high"].notna() & df["or_low"].notna()
    range_valid = (
        (df["or_size"] < df["atr"] * settings.ORB_MAX_RANGE_ATR) &
        (df["or_size"] > df["atr"] * settings.ORB_MIN_RANGE_ATR)
    )

    trend_up   = df["close"] > df["sma20"]
    trend_down = df["close"] < df["sma20"]

    long_cond  = in_entry_window & has_or & range_valid & (df["close"] > df["or_high"]) & trend_up
    short_cond = in_entry_window & has_or & range_valid & (df["close"] < df["or_low"])  & trend_down

    df.loc[long_cond, "signal"] = 1
    df.loc[short_cond, "signal"] = -1

    # Stop loss and take profit
    buf = df["or_size"] * settings.ORB_SL_BUFFER
    df.loc[long_cond, "stop_loss"] = df["or_low"] - buf
    df.loc[long_cond, "take_profit"] = df["close"] + df["or_size"] * settings.ORB_TP_MULTIPLIER

    df.loc[short_cond, "stop_loss"] = df["or_high"] + buf
    df.loc[short_cond, "take_profit"] = df["close"] - df["or_size"] * settings.ORB_TP_MULTIPLIER

    # Only take the FIRST signal per day (avoid re-entering same day)
    first_signal_idx = (
        df[df["signal"] != 0]
        .groupby("date_et")
        .head(1)
        .index
    )
    mask = df.index.isin(first_signal_idx)
    df.loc[~mask, "signal"] = 0
    df.loc[~mask, "stop_loss"] = np.nan
    df.loc[~mask, "take_profit"] = np.nan

    df.dropna(subset=["atr"], inplace=True)
    logger.info(f"ORB signals generated — total entry signals: {(df['signal'] != 0).sum()}")
    return df


def get_latest_orb_signal(df: pd.DataFrame) -> dict:
    """Return the latest ORB signal."""
    last = df.iloc[-1]
    return {
        "signal": int(last["signal"]),
        "close": float(last["close"]),
        "or_high": float(last["or_high"]) if pd.notna(last["or_high"]) else None,
        "or_low": float(last["or_low"]) if pd.notna(last["or_low"]) else None,
        "or_size": float(last["or_size"]) if pd.notna(last["or_size"]) else None,
        "atr": float(last["atr"]) if pd.notna(last["atr"]) else None,
        "stop_loss": float(last["stop_loss"]) if pd.notna(last["stop_loss"]) else None,
        "take_profit": float(last["take_profit"]) if pd.notna(last["take_profit"]) else None,
        "eod_exit": bool(last["eod_exit"]),
    }
