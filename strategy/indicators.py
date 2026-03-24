import pandas as pd
import pandas_ta as ta
from config import settings


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    Calculate all technical indicators used by the strategy.
    Adds columns to the DataFrame in place and returns it.

    Indicators:
        ema_fast  — EMA 20
        ema_slow  — EMA 50
        adx       — Average Directional Index (trend strength)
        atr       — Average True Range (volatility / stop sizing)
        rsi       — RSI 14 (overbought/oversold filter)
    """
    df = df.copy()

    # Trend indicators
    df["ema_fast"] = ta.ema(df["close"], length=settings.EMA_FAST)
    df["ema_slow"] = ta.ema(df["close"], length=settings.EMA_SLOW)

    # ADX — measures trend strength regardless of direction
    adx = ta.adx(df["high"], df["low"], df["close"], length=settings.ADX_PERIOD)
    df["adx"] = adx[f"ADX_{settings.ADX_PERIOD}"]

    # ATR — used for stop loss and take profit sizing
    df["atr"] = ta.atr(df["high"], df["low"], df["close"], length=settings.ATR_PERIOD)

    # RSI — used as an additional entry filter
    df["rsi"] = ta.rsi(df["close"], length=14)

    # Drop rows where indicators haven't warmed up yet
    df.dropna(inplace=True)

    return df
