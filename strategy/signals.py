import pandas as pd
from config import settings


def generate_signals(df: pd.DataFrame) -> pd.DataFrame:
    """
    Generate trade signals based on EMA crossover + ADX trend filter.

    Signal logic:
        LONG  — EMA20 crosses above EMA50 AND ADX > threshold (strong uptrend)
        SHORT — EMA20 crosses below EMA50 AND ADX > threshold (strong downtrend)
        FLAT  — No crossover or ADX too weak (choppy/sideways market)

    Adds columns:
        signal      : 1 = long, -1 = short, 0 = flat
        stop_loss   : price level for stop loss (ATR-based)
        take_profit : price level for take profit (ATR-based)
    """
    df = df.copy()

    # Detect EMA crossover
    df["ema_above"] = df["ema_fast"] > df["ema_slow"]
    prev_ema_above = df["ema_above"].shift(1, fill_value=False).astype(bool)
    df["cross_up"] = df["ema_above"] & ~prev_ema_above
    df["cross_down"] = ~df["ema_above"] & prev_ema_above

    # Trend strength filter
    df["trend_strong"] = df["adx"] > settings.ADX_THRESHOLD

    # Generate raw signal
    df["signal"] = 0
    df.loc[df["cross_up"] & df["trend_strong"], "signal"] = 1    # Long
    df.loc[df["cross_down"] & df["trend_strong"], "signal"] = -1  # Short

    # ATR-based stop loss and take profit
    df["stop_loss"] = df.apply(_calc_stop, axis=1)
    df["take_profit"] = df.apply(_calc_tp, axis=1)

    return df


def _calc_stop(row) -> float:
    """Calculate stop loss price based on signal direction and ATR."""
    if row["signal"] == 1:
        return round(row["close"] - settings.ATR_SL_MULTIPLIER * row["atr"], 2)
    elif row["signal"] == -1:
        return round(row["close"] + settings.ATR_SL_MULTIPLIER * row["atr"], 2)
    return 0.0


def _calc_tp(row) -> float:
    """Calculate take profit price based on signal direction and ATR."""
    if row["signal"] == 1:
        return round(row["close"] + settings.ATR_TP_MULTIPLIER * row["atr"], 2)
    elif row["signal"] == -1:
        return round(row["close"] - settings.ATR_TP_MULTIPLIER * row["atr"], 2)
    return 0.0


def get_latest_signal(df: pd.DataFrame) -> dict:
    """
    Return the signal from the most recently closed candle.
    This is what the live bot checks each candle close.
    """
    last = df.iloc[-1]
    return {
        "signal": int(last["signal"]),
        "close": float(last["close"]),
        "atr": float(last["atr"]),
        "adx": float(last["adx"]),
        "ema_fast": float(last["ema_fast"]),
        "ema_slow": float(last["ema_slow"]),
        "stop_loss": float(last["stop_loss"]),
        "take_profit": float(last["take_profit"]),
    }
