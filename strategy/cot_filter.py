"""
strategy/cot_filter.py

COT (Commitment of Traders) directional bias filter.

Provides a weekly macro directional bias for each instrument based on
CFTC Commitment of Traders data. Used as Layer 1 of the strategy stack —
sets the directional bias that higher-priority signals must confirm.

What it does:
    1. Downloads COT data from CFTC (once per week, cached locally)
    2. Calculates the COT Index for the relevant trader categories
    3. Returns a bias signal: LONG, SHORT, or NEUTRAL

Academic grounding:
    Zhang & Laws (2013): COT as precious metals predictor — profitable vs. naïve long,
    but Granger causality is weak. Use as bias filter, not timing tool.

    Chen & Maher (2013): S&P500 — positive correlation present but unstable across time.

    Academic consensus: COT is better as a weekly directional filter combined with
    other signals than as a standalone entry system.

COT Report types used:
    Gold (MGC/GC): CFTC Disaggregated Futures Only — Producer/Merchant category
    Silver (SIL/SI): Same as Gold
    MES/ES (S&P 500): TFF (Traders in Financial Futures) — Leveraged Funds category
    Crude (MCL/CL): Disaggregated — Producer/Merchant category

Usage:
    from strategy.cot_filter import get_cot_bias, COT_BIAS_LONG, COT_BIAS_SHORT

    bias = get_cot_bias("MGC")  # → "LONG", "SHORT", or "NEUTRAL"
    if bias == COT_BIAS_SHORT:
        # Skip long entries on MGC this week
        pass
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# ─── Constants ────────────────────────────────────────────────────────────────

COT_BIAS_LONG    = "LONG"
COT_BIAS_SHORT   = "SHORT"
COT_BIAS_NEUTRAL = "NEUTRAL"

# COT Index thresholds
BULL_THRESHOLD = 80  # Index > 80 = Producers/Commercials bullish → long bias
BEAR_THRESHOLD = 20  # Index < 20 = Producers/Commercials bearish → short bias

# Lookback period: 3-year default (Larry Williams standard)
LOOKBACK_WEEKS = 156

# Cache directory
CACHE_DIR = Path(__file__).parent.parent / "data" / "cot_cache"
CACHE_EXPIRY_HOURS = 48  # Re-download after 48h (COT updates weekly on Fridays)

# CFTC commodity codes for relevant instruments
CFTC_CODES = {
    "MGC": "088691",   # COMEX Gold (100 troy oz)
    "GC":  "088691",   # same
    "SIL": "084691",   # COMEX Silver
    "SI":  "084691",   # same
    "MCL": "067651",   # NYMEX Crude Oil (WTI)
    "CL":  "067651",   # same
}

# For equity index futures: use TFF report with Leveraged Funds as contrarian signal
EQUITY_INDEX_SYMBOLS = {"MES", "ES", "MNQ", "NQ", "MYM"}


# ─── Public API ───────────────────────────────────────────────────────────────

def get_cot_bias(symbol: str) -> str:
    """
    Return the current weekly COT directional bias for symbol.

    Args:
        symbol : Instrument root (e.g. "MGC", "MES", "SIL")

    Returns:
        "LONG", "SHORT", or "NEUTRAL"

    Notes:
        - Downloads data from CFTC on first call, caches for 48 hours
        - Returns NEUTRAL if data unavailable or signal is ambiguous
        - This is a WEEKLY bias — do not call more than once per day
    """
    symbol = symbol.upper()
    root = "".join(c for c in symbol if c.isalpha())

    try:
        if root in EQUITY_INDEX_SYMBOLS:
            return _equity_cot_bias(root)
        elif root in CFTC_CODES:
            return _commodity_cot_bias(root)
        else:
            logger.debug(f"COT: no mapping for symbol '{root}' — returning NEUTRAL")
            return COT_BIAS_NEUTRAL
    except Exception as e:
        logger.warning(f"COT bias failed for {root}: {e}")
        return COT_BIAS_NEUTRAL


def get_cot_details(symbol: str) -> dict:
    """
    Return detailed COT data for a symbol — for dashboard display.

    Returns:
        dict with keys: bias, prod_index, mm_index, mm_zscore, as_of_date, error
    """
    symbol = symbol.upper()
    root = "".join(c for c in symbol if c.isalpha())
    try:
        if root in CFTC_CODES:
            df = _load_commodity_cot(root)
            if df is None or df.empty:
                return {"bias": COT_BIAS_NEUTRAL, "error": "No COT data available"}
            last = df.iloc[-1]
            bias = _bias_from_indices(float(last["prod_index"]), float(last["mm_index"]))
            return {
                "bias":         bias,
                "prod_index":   round(float(last["prod_index"]), 1),
                "mm_index":     round(float(last["mm_index"]), 1),
                "mm_zscore":    round(float(last["mm_zscore"]),  2),
                "as_of_date":   str(last["Report_Date"])[:10],
                "error":        None,
            }
        return {"bias": COT_BIAS_NEUTRAL, "error": f"No COT mapping for {root}"}
    except Exception as e:
        return {"bias": COT_BIAS_NEUTRAL, "error": str(e)}


# ─── Commodity COT (Gold, Silver, Crude) ──────────────────────────────────────

def _commodity_cot_bias(root: str) -> str:
    df = _load_commodity_cot(root)
    if df is None or df.empty:
        return COT_BIAS_NEUTRAL
    last = df.iloc[-1]
    return _bias_from_indices(float(last["prod_index"]), float(last["mm_index"]))


def _bias_from_indices(prod_index: float, mm_index: float) -> str:
    """
    Determine directional bias from Producer and Managed Money indices.

    Signal logic:
        LONG:  Producer Index > BULL_THRESHOLD  (commercials bullish)
               AND Managed Money Index < (100 - BULL_THRESHOLD)  (speculators not crowded long)
        SHORT: Producer Index < BEAR_THRESHOLD  (commercials bearish)
               AND Managed Money Index > (100 - BEAR_THRESHOLD)  (speculators not crowded short)
        NEUTRAL: Neither extreme
    """
    if prod_index > BULL_THRESHOLD and mm_index < (100 - BULL_THRESHOLD + 10):
        return COT_BIAS_LONG
    if prod_index < BEAR_THRESHOLD and mm_index > (100 - BEAR_THRESHOLD - 10):
        return COT_BIAS_SHORT
    return COT_BIAS_NEUTRAL


# ─── Equity Index COT (MES/ES via TFF Leveraged Funds — contrarian) ───────────

def _equity_cot_bias(root: str) -> str:
    """
    For equity index futures, use Leveraged Funds (hedge funds/CTAs)
    from the TFF report as a CONTRARIAN signal.

    Leveraged Funds at extreme net short = potential bottom (contrarian long)
    Leveraged Funds at extreme net long = potential top (contrarian short)
    """
    df = _load_tff_cot()
    if df is None or df.empty:
        return COT_BIAS_NEUTRAL

    # Filter for S&P500 (consolidated ES/MES/SPX)
    sp_df = df[df['Market_and_Exchange_Names'].str.contains(
        'S&P 500|S&P500|E-MINI|MICRO E-MINI', case=False, na=False
    )].copy()
    if sp_df.empty:
        return COT_BIAS_NEUTRAL

    sp_df = sp_df.sort_values('Report_Date').reset_index(drop=True)

    # Leveraged Funds net positioning
    try:
        sp_df['lev_net'] = sp_df['Lev_Money_Positions_Long_All'] - sp_df['Lev_Money_Positions_Short_All']
    except KeyError:
        return COT_BIAS_NEUTRAL

    def cot_index(s: pd.Series, n: int) -> pd.Series:
        roll_min = s.rolling(n).min()
        roll_max = s.rolling(n).max()
        return 100 * (s - roll_min) / (roll_max - roll_min + 1e-9)

    sp_df['lev_index'] = cot_index(sp_df['lev_net'], LOOKBACK_WEEKS)
    last_idx = sp_df['lev_index'].iloc[-1]

    # CONTRARIAN: Leveraged Funds at extreme long → short bias; extreme short → long bias
    if last_idx < BEAR_THRESHOLD:      # Hedge funds heavily net short → contrarian LONG
        return COT_BIAS_LONG
    if last_idx > BULL_THRESHOLD:      # Hedge funds heavily net long → contrarian SHORT
        return COT_BIAS_SHORT
    return COT_BIAS_NEUTRAL


# ─── Data Loading ─────────────────────────────────────────────────────────────

def _load_commodity_cot(root: str) -> Optional[pd.DataFrame]:
    """Load and process Disaggregated COT data for a commodity."""
    cache_file = CACHE_DIR / f"disagg_{root}.parquet"

    if _is_cache_fresh(cache_file):
        return pd.read_parquet(cache_file)

    df = _download_disaggregated_multi_year(range(2006, datetime.now().year + 1))
    if df is None:
        return None

    code = CFTC_CODES[root]
    gold = df[df['CFTC_Commodity_Code'].astype(str).str.strip() == code].copy()
    if gold.empty:
        logger.warning(f"COT: no data for code {code} ({root})")
        return None

    gold['Report_Date'] = pd.to_datetime(gold['Report_Date_as_YYYY-MM-DD'])
    gold = gold.sort_values('Report_Date').reset_index(drop=True)

    # Net positions
    gold['prod_net'] = gold['Prod_Merc_Positions_Long_ALL'].fillna(0) - gold['Prod_Merc_Positions_Short_ALL'].fillna(0)
    gold['mm_net']   = gold['M_Money_Positions_Long_ALL'].fillna(0)   - gold['M_Money_Positions_Short_ALL'].fillna(0)

    def cot_index(s: pd.Series, n: int) -> pd.Series:
        return 100 * (s - s.rolling(n).min()) / (s.rolling(n).max() - s.rolling(n).min() + 1e-9)

    gold['prod_index'] = cot_index(gold['prod_net'], LOOKBACK_WEEKS)
    gold['mm_index']   = cot_index(gold['mm_net'],   LOOKBACK_WEEKS)
    gold['mm_zscore']  = ((gold['mm_net'] - gold['mm_net'].rolling(LOOKBACK_WEEKS).mean())
                          / gold['mm_net'].rolling(LOOKBACK_WEEKS).std())

    result = gold[['Report_Date', 'prod_net', 'mm_net', 'prod_index', 'mm_index', 'mm_zscore']].dropna()

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    result.to_parquet(cache_file, index=False)
    return result


def _load_tff_cot() -> Optional[pd.DataFrame]:
    """Load TFF (Traders in Financial Futures) data for equity index futures."""
    cache_file = CACHE_DIR / "tff.parquet"

    if _is_cache_fresh(cache_file):
        return pd.read_parquet(cache_file)

    frames = []
    for year in range(2006, datetime.now().year + 1):
        url = f"https://www.cftc.gov/files/dea/history/fut_fin_txt_{year}.zip"
        try:
            import requests, zipfile, io
            r = requests.get(url, timeout=30)
            r.raise_for_status()
            with zipfile.ZipFile(io.BytesIO(r.content)) as z:
                df = pd.read_csv(io.BytesIO(z.read(z.namelist()[0])), low_memory=False)
            df['Report_Date'] = pd.to_datetime(df['Report_Date_as_YYYY-MM-DD'])
            frames.append(df)
        except Exception as e:
            logger.debug(f"TFF {year}: {e}")

    if not frames:
        return None

    result = pd.concat(frames, ignore_index=True).sort_values('Report_Date')
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    result.to_parquet(cache_file, index=False)
    return result


def _download_disaggregated_multi_year(years) -> Optional[pd.DataFrame]:
    """Download multiple years of Disaggregated COT data."""
    try:
        import requests, zipfile, io
    except ImportError:
        logger.error("COT download requires 'requests' library: pip install requests")
        return None

    frames = []
    for year in years:
        url = f"https://www.cftc.gov/files/dea/history/fut_disagg_txt_{year}.zip"
        try:
            r = requests.get(url, timeout=30)
            r.raise_for_status()
            with zipfile.ZipFile(io.BytesIO(r.content)) as z:
                df = pd.read_csv(io.BytesIO(z.read(z.namelist()[0])), low_memory=False)
            frames.append(df)
        except Exception as e:
            logger.debug(f"COT disagg {year}: {e}")

    if not frames:
        logger.warning("COT: could not download any data")
        return None

    return pd.concat(frames, ignore_index=True)


def _is_cache_fresh(path: Path) -> bool:
    """Return True if cache file exists and is newer than CACHE_EXPIRY_HOURS."""
    if not path.exists():
        return False
    mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    age = datetime.now(tz=timezone.utc) - mtime
    return age < timedelta(hours=CACHE_EXPIRY_HOURS)
