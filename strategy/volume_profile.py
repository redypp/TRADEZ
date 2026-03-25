"""
strategy/volume_profile.py

Volume Profile calculation for institutional level identification.

Computes Point of Control (POC), Value Area High/Low (VAH/VAL), and the
full price-volume distribution from OHLCV bar data.

Academic grounding:
    Peter Steidlmayer / CBOT (1985): Market Profile / Volume Profile framework.
    Institutionally validated by its origins and widespread use by floor traders,
    institutional VWAP desks, and CME Group itself in their market commentary.

    The 70% Value Area is grounded in statistical theory (normal distribution ±1 SD),
    not an empirically backtested "price returns to VA X% of the time" claim.
    The "80% return" figure cited in retail content is [RETAIL CLAIM - UNVERIFIED].

Usage:
    from strategy.volume_profile import calculate_volume_profile, add_session_vp

    vp = calculate_volume_profile(df)
    print(vp['poc'], vp['vah'], vp['val'])

    # Add prior-session profile to intraday dataframe
    df = add_session_vp(df)
    # Now df has: prior_poc, prior_vah, prior_val columns
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# ─── Constants ────────────────────────────────────────────────────────────────

DEFAULT_N_BINS    = 50    # Price bins for volume profile
VALUE_AREA_PCT    = 0.70  # Volume percentage for Value Area (70%)


# ─── Core Calculation ─────────────────────────────────────────────────────────

def calculate_volume_profile(
    df:       pd.DataFrame,
    n_bins:   int   = DEFAULT_N_BINS,
    va_pct:   float = VALUE_AREA_PCT,
) -> dict:
    """
    Calculate Volume Profile from OHLCV data.

    Distributes each bar's volume uniformly across its price range (from low to high),
    then aggregates into price bins to find the distribution.

    Args:
        df     : OHLCV DataFrame. Must have: high, low, close, volume columns.
        n_bins : Number of price buckets (more bins = finer resolution).
        va_pct : Value Area percentage (default 0.70 = 70% of volume).

    Returns:
        dict:
            poc      : Point of Control price (max volume level)
            vah      : Value Area High
            val      : Value Area Low
            profile  : dict {price_level → volume}  (sorted by price)
            total_vol: total volume in the period
    """
    if df.empty or "volume" not in df.columns:
        return {"poc": None, "vah": None, "val": None, "profile": {}, "total_vol": 0}

    df = df.dropna(subset=["high", "low", "close", "volume"])
    if df.empty:
        return {"poc": None, "vah": None, "val": None, "profile": {}, "total_vol": 0}

    price_min = float(df["low"].min())
    price_max = float(df["high"].max())

    if price_max <= price_min:
        return {"poc": None, "vah": None, "val": None, "profile": {}, "total_vol": 0}

    bins = np.linspace(price_min, price_max, n_bins + 1)
    bin_mids = (bins[:-1] + bins[1:]) / 2
    volume_at_price = np.zeros(n_bins)

    for _, row in df.iterrows():
        low  = float(row["low"])
        high = float(row["high"])
        vol  = float(row["volume"])

        if vol <= 0:
            continue

        lo_idx = int(np.searchsorted(bins, low,  side="left"))
        hi_idx = int(np.searchsorted(bins, high, side="right"))
        lo_idx = max(0, min(lo_idx, n_bins - 1))
        hi_idx = max(0, min(hi_idx, n_bins - 1))

        span = hi_idx - lo_idx
        if span > 1:
            volume_at_price[lo_idx:hi_idx] += vol / span
        else:
            volume_at_price[lo_idx] += vol

    # ── POC ───────────────────────────────────────────────────────────────────
    poc_idx = int(np.argmax(volume_at_price))
    poc = float(bin_mids[poc_idx])

    # ── Value Area — expand from POC until 70% of volume is captured ──────────
    total_vol = float(volume_at_price.sum())
    target    = total_vol * va_pct

    accumulated = float(volume_at_price[poc_idx])
    va_indices  = {poc_idx}
    lo_ptr      = poc_idx - 1
    hi_ptr      = poc_idx + 1

    while accumulated < target:
        add_lo = volume_at_price[lo_ptr] if lo_ptr >= 0 else 0.0
        add_hi = volume_at_price[hi_ptr] if hi_ptr < n_bins else 0.0

        if add_lo == 0 and add_hi == 0:
            break  # hit the edges

        # Expand in the direction with more volume
        if add_hi >= add_lo:
            va_indices.add(hi_ptr)
            accumulated += add_hi
            hi_ptr += 1
        else:
            va_indices.add(lo_ptr)
            accumulated += add_lo
            lo_ptr -= 1

    va_prices = [bin_mids[i] for i in va_indices]
    vah = float(max(va_prices))
    val = float(min(va_prices))

    profile_sorted = {
        round(float(price), 4): round(float(vol), 2)
        for price, vol in sorted(zip(bin_mids.tolist(), volume_at_price.tolist()))
    }

    return {
        "poc":       round(poc, 4),
        "vah":       round(vah, 4),
        "val":       round(val, 4),
        "profile":   profile_sorted,
        "total_vol": round(total_vol, 2),
    }


# ─── Session-Level Profile Addition ───────────────────────────────────────────

def add_session_vp(
    df:       pd.DataFrame,
    tz:       str = "America/New_York",
    session_start_hour: int = 9,
    session_start_min:  int = 30,
) -> pd.DataFrame:
    """
    Add prior-session Volume Profile levels to an intraday DataFrame.

    For each bar, adds the POC, VAH, and VAL from the PREVIOUS session.
    This avoids lookahead bias — you only know prior session levels.

    Args:
        df     : Intraday OHLCV DataFrame with DatetimeIndex
        tz     : Timezone for session detection (default: US/Eastern)
        session_start_hour/min: RTH open time (9:30 AM ET for equities/futures)

    Returns:
        df with added columns:
            prior_poc, prior_vah, prior_val
    """
    df = df.copy()

    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC").tz_convert(tz)
    else:
        df.index = df.index.tz_convert(tz)

    df["_date"] = df.index.date

    # Compute volume profile per session
    session_profiles = {}
    for date, session_df in df.groupby("_date"):
        # Only use bars at/after RTH open
        rth_mask = (
            (session_df.index.hour > session_start_hour) |
            ((session_df.index.hour == session_start_hour) & (session_df.index.minute >= session_start_min))
        )
        rth_df = session_df[rth_mask]
        if len(rth_df) >= 3:
            vp = calculate_volume_profile(rth_df)
            session_profiles[date] = vp

    sorted_dates = sorted(session_profiles.keys())

    # Map PRIOR session levels to each row
    df["prior_poc"] = np.nan
    df["prior_vah"] = np.nan
    df["prior_val"] = np.nan

    for i, date in enumerate(sorted_dates[1:], 1):  # start from second session
        prior_date = sorted_dates[i - 1]
        prior_vp   = session_profiles[prior_date]

        mask = df["_date"] == date
        if prior_vp["poc"] is not None:
            df.loc[mask, "prior_poc"] = prior_vp["poc"]
            df.loc[mask, "prior_vah"] = prior_vp["vah"]
            df.loc[mask, "prior_val"] = prior_vp["val"]

    df = df.drop(columns=["_date"])
    return df


def add_rolling_vp(
    df:            pd.DataFrame,
    lookback_bars: int = 20,
) -> pd.DataFrame:
    """
    Add rolling Volume Profile levels to a daily DataFrame.

    For each bar, computes POC/VAH/VAL from the prior N bars (rolling window).
    Useful for daily strategies like Donchian to see institutional fair value.

    Args:
        df            : Daily OHLCV DataFrame
        lookback_bars : Rolling window in bars (default 20 = ~1 month of trading days)

    Returns:
        df with added columns: rolling_poc, rolling_vah, rolling_val
    """
    df = df.copy()
    pocs, vahs, vals = [], [], []

    for i in range(len(df)):
        start = max(0, i - lookback_bars)
        window = df.iloc[start:i]  # excludes current bar (no lookahead)
        if len(window) >= 3:
            vp = calculate_volume_profile(window)
            pocs.append(vp["poc"])
            vahs.append(vp["vah"])
            vals.append(vp["val"])
        else:
            pocs.append(np.nan)
            vahs.append(np.nan)
            vals.append(np.nan)

    df["rolling_poc"] = pocs
    df["rolling_vah"] = vahs
    df["rolling_val"] = vals
    return df


def vpoc_trend(
    df:       pd.DataFrame,
    n_bars:   int = 5,
) -> str:
    """
    Detect VPOC migration trend over the last N sessions.

    Args:
        df     : DataFrame with 'prior_poc' column (from add_session_vp)
        n_bars : Lookback for trend detection

    Returns:
        "RISING" / "FALLING" / "NEUTRAL"
    """
    if "prior_poc" not in df.columns:
        return "NEUTRAL"

    recent_pocs = df["prior_poc"].dropna().tail(n_bars).tolist()
    if len(recent_pocs) < 3:
        return "NEUTRAL"

    # Linear regression slope
    x = np.arange(len(recent_pocs))
    y = np.array(recent_pocs)
    slope = np.polyfit(x, y, 1)[0]

    # Threshold: slope > 0.1 point/session = rising
    if slope > 0.1:
        return "RISING"
    if slope < -0.1:
        return "FALLING"
    return "NEUTRAL"
