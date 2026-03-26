"""
Break & Retest Strategy — MES (Micro E-mini S&P 500)
Timeframe: 15-minute candles

─── HOW IT WORKS ────────────────────────────────────────────────────────────

1. LEVEL IDENTIFICATION
   Three types of levels are tracked simultaneously (priority order):
     • VWAP    — Volume Weighted Average Price (resets daily)
                  The most actively traded level on MES. Institutions defend
                  VWAP all session. Breaks + retests here = highest-volume setups.
     • PDH/PDL — Previous Day High / Low (heavily watched institutional levels)
     • Swing   — Rolling N-bar high/low (structural rejection points)

2. BREAK DETECTION
   A "break" is confirmed when:
     • Close > level + BRT_BREAK_BUFFER * ATR  (bull break)
     • Close < level − BRT_BREAK_BUFFER * ATR  (bear break)
     • Volume on break candle ≥ BRT_VOLUME_THRESHOLD × 20-bar vol avg
       (skipped if volume data is zero/unavailable)

3. RETEST DETECTION
   After a break, the system watches for price to return to the broken level:
     • Retest zone : [level − tolerance, level + tolerance]
     • VWAP uses tighter tolerance (BRT_VWAP_TOLERANCE) — it's a precise level
   If no retest within BRT_MAX_RETEST_BARS candles (8 × 15min = 2h) → reset.

4. ENTRY CONFIRMATION  (all required)
   For LONG entry after bull break + retest:
     a. Bullish confirmation candle: close > open
     b. Close clearly above broken level
     c. EMA20 trend: close > EMA(20)
     d. ADX > BRT_ADX_MIN (20 on 15min)
     e. RSI in range BRT_RSI_LONG_MIN–MAX (35–75)
     f. Session timing: BRT_SESSION_START_HOUR–END_HOUR ET

5. STOP LOSS / TAKE PROFIT
   SL: below retest candle low − BRT_SL_BUFFER * ATR
   TP: entry + BRT_TP_RR × risk  (default 2:1 R:R)

─── OUTPUT COLUMNS ──────────────────────────────────────────────────────────
   signal, stop_loss, take_profit, retest_level, level_type
   ema20, atr, adx, rsi, vwap, pdh, pdl, swing_hi, swing_lo
"""

import numpy as np
import pandas as pd
import ta
import logging
from config import settings
from strategy.volume_profile import add_session_vp
from strategy.smc_levels import add_equal_highs_lows, add_fvg_levels

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Helper: Level-specific ADX minimum threshold
# ─────────────────────────────────────────────────────────────────────────────

# Per-level ADX adjustments (delta applied on top of regime-adaptive base).
# See config/settings.py BRT_ADX_DELTA_* for rationale.
_LEVEL_ADX_DELTAS: dict[str, int] = {
    "VWAP":   settings.BRT_ADX_DELTA_VWAP,   # -5: VWAP works in ranging markets
    "SWING":  settings.BRT_ADX_DELTA_SWING,  # +2: swing needs stronger trend
    "FVG":    settings.BRT_ADX_DELTA_FVG,    # +2: FVG is lowest-confidence level
}


def _level_adx_min(level_type: str, base_adx_min: float) -> float:
    """
    Return the effective ADX minimum for a given level type.

    Applies a per-level delta on top of the regime-adaptive base, then
    clamps to BRT_ADX_FLOOR so we never trade pure noise.

    Examples (NORMAL regime, base=20):
        VWAP  → max(12, 20 - 5) = 15   (VWAP retests OK in moderate chop)
        PDH   → max(12, 20 + 0) = 20   (default)
        SWING → max(12, 20 + 2) = 22   (needs cleaner trend)
    """
    delta = _LEVEL_ADX_DELTAS.get(level_type, 0)
    return max(settings.BRT_ADX_FLOOR, base_adx_min + delta)


# ─────────────────────────────────────────────────────────────────────────────
# Helper: Previous Day High / Low
# ─────────────────────────────────────────────────────────────────────────────

def _calc_vwap(df: pd.DataFrame) -> pd.Series:
    """
    Compute intraday VWAP, resetting at the start of each trading day.
    VWAP = cumulative(typical_price × volume) / cumulative(volume)
    Typical price = (high + low + close) / 3
    """
    try:
        dates = df.index.normalize()
    except AttributeError:
        dates = pd.to_datetime(df.index).normalize()

    # Use date string as groupby key — works regardless of timezone
    date_str = dates.strftime("%Y-%m-%d")

    tp  = (df["high"] + df["low"] + df["close"]) / 3
    tpv = tp * df["volume"]

    cum_tpv = tpv.groupby(date_str).cumsum()
    cum_vol = df["volume"].groupby(date_str).cumsum()

    vwap = cum_tpv / cum_vol.replace(0, np.nan)
    return vwap


def _calc_opening_range(df: pd.DataFrame):
    """
    Compute the Opening Range High/Low for each day.
    Opening Range = high/low of the first 30 minutes of the regular session (9:30-10:00 ET).
    These are key intraday breakout levels watched by day traders on MES.
    """
    try:
        idx_et = df.index.tz_convert("America/New_York")
    except Exception:
        idx_et = pd.to_datetime(df.index).tz_localize("America/New_York")

    # Opening range bars: 9:30 and 9:45 (first two 15-min bars)
    or_mask = (idx_et.hour == 9) & (idx_et.minute.isin([30, 45]))
    df_or = df[or_mask].copy()

    if df_or.empty:
        return pd.Series(np.nan, index=df.index), pd.Series(np.nan, index=df.index)

    try:
        dates = df_or.index.normalize()
    except Exception:
        dates = pd.to_datetime(df_or.index).normalize()

    df_or["_date"] = dates.strftime("%Y-%m-%d")
    or_high = df_or.groupby("_date")["high"].max()
    or_low  = df_or.groupby("_date")["low"].min()

    # Map back to full intraday index
    try:
        full_dates = df.index.normalize().strftime("%Y-%m-%d")
    except Exception:
        full_dates = pd.to_datetime(df.index).normalize().strftime("%Y-%m-%d")

    orh = pd.Series(full_dates, index=df.index).map(or_high)
    orl = pd.Series(full_dates, index=df.index).map(or_low)
    return orh.values, orl.values


def _calc_pdh_pdl(df: pd.DataFrame):
    """
    Compute previous session high and low for each intraday bar.
    Resamples to daily, shifts by 1 day, then forward-fills back to the
    intraday index so every bar within a session shares the same PDH/PDL.
    """
    try:
        dates = df.index.normalize()
    except AttributeError:
        dates = pd.to_datetime(df.index).normalize()

    df_work = df.copy()
    df_work["_date"] = dates

    daily = df_work.groupby("_date").agg(daily_high=("high", "max"),
                                          daily_low=("low", "min"))
    daily.index = pd.to_datetime(daily.index)

    # Shift by 1 trading day → previous session
    daily_prev = daily.shift(1)

    pdh = df_work["_date"].map(daily_prev["daily_high"])
    pdl = df_work["_date"].map(daily_prev["daily_low"])

    return pdh.values, pdl.values


# ─────────────────────────────────────────────────────────────────────────────
# Core: Stateful Break & Retest Signal Detection
# ─────────────────────────────────────────────────────────────────────────────

def _detect_brt_signals(df: pd.DataFrame, long_only: bool,
                        regime_params: dict | None = None) -> tuple:
    """
    Iterate bar-by-bar and detect break & retest entry signals.

    State machine:
        NEUTRAL          → watching for a break above/below any tracked level
        WATCHING_LONG    → bull break confirmed, waiting for retest
        WATCHING_SHORT   → bear break confirmed, waiting for retest

    Args:
        df            : Prepared OHLCV DataFrame with indicators
        long_only     : If True, only long setups are generated
        regime_params : Adaptive param overrides from RegimeEngine (None = use settings defaults)

    Returns six numpy arrays: signals, stop_losses, take_profits, retest_levels, level_types, sweep_flags
    """
    # ── Resolve parameters (regime overrides, else settings defaults) ─────
    p = regime_params or {}
    adx_min        = p.get("adx_min",         settings.BRT_ADX_MIN)
    sl_buffer      = p.get("sl_buffer",        settings.BRT_SL_BUFFER)
    tp_rr          = p.get("tp_rr",            settings.BRT_TP_RR)
    max_retest_bars = p.get("max_retest_bars", settings.BRT_MAX_RETEST_BARS)
    lev_tolerance  = p.get("level_tolerance",  settings.BRT_LEVEL_TOLERANCE)
    break_body_min = p.get("break_body_min",   settings.BRT_BREAK_BODY_MIN)

    n = len(df)
    signals      = np.zeros(n, dtype=float)
    stop_losses  = np.full(n, np.nan)
    take_profits = np.full(n, np.nan)
    retest_arr   = np.full(n, np.nan)
    level_types  = [""] * n
    sweep_flags  = np.zeros(n, dtype=float)  # 1 = liquidity sweep confirmed at entry

    state         = "NEUTRAL"
    broken_level  = np.nan
    break_bar_idx = -1
    broken_ltype  = ""

    for i in range(1, n):
        row = df.iloc[i]

        # Skip bars outside trading session
        try:
            hour_et = row.name.tz_convert("America/New_York").hour
        except Exception:
            hour_et = settings.BRT_SESSION_START_HOUR  # default pass

        in_session = (
            settings.BRT_SESSION_START_HOUR <= hour_et < settings.BRT_SESSION_END_HOUR
            and not (settings.BRT_LUNCH_START_HOUR <= hour_et < settings.BRT_LUNCH_END_HOUR)
        )

        atr       = row["atr"]
        # VWAP uses tighter tolerance — it's a precise, actively defended level
        tolerance = (settings.BRT_VWAP_TOLERANCE if broken_ltype == "VWAP"
                     else lev_tolerance) * atr
        buf       = settings.BRT_BREAK_BUFFER * atr

        # ── Volume check helper ───────────────────────────────────────
        vol    = float(row["volume"]) if "volume" in df.columns else 0.0
        vol_ma = float(row["vol_ma"]) if "vol_ma" in df.columns else 0.0
        if vol > 0 and vol_ma > 0:
            vol_ok = vol >= settings.BRT_VOLUME_THRESHOLD * vol_ma
        else:
            vol_ok = True  # volume data absent → skip check

        # ── State: watching for retest ────────────────────────────────
        if state in ("WATCHING_LONG", "WATCHING_SHORT"):
            bars_waited = i - break_bar_idx

            if bars_waited > max_retest_bars:
                state = "NEUTRAL"
                broken_level = np.nan
                broken_ltype = ""
                break_bar_idx = -1

            elif state == "WATCHING_LONG":
                # Retest zone: price returns to near the broken level
                in_zone = (row["low"] <= broken_level + tolerance) and \
                          (row["close"] >= broken_level - tolerance)

                if in_zone and in_session:
                    # Confirmation confluence:
                    #   1. Bullish candle (close > open) with meaningful body
                    #   2. Close is clearly ABOVE the broken level (not just in zone)
                    #   3. EMA20 trend alignment
                    #   4. ADX >= level-specific minimum (regime base ± level delta)
                    #      VWAP allows lower ADX; SWING/FVG require higher ADX.
                    #   5. RSI in healthy range (not freefall, not overbought)
                    #   6. Liquidity sweep (optional): wick below level, close above
                    #      Confirms institutional stop hunt before the reversal.
                    candle_body   = row["close"] - row["open"]
                    bullish_body  = candle_body > 0
                    close_above   = row["close"] > broken_level
                    ema_ok        = row["close"] > row["ema20"]
                    adx_ok        = row["adx"] > _level_adx_min(broken_ltype, adx_min)
                    rsi_ok        = (settings.BRT_RSI_LONG_MIN < row["rsi"] < settings.BRT_RSI_LONG_MAX)
                    # Sweep: wick dipped below the level, close recovered above it
                    sweep_ok      = (not settings.BRT_REQUIRE_SWEEP or
                                     (row["low"] < broken_level and row["close"] > broken_level))
                    # VSA: close must be in the upper half of the bar's high-low range
                    # (filters doji/weak candles that close near the bottom despite being "bullish")
                    bar_range     = row["high"] - row["low"]
                    vsa_close_ok  = (not settings.BRT_VSA_CLOSE_POSITION or
                                     bar_range <= 0 or
                                     (row["close"] - row["low"]) / bar_range >= 0.5)
                    # VSA no-demand check: retest candle must not be a "no demand" bar
                    # No demand = narrow spread + low volume + weak close → professionals absent
                    # Research: MICROSTRUCTURE_RESEARCH.md § VSA detection thresholds
                    retest_vol    = float(row["volume"]) if "volume" in df.columns else 0.0
                    retest_vol_ma = float(row["vol_ma"]) if "vol_ma" in df.columns else 0.0
                    vsa_vol_ok    = (not settings.BRT_VSA_NO_DEMAND_CHECK or
                                     retest_vol_ma <= 0 or
                                     retest_vol >= settings.BRT_VSA_MIN_VOLUME_RATIO * retest_vol_ma)

                    if bullish_body and close_above and ema_ok and adx_ok and rsi_ok and sweep_ok and vsa_close_ok and vsa_vol_ok:
                        sl_candle = row["low"] - sl_buffer * atr
                        sl_level  = broken_level - sl_buffer * atr
                        sl        = min(sl_candle, sl_level)
                        risk      = row["close"] - sl
                        if risk > 0:
                            signals[i]      = 1
                            stop_losses[i]  = round(sl, 2)
                            take_profits[i] = round(row["close"] + tp_rr * risk, 2)
                            retest_arr[i]   = broken_level
                            level_types[i]  = broken_ltype
                            # Record whether a sweep occurred (wick below level, close above)
                            sweep_flags[i]  = 1.0 if (row["low"] < broken_level and row["close"] > broken_level) else 0.0
                            state         = "NEUTRAL"
                            broken_level  = np.nan
                            broken_ltype  = ""
                            break_bar_idx = -1
                            continue

                # Failed retest: price closes decisively below the broken level
                if row["close"] < broken_level - tolerance:
                    state = "NEUTRAL"
                    broken_level = np.nan
                    broken_ltype = ""
                    break_bar_idx = -1

            elif state == "WATCHING_SHORT":
                in_zone = (row["high"] >= broken_level - tolerance) and \
                          (row["close"] <= broken_level + tolerance)

                if in_zone and in_session:
                    candle_body   = row["open"] - row["close"]
                    bearish_body  = candle_body > 0
                    close_below   = row["close"] < broken_level
                    ema_ok        = row["close"] < row["ema20"]
                    adx_ok        = row["adx"] > _level_adx_min(broken_ltype, adx_min)
                    rsi_ok        = (settings.BRT_RSI_SHORT_MIN < row["rsi"] < settings.BRT_RSI_SHORT_MAX)
                    # Sweep: wick spiked above the level, close dropped back below it
                    sweep_ok      = (not settings.BRT_REQUIRE_SWEEP or
                                     (row["high"] > broken_level and row["close"] < broken_level))
                    # VSA: close must be in the lower half of the bar's high-low range
                    bar_range     = row["high"] - row["low"]
                    vsa_close_ok  = (not settings.BRT_VSA_CLOSE_POSITION or
                                     bar_range <= 0 or
                                     (row["high"] - row["close"]) / bar_range >= 0.5)
                    # VSA no-supply check: retest candle must not be a "no supply" bar
                    retest_vol    = float(row["volume"]) if "volume" in df.columns else 0.0
                    retest_vol_ma = float(row["vol_ma"]) if "vol_ma" in df.columns else 0.0
                    vsa_vol_ok    = (not settings.BRT_VSA_NO_DEMAND_CHECK or
                                     retest_vol_ma <= 0 or
                                     retest_vol >= settings.BRT_VSA_MIN_VOLUME_RATIO * retest_vol_ma)

                    if bearish_body and close_below and ema_ok and adx_ok and rsi_ok and sweep_ok and vsa_close_ok and vsa_vol_ok:
                        sl_candle = row["high"] + sl_buffer * atr
                        sl_level  = broken_level + sl_buffer * atr
                        sl        = max(sl_candle, sl_level)
                        risk      = sl - row["close"]
                        if risk > 0:
                            signals[i]      = -1
                            stop_losses[i]  = round(sl, 2)
                            take_profits[i] = round(row["close"] - tp_rr * risk, 2)
                            retest_arr[i]   = broken_level
                            level_types[i]  = broken_ltype
                            # Record whether a sweep occurred (wick above level, close below)
                            sweep_flags[i]  = 1.0 if (row["high"] > broken_level and row["close"] < broken_level) else 0.0
                            state         = "NEUTRAL"
                            broken_level  = np.nan
                            broken_ltype  = ""
                            break_bar_idx = -1
                            continue

                if row["close"] > broken_level + tolerance:
                    state = "NEUTRAL"
                    broken_level = np.nan
                    broken_ltype = ""
                    break_bar_idx = -1

        # ── State: NEUTRAL — scan for fresh breaks ────────────────────
        if state == "NEUTRAL" and in_session:
            levels = []

            # VWAP (primary — highest volume level of the day)
            if "vwap" in df.columns and pd.notna(row["vwap"]):
                vwap_val = float(row["vwap"])
                levels.append(("VWAP", vwap_val, "long"))
                if not long_only:
                    levels.append(("VWAP", vwap_val, "short"))

            # PDH / PDL (secondary institutional levels)
            pdh = row.get("pdh") if hasattr(row, "get") else row["pdh"] if "pdh" in df.columns else np.nan
            pdl = row.get("pdl") if hasattr(row, "get") else row["pdl"] if "pdl" in df.columns else np.nan

            if pd.notna(pdh):
                levels.append(("PDH", float(pdh), "long"))
            if pd.notna(pdl) and not long_only:
                levels.append(("PDL", float(pdl), "short"))

            # Opening Range High/Low (key intraday breakout levels)
            if "orh" in df.columns and pd.notna(row.get("orh")):
                levels.append(("ORH", float(row["orh"]), "long"))
            if "orl" in df.columns and pd.notna(row.get("orl")) and not long_only:
                levels.append(("ORL", float(row["orl"]), "short"))

            # Prior-session Volume Profile levels (institutional fair value)
            # POC = highest-volume price level; VAH/VAL = 70% value area boundaries
            # Priority: after ORH/ORL, before swing — well-validated institutional S/R
            if "prior_poc" in df.columns and pd.notna(row.get("prior_poc")):
                levels.append(("VP_POC", float(row["prior_poc"]), "long"))
                if not long_only:
                    levels.append(("VP_POC", float(row["prior_poc"]), "short"))
            if "prior_vah" in df.columns and pd.notna(row.get("prior_vah")):
                levels.append(("VP_VAH", float(row["prior_vah"]), "long"))
            if "prior_val" in df.columns and pd.notna(row.get("prior_val")) and not long_only:
                levels.append(("VP_VAL", float(row["prior_val"]), "short"))

            # Equal Highs/Lows — NOT used as break/retest entry levels.
            # EQH/EQL are SMC liquidity pools (stop clusters). They are TARGETS
            # for stop-hunt runs, not reliable S/R zones to trade from.
            # Conceptually: price tends to run TO EQH/EQL to grab stops, then reverse.
            # Using them as break/retest entries puts you on the wrong side of that move.
            # They remain in the DataFrame (eqh, eql columns) for use as exit targets
            # and in the dashboard — just not eligible for entry signal generation.
            # Research: Osler 2005 (stop cascades), ResearchGate 2024 (PDH/PDL sweeps).

            # FVG levels — Fair Value Gap boundaries as S/R zones (lowest priority)
            # Research: >60% of FVGs NEVER fill (Edgeful); use as S/R, not fill targets.
            # Extra ADX filter applied at confirmation (see _level_adx_min for FVG delta).
            if "fvg_bull_low" in df.columns and pd.notna(row.get("fvg_bull_low")):
                levels.append(("FVG", float(row["fvg_bull_low"]), "long"))
            if "fvg_bear_high" in df.columns and pd.notna(row.get("fvg_bear_high")) and not long_only:
                levels.append(("FVG", float(row["fvg_bear_high"]), "short"))

            # Swing levels (tertiary)
            if "swing_hi" in df.columns and pd.notna(row["swing_hi"]):
                levels.append(("SWING", float(row["swing_hi"]), "long"))
            if "swing_lo" in df.columns and pd.notna(row["swing_lo"]) and not long_only:
                levels.append(("SWING", float(row["swing_lo"]), "short"))

            # Break candle body filter — regime-adaptive threshold
            break_body_long  = (row["close"] - row["open"]) >= break_body_min * atr
            break_body_short = (row["open"] - row["close"]) >= break_body_min * atr

            for ltype, level, direction in levels:
                if direction == "long":
                    if row["close"] > level + buf and vol_ok and break_body_long:
                        state         = "WATCHING_LONG"
                        broken_level  = level
                        broken_ltype  = ltype
                        break_bar_idx = i
                        break  # take highest-priority level only
                else:
                    if row["close"] < level - buf and vol_ok and break_body_short:
                        state         = "WATCHING_SHORT"
                        broken_level  = level
                        broken_ltype  = ltype
                        break_bar_idx = i
                        break

    return signals, stop_losses, take_profits, retest_arr, level_types, sweep_flags


# ─────────────────────────────────────────────────────────────────────────────
# Public: prepare_break_retest
# ─────────────────────────────────────────────────────────────────────────────

def prepare_break_retest(df: pd.DataFrame, long_only: bool = True,
                         regime_params: dict | None = None) -> pd.DataFrame:
    """
    Prepare 15-minute OHLCV data for the Break & Retest strategy.

    Adds columns:
        vwap          — Intraday VWAP (resets daily) — primary level
        ema20         — EMA(20) for trend alignment
        atr           — ATR(14) for level tolerance and stop sizing
        adx           — ADX(14) for trend strength filter
        rsi           — RSI(14) for momentum filter
        vol_ma        — 20-bar volume moving average
        pdh / pdl     — Previous day high / low
        swing_hi / swing_lo — Rolling N-bar swing levels
        signal        — 1 (long), -1 (short), 0 (flat)
        stop_loss     — Hard stop price
        take_profit   — Fixed R:R take profit price
        retest_level  — The level being retested at entry
        level_type    — 'VWAP', 'PDH', 'PDL', 'ORH', 'ORL', 'VP_POC', 'VP_VAH', 'VP_VAL', 'SWING'
        prior_poc / prior_vah / prior_val — Prior-session Volume Profile levels

    Args:
        df            : OHLCV DataFrame with DatetimeIndex
        long_only     : If True, only long setups are generated (MES default)
        regime_params : Adaptive param overrides from RegimeEngine (None = use settings defaults)
    """
    df = df.copy()

    # ── VWAP (primary level — resets daily) ──────────────────────────────
    df["vwap"] = _calc_vwap(df)

    # ── Indicators ───────────────────────────────────────────────────────
    df["ema20"] = ta.trend.ema_indicator(df["close"], window=settings.BRT_EMA_PERIOD)

    atr_ind = ta.volatility.AverageTrueRange(
        df["high"], df["low"], df["close"], window=settings.BRT_ATR_PERIOD
    )
    df["atr"] = atr_ind.average_true_range()

    adx_ind = ta.trend.ADXIndicator(
        df["high"], df["low"], df["close"], window=settings.BRT_ATR_PERIOD
    )
    df["adx"] = adx_ind.adx()

    df["rsi"] = ta.momentum.RSIIndicator(df["close"], window=settings.BRT_RSI_PERIOD).rsi()

    df["vol_ma"] = df["volume"].rolling(20).mean()

    # ── Level Calculations ────────────────────────────────────────────────
    pdh_arr, pdl_arr = _calc_pdh_pdl(df)
    df["pdh"] = pdh_arr
    df["pdl"] = pdl_arr

    orh_arr, orl_arr = _calc_opening_range(df)
    df["orh"] = orh_arr
    df["orl"] = orl_arr

    swing_n = settings.BRT_SWING_WINDOW
    # Shift by 1 to avoid lookahead: only use levels from previous bars
    df["swing_hi"] = df["high"].shift(1).rolling(swing_n).max()
    df["swing_lo"] = df["low"].shift(1).rolling(swing_n).min()

    # ── Prior-session Volume Profile levels (institutional S/R) ───────────
    # Adds prior_poc, prior_vah, prior_val — no lookahead (uses previous session)
    # Research: POC/VAH/VAL from prior session = highest-conviction intraday S/R.
    # Inserted between ORH/ORL and SWING in the level priority order.
    try:
        df = add_session_vp(df)
    except Exception as e:
        logger.warning(f"Volume Profile calculation failed (non-fatal): {e}")
        for col in ("prior_poc", "prior_vah", "prior_val"):
            if col not in df.columns:
                df[col] = np.nan

    # ── Equal Highs/Lows (SMC liquidity pools) ───────────────────────────
    # Research: Osler 2005 + ResearchGate 2024 — stop clusters at equal H/L
    # produce statistically validated reversal tendencies after sweeps.
    try:
        df = add_equal_highs_lows(df)
    except Exception as e:
        logger.warning(f"EQH/EQL calculation failed (non-fatal): {e}")
        for col in ("eqh", "eql"):
            if col not in df.columns:
                df[col] = np.nan

    # ── Fair Value Gaps (FVG zones) ───────────────────────────────────────
    # Research: >60% of FVGs never fill (Edgeful). Used as S/R zones only.
    try:
        df = add_fvg_levels(df)
    except Exception as e:
        logger.warning(f"FVG calculation failed (non-fatal): {e}")
        for col in ("fvg_bull_low", "fvg_bull_high", "fvg_bear_low", "fvg_bear_high"):
            if col not in df.columns:
                df[col] = np.nan

    # ── Drop warmup rows ──────────────────────────────────────────────────
    df.dropna(subset=["ema20", "atr", "adx", "rsi"], inplace=True)

    # ── Break & Retest Signal Detection ──────────────────────────────────
    signals, stop_losses, take_profits, retest_arr, level_types, sweep_flags = _detect_brt_signals(
        df, long_only=long_only, regime_params=regime_params
    )

    df["signal"]           = signals
    df["stop_loss"]        = stop_losses
    df["take_profit"]      = take_profits
    df["retest_level"]     = retest_arr
    df["level_type"]       = level_types
    df["liquidity_sweep"]  = sweep_flags  # 1 = sweep confirmed at entry bar

    n_long  = int((df["signal"] == 1).sum())
    n_short = int((df["signal"] == -1).sum())
    logger.info(
        f"Break & Retest signals — LONG: {n_long}  SHORT: {n_short}  "
        f"(over {len(df)} bars)"
    )
    return df


# ─────────────────────────────────────────────────────────────────────────────
# Public: latest signal accessor
# ─────────────────────────────────────────────────────────────────────────────

def get_latest_brt_signal(df: pd.DataFrame) -> dict:
    """Return the most recent Break & Retest signal dict."""
    last = df.iloc[-1]
    return {
        "signal":          int(last["signal"]),
        "close":           float(last["close"]),
        "ema20":           float(last["ema20"]),
        "atr":             float(last["atr"]),
        "adx":             float(last["adx"]),
        "rsi":             float(last["rsi"]),
        "vwap":            float(last["vwap"])    if pd.notna(last.get("vwap"))    else None,
        "pdh":             float(last["pdh"])     if pd.notna(last.get("pdh"))     else None,
        "pdl":             float(last["pdl"])     if pd.notna(last.get("pdl"))     else None,
        "swing_hi":        float(last["swing_hi"]) if pd.notna(last.get("swing_hi")) else None,
        "swing_lo":        float(last["swing_lo"]) if pd.notna(last.get("swing_lo")) else None,
        "stop_loss":       float(last["stop_loss"])   if pd.notna(last["stop_loss"])   else None,
        "take_profit":     float(last["take_profit"]) if pd.notna(last["take_profit"]) else None,
        "retest_level":    float(last["retest_level"]) if pd.notna(last["retest_level"]) else None,
        "level_type":      str(last["level_type"]),
        "liquidity_sweep": int(last.get("liquidity_sweep", 0)),
        "prior_poc":       float(last["prior_poc"]) if pd.notna(last.get("prior_poc")) else None,
        "prior_vah":       float(last["prior_vah"]) if pd.notna(last.get("prior_vah")) else None,
        "prior_val":       float(last["prior_val"]) if pd.notna(last.get("prior_val")) else None,
        "eqh":             float(last["eqh"]) if pd.notna(last.get("eqh")) else None,
        "eql":             float(last["eql"]) if pd.notna(last.get("eql")) else None,
        "fvg_bull_low":    float(last["fvg_bull_low"])  if pd.notna(last.get("fvg_bull_low"))  else None,
        "fvg_bull_high":   float(last["fvg_bull_high"]) if pd.notna(last.get("fvg_bull_high")) else None,
        "fvg_bear_low":    float(last["fvg_bear_low"])  if pd.notna(last.get("fvg_bear_low"))  else None,
        "fvg_bear_high":   float(last["fvg_bear_high"]) if pd.notna(last.get("fvg_bear_high")) else None,
    }
