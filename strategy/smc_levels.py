"""
strategy/smc_levels.py

Smart Money Concept level detection — EQH/EQL and FVG zones.

These functions add new columns to a prepared OHLCV DataFrame so that
break_retest.py can include SMC levels in its priority scan.

Academic backing:
  - Equal Highs/Lows: ResearchGate 2024 (EUR/USD PDH/PDL sweeps, ~14.3% of days,
    statistically validated reversal tendency); Osler 2005 (stop-loss cascades at
    clustered levels). Most academically grounded SMC component.
  - FVG: Edgeful.com futures data — >60% of FVGs NEVER fill. Use as S/R zones,
    not fill targets.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import logging

logger = logging.getLogger(__name__)


# ─── Equal Highs / Equal Lows ─────────────────────────────────────────────────

def add_equal_highs_lows(
    df: pd.DataFrame,
    swing_lookback: int  = 10,
    cluster_lookback: int = 50,
    tolerance_atr: float  = 0.15,
) -> pd.DataFrame:
    """
    Detect Equal Highs (EQH) and Equal Lows (EQL) as liquidity pool levels.

    EQH = two or more recent swing highs within `tolerance_atr × ATR` of each
          other → dense stop cluster above (buy-side liquidity)
    EQL = two or more recent swing lows within `tolerance_atr × ATR` of each
          other → sell-side liquidity

    Adds columns:
        eqh  — price of the most recent active equal high (NaN if none)
        eql  — price of the most recent active equal low  (NaN if none)

    Args:
        swing_lookback:   bars on each side to define a local high/low
        cluster_lookback: look back this many bars for swing point clusters
        tolerance_atr:    max distance (as ATR multiple) between swing points
                          to qualify as "equal"
    """
    df = df.copy()
    df["eqh"] = np.nan
    df["eql"] = np.nan

    if "atr" not in df.columns or len(df) < swing_lookback * 2 + cluster_lookback:
        return df

    highs = df["high"].values
    lows  = df["low"].values
    atrs  = df["atr"].values
    n     = len(df)
    sl    = swing_lookback

    for i in range(sl + cluster_lookback, n):
        atr_val = atrs[i]
        if atr_val <= 0:
            continue
        tol = tolerance_atr * atr_val

        # Collect swing highs in the lookback window
        swing_highs = []
        swing_lows  = []
        start = max(sl, i - cluster_lookback)
        for j in range(start, i - sl + 1):
            # Local high: highest within ±swing_lookback bars
            window_h = highs[max(0, j - sl): j + sl + 1]
            if highs[j] == window_h.max():
                swing_highs.append(highs[j])
            # Local low: lowest within ±swing_lookback bars
            window_l = lows[max(0, j - sl): j + sl + 1]
            if lows[j] == window_l.min():
                swing_lows.append(lows[j])

        # Check for equal highs (2+ swing highs within tolerance)
        if len(swing_highs) >= 2:
            for k, sh in enumerate(swing_highs):
                cluster = [x for x in swing_highs if abs(x - sh) <= tol]
                if len(cluster) >= 2:
                    # Use the average of the cluster as the level
                    df.iloc[i, df.columns.get_loc("eqh")] = float(np.mean(cluster))
                    break

        # Check for equal lows
        if len(swing_lows) >= 2:
            for k, sl_val in enumerate(swing_lows):
                cluster = [x for x in swing_lows if abs(x - sl_val) <= tol]
                if len(cluster) >= 2:
                    df.iloc[i, df.columns.get_loc("eql")] = float(np.mean(cluster))
                    break

    return df


# ─── Fair Value Gaps (FVGs) ───────────────────────────────────────────────────

def add_fvg_levels(df: pd.DataFrame, min_gap_atr: float = 0.1) -> pd.DataFrame:
    """
    Detect the most recent active Fair Value Gap (FVG) and expose its edges
    as potential BRT levels.

    FVG definition (three-candle pattern):
        Bullish:  candle[i-1].high < candle[i+1].low  → price void above candle[i-1]
        Bearish:  candle[i-1].low  > candle[i+1].high → price void below candle[i-1]

    IMPORTANT: >60% of FVGs are NEVER filled (Edgeful.com, YM futures data).
    Use FVG boundaries as support/resistance zones, NOT as fill targets.

    Adds columns:
        fvg_bull_low  — low edge of the most recent bullish FVG (NaN if none active)
        fvg_bull_high — high edge of the most recent bullish FVG
        fvg_bear_low  — low edge of the most recent bearish FVG
        fvg_bear_high — high edge of the most recent bearish FVG

    An FVG is "active" until price closes through its midpoint
    (conservative invalidation — use 0.5 fill as the mitigated signal).

    Args:
        min_gap_atr: minimum gap size (as ATR multiple) to count as a meaningful FVG
    """
    df = df.copy()
    df["fvg_bull_low"]  = np.nan
    df["fvg_bull_high"] = np.nan
    df["fvg_bear_low"]  = np.nan
    df["fvg_bear_high"] = np.nan

    if "atr" not in df.columns or len(df) < 3:
        return df

    highs  = df["high"].values
    lows   = df["low"].values
    closes = df["close"].values
    atrs   = df["atr"].values
    n      = len(df)

    # Track the most recent active FVGs (rolling, mitigated when price closes through mid)
    active_bull: tuple | None = None   # (low, high)
    active_bear: tuple | None = None   # (low, high)

    for i in range(2, n):
        atr_val = atrs[i]
        close_i = closes[i]

        # Check mitigation of existing FVGs by close through midpoint
        if active_bull is not None:
            mid = (active_bull[0] + active_bull[1]) / 2
            if close_i < mid:                # price closed below bull FVG midpoint
                active_bull = None

        if active_bear is not None:
            mid = (active_bear[0] + active_bear[1]) / 2
            if close_i > mid:                # price closed above bear FVG midpoint
                active_bear = None

        # Detect new FVG on candle i (using i-2, i-1, i pattern)
        if atr_val > 0:
            # Bullish FVG: prev_high < next_low (gap between candle[i-2] and candle[i])
            bull_gap = lows[i] - highs[i - 2]
            if bull_gap > min_gap_atr * atr_val:
                active_bull = (highs[i - 2], lows[i])

            # Bearish FVG: prev_low > next_high
            bear_gap = lows[i - 2] - highs[i]
            if bear_gap > min_gap_atr * atr_val:
                active_bear = (highs[i], lows[i - 2])

        # Write the currently active FVGs to this bar's row
        if active_bull is not None:
            df.iloc[i, df.columns.get_loc("fvg_bull_low")]  = active_bull[0]
            df.iloc[i, df.columns.get_loc("fvg_bull_high")] = active_bull[1]

        if active_bear is not None:
            df.iloc[i, df.columns.get_loc("fvg_bear_low")]  = active_bear[0]
            df.iloc[i, df.columns.get_loc("fvg_bear_high")] = active_bear[1]

    return df
