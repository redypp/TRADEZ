"""
Live market fundamentals for MES (Micro E-mini S&P 500).

Fetches real-time data from Yahoo Finance to assess the macro regime
before placing trades.  Factors watched:

    VIX    — CBOE Volatility Index (market fear gauge)
    TNX    — 10-Year Treasury Yield (rate environment)
    DXY    — US Dollar Index (inverse equity correlation)
    SPY    — S&P 500 ETF volume vs average (participation check)

Regime output:
    RISK_ON   — All green, trade normally
    CAUTIOUS  — One headwind present, trade with selectivity
    RISK_OFF  — Multiple headwinds, skip marginal setups
    NO_TRADE  — Extreme conditions, sit out entirely
"""

import logging
import pandas as pd
import yfinance as yf
from config import settings

logger = logging.getLogger(__name__)


def _fetch_ticker(ticker: str, period: str = "20d", interval: str = "1d") -> pd.DataFrame:
    """Download ticker data silently, return empty DataFrame on failure."""
    try:
        df = yf.download(ticker, period=period, interval=interval,
                         progress=False, auto_adjust=True)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df.columns = [c.lower() for c in df.columns]
        return df.dropna()
    except Exception as e:
        logger.warning(f"Could not fetch {ticker}: {e}")
        return pd.DataFrame()


def _trend_pct(series: pd.Series, lookback: int) -> float:
    """Return percentage change over the last `lookback` bars."""
    if len(series) < lookback + 1:
        return 0.0
    prev = series.iloc[-lookback - 1]
    if prev == 0:
        return 0.0
    return float((series.iloc[-1] - prev) / prev * 100)


def _trend_abs(series: pd.Series, lookback: int) -> float:
    """Return absolute change over the last `lookback` bars."""
    if len(series) < lookback + 1:
        return 0.0
    return float(series.iloc[-1] - series.iloc[-lookback - 1])


def get_live_fundamentals() -> dict:
    """
    Fetch live market fundamentals relevant to MES trading.

    Returns a dict with:
        vix           — Current VIX level
        vix_regime    — 'LOW' | 'NORMAL' | 'ELEVATED' | 'HIGH' | 'EXTREME'
        yield_10y     — Current 10-year yield (%)
        yield_trend   — 'RISING' | 'STABLE' | 'FALLING' (5-day change)
        yield_change  — 5-day yield change in percentage points
        dxy           — Current DXY level
        dxy_trend     — 'STRENGTHENING' | 'STABLE' | 'WEAKENING'
        dxy_change    — 5-day DXY % change
        spy_vol_ratio — Today's SPY volume vs 20-day avg (>1.2 = active market)
        regime        — Overall: 'RISK_ON' | 'CAUTIOUS' | 'RISK_OFF' | 'NO_TRADE'
        headwinds     — List of active headwind descriptions
        tailwinds     — List of active tailwind descriptions
        notes         — Human-readable summary string
    """
    result = {
        "vix": None,
        "vix_regime": "UNKNOWN",
        "yield_10y": None,
        "yield_trend": "UNKNOWN",
        "yield_change": 0.0,
        "dxy": None,
        "dxy_trend": "UNKNOWN",
        "dxy_change": 0.0,
        "spy_vol_ratio": None,
        "regime": "CAUTIOUS",
        "headwinds": [],
        "tailwinds": [],
        "notes": "Fundamentals unavailable",
    }

    headwinds = []
    tailwinds = []

    # ── VIX ──────────────────────────────────────────────────────────────
    vix_df = _fetch_ticker(settings.FUNDAMENTALS_TICKERS["vix"])
    if not vix_df.empty:
        vix = float(vix_df["close"].iloc[-1])
        result["vix"] = round(vix, 2)

        if vix > settings.VIX_EXTREME:
            result["vix_regime"] = "EXTREME"
            headwinds.append(f"VIX EXTREME ({vix:.1f}) — market panic, no new longs")
        elif vix > settings.VIX_HIGH_MAX:
            result["vix_regime"] = "HIGH"
            headwinds.append(f"VIX HIGH ({vix:.1f}) — skip marginal setups")
        elif vix > settings.VIX_ELEVATED_MAX:
            result["vix_regime"] = "ELEVATED"
            headwinds.append(f"VIX elevated ({vix:.1f}) — trade selectively")
        elif vix > settings.VIX_NORMAL_MAX:
            result["vix_regime"] = "NORMAL"
        else:
            result["vix_regime"] = "LOW"
            tailwinds.append(f"VIX low ({vix:.1f}) — low fear, risk-on environment")
    else:
        logger.warning("VIX data unavailable — proceeding with caution")

    # ── 10-Year Treasury Yield ───────────────────────────────────────────
    tnx_df = _fetch_ticker(settings.FUNDAMENTALS_TICKERS["yield_10y"])
    if not tnx_df.empty:
        yield_now = float(tnx_df["close"].iloc[-1])
        result["yield_10y"] = round(yield_now, 3)
        # Use absolute change (in percentage points = 100 basis points per pp)
        yield_chg = _trend_abs(tnx_df["close"], settings.YIELD_LOOKBACK_DAYS)
        result["yield_change"] = round(yield_chg, 3)
        bps = round(yield_chg * 100, 1)

        if yield_chg > settings.YIELD_RISING_THRESH:
            result["yield_trend"] = "RISING"
            headwinds.append(
                f"Yields rising sharply ({yield_now:.3f}%, +{bps:.0f}bps/5d) — equity headwind"
            )
        elif yield_chg < -settings.YIELD_RISING_THRESH:
            result["yield_trend"] = "FALLING"
            tailwinds.append(
                f"Yields falling ({yield_now:.3f}%, {bps:.0f}bps/5d) — equity tailwind"
            )
        else:
            result["yield_trend"] = "STABLE"

    # ── US Dollar Index (DXY) ────────────────────────────────────────────
    dxy_df = _fetch_ticker(settings.FUNDAMENTALS_TICKERS["dxy"])
    if not dxy_df.empty:
        dxy_now = float(dxy_df["close"].iloc[-1])
        result["dxy"] = round(dxy_now, 2)
        dxy_chg = _trend_pct(dxy_df["close"], settings.DXY_LOOKBACK_DAYS)
        result["dxy_change"] = round(dxy_chg, 3)

        if dxy_chg > settings.DXY_STRONG_THRESH:
            result["dxy_trend"] = "STRENGTHENING"
            headwinds.append(
                f"Dollar strengthening ({dxy_now:.1f}, +{dxy_chg:.2f}%/5d) — equity headwind"
            )
        elif dxy_chg < -settings.DXY_STRONG_THRESH:
            result["dxy_trend"] = "WEAKENING"
            tailwinds.append(
                f"Dollar weakening ({dxy_now:.1f}, {dxy_chg:.2f}%/5d) — equity tailwind"
            )
        else:
            result["dxy_trend"] = "STABLE"

    # ── SPY Volume ───────────────────────────────────────────────────────
    spy_df = _fetch_ticker(settings.FUNDAMENTALS_TICKERS["spy"], period="30d")
    if not spy_df.empty and "volume" in spy_df.columns:
        vol_avg = float(spy_df["volume"].iloc[:-1].tail(20).mean())
        vol_today = float(spy_df["volume"].iloc[-1])
        if vol_avg > 0:
            vol_ratio = round(vol_today / vol_avg, 2)
            result["spy_vol_ratio"] = vol_ratio
            if vol_ratio >= 1.5:
                tailwinds.append(f"SPY volume elevated ({vol_ratio:.1f}x avg) — high participation")
            elif vol_ratio < 0.6:
                headwinds.append(f"SPY volume low ({vol_ratio:.1f}x avg) — choppy conditions likely")

    # ── Regime Assessment ────────────────────────────────────────────────
    result["headwinds"] = headwinds
    result["tailwinds"] = tailwinds

    n_headwinds = len(headwinds)

    if result["vix_regime"] == "EXTREME":
        regime = "NO_TRADE"
    elif result["vix_regime"] == "HIGH" or n_headwinds >= 3:
        regime = "RISK_OFF"
    elif n_headwinds >= 1:
        regime = "CAUTIOUS"
    elif len(tailwinds) >= 2:
        regime = "RISK_ON"
    else:
        regime = "RISK_ON"

    result["regime"] = regime

    # ── Summary note ────────────────────────────────────────────────────
    vix_str = f"VIX {result['vix']}" if result['vix'] else "VIX N/A"
    yld_str = f"10Y {result['yield_10y']}%" if result['yield_10y'] else "10Y N/A"
    dxy_str = f"DXY {result['dxy']}" if result['dxy'] else "DXY N/A"
    result["notes"] = f"{vix_str} | {yld_str} | {dxy_str} → {regime}"

    logger.info(f"Fundamentals: {result['notes']}")
    return result


def print_fundamentals(f: dict) -> None:
    """Print a formatted fundamentals report to stdout."""
    print("\n" + "─" * 50)
    print("  MARKET FUNDAMENTALS (MES)")
    print("─" * 50)

    regime_icons = {
        "RISK_ON": "✓ RISK ON",
        "CAUTIOUS": "~ CAUTIOUS",
        "RISK_OFF": "✗ RISK OFF",
        "NO_TRADE": "✗✗ NO TRADE — VIX EXTREME",
    }
    print(f"  Regime : {regime_icons.get(f['regime'], f['regime'])}")
    print()

    if f["vix"] is not None:
        print(f"  VIX    : {f['vix']:.1f}  [{f['vix_regime']}]")
    if f["yield_10y"] is not None:
        chg = f["yield_change"]
        bps = chg * 100
        direction = f"{'↑' if chg > 0 else '↓'}{abs(bps):.0f}bps/5d"
        print(f"  10Y    : {f['yield_10y']:.3f}%  {direction}  [{f['yield_trend']}]")
    if f["dxy"] is not None:
        chg = f["dxy_change"]
        direction = f"{'↑' if chg > 0 else '↓'}{abs(chg):.2f}%/5d"
        print(f"  DXY    : {f['dxy']:.2f}  {direction}  [{f['dxy_trend']}]")
    if f["spy_vol_ratio"] is not None:
        print(f"  SPY Vol: {f['spy_vol_ratio']:.2f}x avg")

    if f["tailwinds"]:
        print()
        for t in f["tailwinds"]:
            print(f"  + {t}")
    if f["headwinds"]:
        print()
        for h in f["headwinds"]:
            print(f"  - {h}")

    print("─" * 50)
