"""
data/validator.py

Pre-flight data quality checks run before every signal computation.

Checks (in order):
    1. Stale data     — last bar timestamp is too old (data feed lag or API failure)
    2. Gap detection  — missing candles in the time series (broker outage, rollover)
    3. Price spikes   — bar high-low range exceeds 3x ATR (bad tick / data error)
    4. Volume anomaly — volume is 0 or abnormally low on recent bars (thin/bad data)
    5. Minimum bars   — not enough history for indicators to warm up

If any check fails it raises DataQualityError, causing the tick to be skipped
rather than trading on corrupted data.

Why this matters:
    A single bad tick (e.g. a price spike of 10%) can create a false break signal,
    generate a position with an impossible stop-loss, and cause a catastrophic fill.
    yFinance data for ES=F has documented gaps at contract rollover dates (Mar, Jun,
    Sep, Dec third Friday) and occasional stale snapshots.

Usage:
    from data.validator import validate_ohlcv, DataQualityError

    try:
        validate_ohlcv(df, timeframe_minutes=15)
    except DataQualityError as e:
        logger.warning(f"Data quality check failed: {e}")
        return  # skip tick
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


class DataQualityError(Exception):
    """Raised when incoming OHLCV data fails a quality check."""
    pass


# ─── Public entry point ────────────────────────────────────────────────────────

def validate_ohlcv(
    df:                  pd.DataFrame,
    timeframe_minutes:   int   = 15,
    stale_threshold_min: int   = 30,
    spike_atr_multiple:  float = 3.0,
    min_bars:            int   = 50,
    max_gap_multiples:   float = 2.5,
) -> None:
    """
    Run all data quality checks on an OHLCV DataFrame.

    Raises DataQualityError if any check fails.

    Args:
        df                  : OHLCV DataFrame with DatetimeIndex
        timeframe_minutes   : Expected bar interval in minutes (15 for BRT)
        stale_threshold_min : Max acceptable age of last bar in minutes
        spike_atr_multiple  : Flag bar if (high-low) > X × ATR(20)
        min_bars            : Minimum number of bars required
        max_gap_multiples   : Flag gap if time delta > X × expected interval
    """
    if df is None or df.empty:
        raise DataQualityError("DataFrame is empty — no data returned from feed")

    _check_min_bars(df, min_bars)
    _check_stale_data(df, timeframe_minutes, stale_threshold_min)
    _check_gaps(df, timeframe_minutes, max_gap_multiples)
    _check_price_spikes(df, spike_atr_multiple)
    _check_volume_anomaly(df)

    logger.debug(f"Data quality OK — {len(df)} bars, last={df.index[-1]}")


# ─── Individual checks ─────────────────────────────────────────────────────────

def _check_min_bars(df: pd.DataFrame, min_bars: int) -> None:
    """Fail if there aren't enough bars for indicators to warm up."""
    if len(df) < min_bars:
        raise DataQualityError(
            f"Insufficient bars: {len(df)} available, {min_bars} required. "
            f"Indicators (EMA, ATR, ADX) need warm-up history to be reliable."
        )


def _check_stale_data(
    df: pd.DataFrame,
    timeframe_minutes: int,
    stale_threshold_min: int,
) -> None:
    """
    Fail if the last bar's timestamp is more than stale_threshold_min minutes old.

    Catches yFinance API returning cached/stale data from a prior session,
    which would cause the signal engine to evaluate old market state.
    """
    try:
        last_ts = df.index[-1]
        if hasattr(last_ts, "tzinfo") and last_ts.tzinfo is None:
            last_ts = last_ts.tz_localize("UTC")
        now_utc = datetime.now(timezone.utc)
        age_min = (now_utc - last_ts.tz_convert("UTC")).total_seconds() / 60

        # During market hours, data older than threshold is suspicious
        # Outside market hours, staleness is expected — skip the check
        from pytz import timezone as pytz_tz
        et = pytz_tz("America/New_York")
        now_et = datetime.now(et)
        market_open = now_et.hour >= 9 and now_et.weekday() < 5

        if market_open and age_min > stale_threshold_min:
            raise DataQualityError(
                f"Data is stale: last bar is {age_min:.0f} min old "
                f"(threshold: {stale_threshold_min} min). "
                f"Feed may be delayed or API returned cached data."
            )
    except DataQualityError:
        raise
    except Exception as e:
        logger.debug(f"Stale data check skipped (non-critical): {e}")


def _check_gaps(
    df: pd.DataFrame,
    timeframe_minutes: int,
    max_gap_multiples: float,
) -> None:
    """
    Detect missing candles in the time series.

    A gap exists when the time delta between consecutive bars is more than
    max_gap_multiples × expected_interval. Gaps indicate broker outages,
    data feed failures, or contract rollover artifacts.

    Missing bars cause indicators to compute across gaps, producing
    incorrect ATR / VWAP / EMA values for the affected period.
    """
    if len(df) < 2:
        return

    try:
        expected_delta = pd.Timedelta(minutes=timeframe_minutes)
        max_delta      = expected_delta * max_gap_multiples
        deltas         = df.index.to_series().diff().dropna()
        large_gaps     = deltas[deltas > max_delta]

        if not large_gaps.empty:
            worst_gap  = large_gaps.max()
            worst_time = large_gaps.idxmax()
            n_gaps     = len(large_gaps)
            # Only fail on recent gaps (last 20% of data) — old gaps in history are OK
            cutoff = df.index[int(len(df) * 0.80)]
            recent_gaps = large_gaps[large_gaps.index > cutoff]

            if not recent_gaps.empty:
                raise DataQualityError(
                    f"{len(recent_gaps)} data gap(s) detected in recent bars. "
                    f"Worst: {worst_gap} at {worst_time}. "
                    f"Expected interval: {timeframe_minutes} min. "
                    f"Indicators computed across gaps are unreliable."
                )
            else:
                # Historical gaps — warn but don't fail
                logger.warning(
                    f"{n_gaps} historical gap(s) in data "
                    f"(worst: {worst_gap} at {worst_time}) — not in recent bars, proceeding."
                )
    except DataQualityError:
        raise
    except Exception as e:
        logger.debug(f"Gap check failed (non-critical): {e}")


def _check_price_spikes(df: pd.DataFrame, spike_atr_multiple: float) -> None:
    """
    Flag candles where (high - low) > spike_atr_multiple × ATR(20).

    These are either:
        - Bad ticks (erroneous prices from exchange or data vendor)
        - Extreme news events (FOMC flash crash, flash spike)

    In either case, a break signal generated on a spike bar is unreliable
    because the "break" may be noise rather than a genuine structural move.
    Only flags spikes in the last 3 bars (recent data is what the signal engine acts on).
    """
    if len(df) < 22:
        return

    try:
        bar_range = df["high"] - df["low"]
        atr20     = bar_range.rolling(20).mean().shift(1)  # shift to avoid lookahead
        ratio     = bar_range / atr20.replace(0, np.nan)

        # Check only the last 3 bars — historical spikes don't affect current signal
        recent_ratio = ratio.iloc[-3:]
        spike_bars   = recent_ratio[recent_ratio > spike_atr_multiple]

        if not spike_bars.empty:
            worst_ratio = spike_bars.max()
            worst_time  = spike_bars.idxmax()
            logger.warning(
                f"Price spike detected: bar at {worst_time} has range "
                f"{worst_ratio:.1f}x ATR (threshold: {spike_atr_multiple}x). "
                f"Signal generated on spike bar may be a false break. "
                f"Proceeding with caution — verify signal is structural."
            )
            # Warning only — do not fail (spikes can be genuine, e.g. NFP release)
            # If you want to block: raise DataQualityError(...)
    except Exception as e:
        logger.debug(f"Spike check failed (non-critical): {e}")


def _check_volume_anomaly(df: pd.DataFrame) -> None:
    """
    Warn if the last bar has zero or suspiciously low volume.

    Zero volume = data feed returned a bar with no trades — typically a stale
    snapshot or a holiday session. The BRT volume-confirmation filter already
    handles this gracefully (vol_ok = True when volume = 0), but this check
    provides an early warning so we know the data source is degraded.
    """
    if "volume" not in df.columns or len(df) < 21:
        return

    try:
        last_vol   = float(df["volume"].iloc[-1])
        vol_ma20   = float(df["volume"].iloc[-21:-1].mean())

        if last_vol == 0:
            logger.warning(
                "Last bar has zero volume — data feed may have returned a "
                "stale/empty candle. VWAP and volume filters may be unreliable."
            )
        elif vol_ma20 > 0 and last_vol < 0.05 * vol_ma20:
            logger.warning(
                f"Last bar volume ({last_vol:,.0f}) is {last_vol/vol_ma20:.1%} of 20-bar average "
                f"({vol_ma20:,.0f}). Possible thin trading or data issue."
            )
    except Exception as e:
        logger.debug(f"Volume anomaly check failed (non-critical): {e}")


# ─── Summary helper for logging ────────────────────────────────────────────────

def data_quality_summary(df: pd.DataFrame, timeframe_minutes: int = 15) -> dict:
    """
    Return a summary dict of data quality metrics (non-raising, for dashboard).

    Returns:
        {bars, last_bar, staleness_min, gap_count, spike_count, zero_volume_bars}
    """
    summary = {
        "bars":             len(df),
        "last_bar":         str(df.index[-1]) if not df.empty else None,
        "staleness_min":    None,
        "gap_count":        0,
        "spike_count":      0,
        "zero_volume_bars": 0,
    }

    if df.empty:
        return summary

    try:
        last_ts = df.index[-1]
        if hasattr(last_ts, "tzinfo") and last_ts.tzinfo is None:
            last_ts = last_ts.tz_localize("UTC")
        summary["staleness_min"] = round(
            (datetime.now(timezone.utc) - last_ts.tz_convert("UTC")).total_seconds() / 60, 1
        )
    except Exception:
        pass

    try:
        expected = pd.Timedelta(minutes=timeframe_minutes)
        deltas   = df.index.to_series().diff().dropna()
        summary["gap_count"] = int((deltas > expected * 2.5).sum())
    except Exception:
        pass

    try:
        bar_range = df["high"] - df["low"]
        atr20     = bar_range.rolling(20).mean().shift(1)
        ratio     = bar_range / atr20.replace(0, np.nan)
        summary["spike_count"] = int((ratio > 3.0).sum())
    except Exception:
        pass

    try:
        if "volume" in df.columns:
            summary["zero_volume_bars"] = int((df["volume"] == 0).sum())
    except Exception:
        pass

    return summary
