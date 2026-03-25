"""
RSI(2) Daily Mean Reversion — US Stocks / ETFs
Timeframe: Daily candles
Primary instruments: SPY, QQQ, IWM (broad market ETFs)
Broker: Alpaca

─── ACADEMIC PEDIGREE ────────────────────────────────────────────────────────

Larry Connors & Cesar Alvarez, "Short-Term Trading Strategies That Work" (2009).
Backtested 1995–2008 on S&P 500 universe: 75% win rate, 2.3 profit factor.
Subsequently validated by multiple independent researchers on post-publication data.

Core insight: RSI(2) is a short-term mean-reversion oscillator. When daily RSI(2)
drops below 10, the stock is severely short-term oversold and has high probability
of mean-reverting UP within 1–5 days. Not a trend strategy — a rubber-band strategy.

Works because:
    - Short-term selloffs in uptrending stocks attract institutional buyers
    - RSI(2) < 10 occurs after 2-3 strong down days — short-term capitulation
    - Long-term uptrend filter (price > 200-day MA) ensures we buy dips, not disasters

─── SIGNAL LOGIC ─────────────────────────────────────────────────────────────

LONG ENTRY (all required):
    1. Close > SMA(200) — long-term uptrend (institutional bias is long)
    2. Close < SMA(5)   — short-term pullback (below 5-day MA)
    3. RSI(2) < RSI2_ENTRY_THRESHOLD (default 10) — short-term oversold
    4. VIX < 40         — not in extreme fear (optional regime filter)

EXIT (first of):
    1. Close > SMA(5) AND RSI(2) > RSI2_EXIT_THRESHOLD (default 65) — mean reversion complete
    2. RSI2_MAX_BARS days held (default 5) — time stop

STOP LOSS:
    Below entry_price × (1 - RSI2_HARD_STOP) — hard percent stop (default 2%)
    This is NOT the primary exit — the mean-reversion signal is the primary exit.
    The hard stop protects against gap-down disasters.

NO SHORTS: RSI(2) short signals (RSI > 90, price < SMA5) are skipped.
    - Short-selling requires locate fees, uptick rule risk, unlimited loss potential
    - The long-side edge is stronger and cleaner
    - Long-only also avoids fighting institutional buyers on dip-buying setups

─── KNOWN LIMITATIONS ────────────────────────────────────────────────────────
    - Works best in trending markets; underperforms in prolonged bear markets
    - Position sizing must be conservative — can experience multiple false signals
      in a row during choppy conditions
    - Alpha has decayed somewhat since 2009 publication but remains viable
      (post-publication WR ~65-68% vs original 75% — still positive expectancy)
    - Do NOT use on individual stocks with < $1B market cap (gap risk too high)
"""

import logging

import numpy as np
import pandas as pd
import ta

from config import settings

logger = logging.getLogger(__name__)


# ─── Settings (with defaults; override in config/settings.py) ─────────────────
RSI2_PERIOD          = getattr(settings, "RSI2_PERIOD",          2)
RSI2_ENTRY_THRESHOLD = getattr(settings, "RSI2_ENTRY_THRESHOLD", 10.0)  # oversold gate
RSI2_EXIT_THRESHOLD  = getattr(settings, "RSI2_EXIT_THRESHOLD",  65.0)  # exit when recovered
RSI2_SMA_LONG        = getattr(settings, "RSI2_SMA_LONG",        200)   # trend filter
RSI2_SMA_SHORT       = getattr(settings, "RSI2_SMA_SHORT",       5)     # pullback filter
RSI2_MAX_BARS        = getattr(settings, "RSI2_MAX_BARS",         5)     # time stop (days)
RSI2_HARD_STOP_PCT   = getattr(settings, "RSI2_HARD_STOP_PCT",   0.02)  # 2% hard stop
RSI2_VIX_MAX         = getattr(settings, "RSI2_VIX_MAX",         40.0)  # skip if VIX > this


def prepare_rsi2(df: pd.DataFrame) -> pd.DataFrame:
    """
    Prepare daily OHLCV data for RSI(2) Mean Reversion strategy.

    Args:
        df : Daily OHLCV DataFrame. Must have columns: open, high, low, close, volume.
             Index should be DatetimeIndex.

    Returns:
        DataFrame with added columns:
            sma200      — 200-day simple moving average
            sma5        — 5-day simple moving average
            rsi2        — RSI with period=2
            uptrend     — bool: close > sma200
            pullback    — bool: close < sma5
            signal      — 1=long entry, -2=exit signal, 0=hold
            stop_loss   — hard stop price (entry × (1 - RSI2_HARD_STOP_PCT))
            take_profit — set to 0.0 (exit driven by RSI2, not fixed TP)
    """
    df = df.copy()

    # ── Trend and momentum indicators ──────────────────────────────────────────
    df["sma200"] = df["close"].rolling(RSI2_SMA_LONG).mean()
    df["sma5"]   = df["close"].rolling(RSI2_SMA_SHORT).mean()

    rsi_indicator = ta.momentum.RSIIndicator(df["close"], window=RSI2_PERIOD)
    df["rsi2"] = rsi_indicator.rsi()

    # ── Entry conditions ────────────────────────────────────────────────────────
    df["uptrend"]  = df["close"] > df["sma200"]
    df["pullback"] = df["close"] < df["sma5"]
    df["oversold"] = df["rsi2"] < RSI2_ENTRY_THRESHOLD

    # ── Signals ─────────────────────────────────────────────────────────────────
    df["signal"]      = 0
    df["stop_loss"]   = np.nan
    df["take_profit"] = 0.0  # RSI(2) uses signal-based exit, not fixed TP

    # LONG entry: all 3 conditions met
    entry_mask = df["uptrend"] & df["pullback"] & df["oversold"]
    df.loc[entry_mask, "signal"] = 1
    df.loc[entry_mask, "stop_loss"] = df.loc[entry_mask, "close"] * (1 - RSI2_HARD_STOP_PCT)

    # EXIT signal: RSI(2) has recovered AND price above 5-day MA
    exit_mask = (df["rsi2"] > RSI2_EXIT_THRESHOLD) & (df["close"] > df["sma5"])
    df.loc[exit_mask & (df["signal"] == 0), "signal"] = -2  # -2 = exit signal (not short entry)

    return df


def get_latest_rsi2_signal(df: pd.DataFrame) -> dict:
    """
    Return the most recent trade signal from a prepared RSI(2) DataFrame.

    Args:
        df : DataFrame returned by prepare_rsi2()

    Returns:
        dict with keys:
            signal      : 1 = new long entry, -2 = exit open position, 0 = hold
            close       : last close price
            stop_loss   : stop price (or None if no entry)
            take_profit : 0.0 (use RSI2 exit signal instead)
            rsi2        : current RSI(2) value
            sma200      : current 200-day SMA
            sma5        : current 5-day SMA
            uptrend     : bool
            bars_held   : None (tracked externally)
            reason      : human-readable reason string
    """
    last = df.dropna(subset=["rsi2", "sma200", "sma5"]).iloc[-1]

    signal = int(last.get("signal", 0))

    if signal == 1:
        reason = (
            f"RSI(2)={last['rsi2']:.1f} < {RSI2_ENTRY_THRESHOLD} | "
            f"close={last['close']:.2f} < SMA5={last['sma5']:.2f} | "
            f"above SMA200={last['sma200']:.2f}"
        )
    elif signal == -2:
        reason = (
            f"RSI(2)={last['rsi2']:.1f} > {RSI2_EXIT_THRESHOLD} — mean reversion complete"
        )
    else:
        parts = []
        if not last.get("uptrend"):
            parts.append(f"below SMA200={last['sma200']:.2f}")
        if not last.get("pullback"):
            parts.append(f"above SMA5={last['sma5']:.2f} (no pullback)")
        if last["rsi2"] >= RSI2_ENTRY_THRESHOLD:
            parts.append(f"RSI(2)={last['rsi2']:.1f} not oversold")
        reason = "No entry: " + (" | ".join(parts) if parts else "conditions not met")

    return {
        "signal":      signal,
        "close":       float(last["close"]),
        "stop_loss":   float(last["stop_loss"]) if signal == 1 else None,
        "take_profit": 0.0,
        "rsi2":        float(last["rsi2"]),
        "sma200":      float(last["sma200"]),
        "sma5":        float(last["sma5"]),
        "uptrend":     bool(last.get("uptrend", False)),
        "bars_held":   None,
        "reason":      reason,
    }
