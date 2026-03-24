import pandas as pd
import ta
from config import settings


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    Calculate all technical indicators used by the strategy.
    Adds columns to the DataFrame and returns it.

    Indicators:
        ema_fast  — EMA 20
        ema_slow  — EMA 50
        adx       — Average Directional Index (trend strength)
        atr       — Average True Range (volatility / stop sizing)
        rsi       — RSI 14 (overbought/oversold filter)
    """
    df = df.copy()

    # Trend indicators
    df["ema_fast"] = ta.trend.ema_indicator(df["close"], window=settings.EMA_FAST)
    df["ema_slow"] = ta.trend.ema_indicator(df["close"], window=settings.EMA_SLOW)

    # ADX — measures trend strength regardless of direction
    adx_indicator = ta.trend.ADXIndicator(df["high"], df["low"], df["close"], window=settings.ADX_PERIOD)
    df["adx"] = adx_indicator.adx()

    # ATR — used for stop loss and take profit sizing
    atr_indicator = ta.volatility.AverageTrueRange(df["high"], df["low"], df["close"], window=settings.ATR_PERIOD)
    df["atr"] = atr_indicator.average_true_range()

    # RSI — additional entry filter
    df["rsi"] = ta.momentum.RSIIndicator(df["close"], window=14).rsi()

    # Drop rows where indicators haven't warmed up yet
    df.dropna(inplace=True)

    return df
