"""
strategy/momentum_swing.py

Momentum Swing Trading Strategy — US Equities (Daily Timeframe)

STRATEGY OVERVIEW
─────────────────
Momentum-based swing system targeting breakout and continuation setups
on liquid US stocks. Holds positions several days to a few weeks.

TWO SETUPS
──────────
A) BREAKOUT — stock compresses into a tight range then breaks above resistance
   on elevated volume. Enter on close confirmation above resistance.

B) PULLBACK — stock is in a clear uptrend, pulls back to the 20 EMA or prior
   support, shows a rejection/bounce candle. Enter on confirmation of bounce.

TREND FILTER (required for both setups)
   • Price > EMA20 AND price > EMA50
   • Both EMAs sloping upward (EMA20[0] > EMA20[5] and EMA50[0] > EMA50[5])

RISK MANAGEMENT
   • Risk per trade: SWING_RISK_PER_TRADE (default 0.75% of account)
   • Stop:   below consolidation range (breakout) or below pullback low
   • Target: SWING_TP_R1 (partial, default 1.5R), SWING_TP_R2 (runner, default 3R)
   • Trailing stop: below higher lows or below EMA20

DATA
   • Daily OHLCV via yfinance (default) or any source that returns a standard df
   • Min avg volume: SWING_MIN_AVG_VOLUME (default 1,000,000 shares)
   • Lookback: SWING_LOOKBACK_DAYS (default 90 days for indicator warmup)

CONFIG (config/settings.py — all overridable via .env)
   SWING_ENABLED            = false (disabled until ready)
   SWING_UNIVERSE           = AAPL,MSFT,NVDA,META,GOOGL,AMZN,AMD,TSM,AVGO,CRM,...
   SWING_LOOKBACK_DAYS      = 90
   SWING_EMA_FAST           = 20
   SWING_EMA_SLOW           = 50
   SWING_BREAKOUT_BARS      = 10   (consolidation window — last N bars define range)
   SWING_CONSOLIDATION_ATR  = 0.75 (max range/ATR ratio to qualify as "tight")
   SWING_VOLUME_MULT        = 1.5  (entry volume must be N× avg volume)
   SWING_MIN_AVG_VOLUME     = 1_000_000
   SWING_PULLBACK_EMA_TOL   = 0.02 (price within 2% of EMA20 to qualify as pullback)
   SWING_RISK_PER_TRADE     = 0.0075
   SWING_TP_R1              = 1.5  (first partial target — 1.5× risk)
   SWING_TP_R2              = 3.0  (runner target — 3× risk)
"""

import logging
import numpy as np
import pandas as pd

from strategy.base import AbstractStrategy
from strategy.registry import register
from config import settings

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Setup type constants
# ─────────────────────────────────────────────────────────────────────────────
SETUP_BREAKOUT = "BREAKOUT"
SETUP_PULLBACK = "PULLBACK"


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _ema(series: pd.Series, period: int) -> pd.Series:
    """Exponential moving average."""
    return series.ewm(span=period, adjust=False).mean()


def _atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Average True Range."""
    high, low, close = df["high"], df["low"], df["close"]
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low  - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.rolling(period).mean()


def _slope_up(series: pd.Series, lookback: int = 5) -> bool:
    """True if the last value is higher than the value N periods ago."""
    if len(series) < lookback + 1:
        return False
    return bool(series.iloc[-1] > series.iloc[-1 - lookback])


def _consolidation(df: pd.DataFrame, bars: int, atr_mult: float) -> tuple[float, float, bool]:
    """
    Check if the last N bars form a tight consolidation range.

    Returns (resistance, support, is_tight) where:
        resistance = max high of the window
        support    = min low of the window
        is_tight   = True if (resistance - support) <= atr_mult × ATR
    """
    window = df.tail(bars)
    resistance = float(window["high"].max())
    support    = float(window["low"].min())
    current_atr = float(df["atr"].iloc[-1]) if "atr" in df.columns else (resistance - support)
    is_tight = (resistance - support) <= atr_mult * current_atr
    return resistance, support, is_tight


def _avg_volume(df: pd.DataFrame, bars: int = 20) -> float:
    """Average volume over the last N bars."""
    return float(df["volume"].tail(bars).mean())


def _next_resistance(df: pd.DataFrame, entry: float, atr: float,
                     lookback: int = 60, min_r: float = 1.0, max_r: float = 4.0,
                     risk: float = 0.0) -> float | None:
    """
    Find the nearest prior swing high above entry that sits between min_r and max_r
    multiples of risk away. Used to set context-aware TP1.

    A swing high is a bar whose high is higher than the two bars on each side.
    Returns the price level, or None if no clean level is found in range.
    """
    if risk <= 0:
        return None
    window = df.tail(lookback)
    highs = window["high"].values
    candidates = []
    for i in range(2, len(highs) - 2):
        if highs[i] > highs[i-1] and highs[i] > highs[i-2] and \
           highs[i] > highs[i+1] and highs[i] > highs[i+2]:
            level = float(highs[i])
            r_multiple = (level - entry) / risk
            if min_r <= r_multiple <= max_r:
                candidates.append(level)
    return min(candidates) if candidates else None


# ─────────────────────────────────────────────────────────────────────────────
# Dynamic Universe — S&P 500 + popular momentum names
# ─────────────────────────────────────────────────────────────────────────────

_universe_cache: list | None = None
_universe_cache_ts: float = 0

def _get_scan_universe() -> list[str]:
    """
    Fetch a broad, liquid universe for the screener.
    Pulls S&P 500 constituents from Wikipedia + adds popular momentum/growth
    names that may not be in the index. Cached for 24 hours.
    """
    import time as _time
    global _universe_cache, _universe_cache_ts

    if _universe_cache and (_time.time() - _universe_cache_ts) < 86400:
        return _universe_cache

    symbols = set()

    # 1. S&P 500 from Wikipedia
    try:
        sp500 = pd.read_html(
            "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies",
            attrs={"id": "constituents"},
        )[0]
        tickers = sp500["Symbol"].str.replace(".", "-", regex=False).tolist()
        symbols.update(tickers)
        logger.info(f"[SWING universe] Loaded {len(tickers)} S&P 500 tickers")
    except Exception as e:
        logger.warning(f"[SWING universe] Wikipedia S&P 500 fetch failed: {e}")

    # 2. Extra popular/momentum names not always in S&P 500
    _EXTRA = [
        "COIN", "HOOD", "MSTR", "RBLX", "U", "IONQ", "RGTI", "QUBT",
        "PLTR", "APP", "RDDT", "ARM", "SMCI", "CELH", "DUOL", "GRAB",
        "SOFI", "AFRM", "UPST", "SE", "MELI", "NU", "SHOP", "SNOW",
        "MDB", "DDOG", "NET", "ZS", "CRWD", "PANW",
    ]
    symbols.update(_EXTRA)

    # 3. Fallback if Wikipedia failed
    if len(symbols) < 50:
        logger.warning("[SWING universe] Using fallback hardcoded universe")
        _FALLBACK = [
            "AAPL", "MSFT", "NVDA", "META", "GOOGL", "AMZN", "AMD", "TSM",
            "AVGO", "CRM", "ORCL", "NFLX", "TSLA", "JPM", "V", "MA", "UNH",
            "LLY", "JNJ", "PG", "HD", "COST", "ABBV", "MRK", "PEP", "KO",
            "ADBE", "INTC", "QCOM", "TXN", "AMAT", "LRCX", "KLAC", "MRVL",
            "GS", "MS", "BAC", "WFC", "C", "BLK", "SCHW", "AXP",
            "XOM", "CVX", "COP", "SLB", "CAT", "DE", "GE", "RTX",
            "DIS", "CMCSA", "NFLX", "ABNB", "UBER", "BKNG",
            "COIN", "HOOD", "SQ", "PYPL", "PLTR", "MSTR",
        ]
        symbols.update(_FALLBACK)

    result = sorted(symbols)
    _universe_cache = result
    _universe_cache_ts = _time.time()
    logger.info(f"[SWING universe] Total scan universe: {len(result)} stocks")
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Strategy
# ─────────────────────────────────────────────────────────────────────────────

@register
class MomentumSwingStrategy(AbstractStrategy):
    """
    Sean's Momentum Swing — liquid US equities, daily timeframe.
    Breakout and pullback continuation setups with strict trend filter.
    """

    name              = "SWING"
    timeframe_minutes = 1440   # daily bars
    priority          = 60     # lower priority than BRT (which is 50)
    strategy_type     = "daily"  # holds 5-30 days — overnight gap risk

    @property
    def symbols(self) -> list:
        """Universe pulled from settings — configurable via .env."""
        universe = getattr(settings, "SWING_UNIVERSE",
                           "AAPL,MSFT,NVDA,META,GOOGL,AMZN,AMD,TSM,AVGO,CRM,"
                           "ORCL,NFLX,SHOP,PANW,CRWD,SNOW,MDB,DDOG,ZS,AXON")
        return [s.strip() for s in universe.split(",") if s.strip()]

    # ── is_eligible ────────────────────────────────────────────────────────────
    def is_eligible(
        self,
        symbol: str,
        regime: str,
        session_hour: int,
        fundamentals: dict,
    ) -> bool:
        """
        Run the swing screener after market close (16:00–23:59 ET) or
        pre-market (0:00–9:29 ET). Signals are daily, so no intraday churn.

        Blocked in extreme volatility (VIX > 35) — momentum setups fail
        in panic markets.

        Fundamental gate: blocks trades on stocks with weak fundamentals,
        imminent earnings, or active analyst downgrades.
        """
        # Only evaluate during off-hours (daily signals, not intraday)
        intraday = 9 <= session_hour <= 15
        if intraday:
            return False

        # Hard block if VIX is in panic territory
        # (One-shot override can bypass this for live test runs)
        vix = fundamentals.get("vix") or 0
        if vix > 35:
            try:
                from strategy import swing_override
                if swing_override.is_skip_vix():
                    logger.warning(
                        f"[SWING] {symbol} — VIX={vix:.1f} > 35 but skip_vix_cap override active"
                    )
                else:
                    logger.debug(f"[SWING] {symbol} — blocked: VIX={vix:.1f} > 35")
                    return False
            except ImportError:
                logger.debug(f"[SWING] {symbol} — blocked: VIX={vix:.1f} > 35")
                return False

        # Block in NO_TRADE regime
        if regime == "NO_TRADE":
            return False

        # ── Fundamental gate (equity-specific) ────────────────────────────────
        if getattr(settings, "FUNDAMENTAL_GATE_ENABLED", True):
            try:
                from data.equity_fundamentals import get_fundamentals_cached, get_fundamental_gate
                fund = get_fundamentals_cached(symbol)
                allowed, reason = get_fundamental_gate(fund)
                if not allowed:
                    logger.info(f"[SWING] {symbol} — FUNDAMENTAL GATE BLOCKED: {reason}")
                    try:
                        from data.trade_log import log_event
                        log_event(
                            f"Fundamental gate blocked {symbol}",
                            "WARN",
                            reason,
                        )
                    except Exception:
                        pass
                    return False
                else:
                    logger.debug(f"[SWING] {symbol} — {reason}")
            except ImportError:
                pass  # equity_fundamentals module not available — proceed without gate

        return True

    # ── prepare ────────────────────────────────────────────────────────────────
    def prepare(self, df: pd.DataFrame, **kwargs) -> pd.DataFrame:
        """
        Enrich a daily OHLCV DataFrame with all indicators and signal columns.

        Returns the enriched DataFrame. Does not modify in place.
        """
        df = df.copy()

        ema_fast = getattr(settings, "SWING_EMA_FAST", 20)
        ema_slow = getattr(settings, "SWING_EMA_SLOW", 50)
        bb_bars  = getattr(settings, "SWING_BREAKOUT_BARS", 10)
        consol_atr_mult = getattr(settings, "SWING_CONSOLIDATION_ATR", 0.75)
        vol_mult = getattr(settings, "SWING_VOLUME_MULT", 1.5)
        min_avg_vol = getattr(settings, "SWING_MIN_AVG_VOLUME", 1_000_000)
        pullback_tol = getattr(settings, "SWING_PULLBACK_EMA_TOL", 0.02)
        tp_r1 = getattr(settings, "SWING_TP_R1", 1.5)
        tp_r2 = getattr(settings, "SWING_TP_R2", 3.0)

        # ── Indicators ─────────────────────────────────────────────────────────
        df["ema20"] = _ema(df["close"], ema_fast)
        df["ema50"] = _ema(df["close"], ema_slow)
        df["atr"]   = _atr(df)
        df["avg_vol_20"] = df["volume"].rolling(20).mean()

        # RSI (14) for overbought/oversold context
        delta = df["close"].diff()
        gain  = delta.clip(lower=0).rolling(14).mean()
        loss  = (-delta.clip(upper=0)).rolling(14).mean()
        rs    = gain / loss.replace(0, np.nan)
        df["rsi"] = 100 - (100 / (1 + rs))

        # Relative strength vs SPY — higher = outperforming market
        # (Populated by the orchestrator/data layer if available, else NaN)
        if "spy_close" in df.columns:
            df["rel_strength"] = df["close"] / df["spy_close"]
        else:
            df["rel_strength"] = np.nan

        # ── Signal columns (initialized flat) ──────────────────────────────────
        df["signal"]     = 0
        df["stop_loss"]  = np.nan
        df["take_profit"] = np.nan
        df["setup_type"] = ""

        if len(df) < max(ema_slow, bb_bars) + 5:
            # Not enough data yet
            return df

        # ── Trend filter ───────────────────────────────────────────────────────
        close = df["close"].iloc[-1]
        ema20 = df["ema20"].iloc[-1]
        ema50 = df["ema50"].iloc[-1]

        trend_ok = (
            close > ema20
            and close > ema50
            and _slope_up(df["ema20"], lookback=5)
            and _slope_up(df["ema50"], lookback=5)
        )

        # ── Volume filter ──────────────────────────────────────────────────────
        avg_vol = _avg_volume(df)
        entry_vol = float(df["volume"].iloc[-1])
        vol_ok = (
            avg_vol >= min_avg_vol
            and entry_vol >= vol_mult * avg_vol
        )

        if not trend_ok:
            # No signal — trend filter failed
            return df

        current_atr = float(df["atr"].iloc[-1])

        # ── SETUP A: BREAKOUT ─────────────────────────────────────────────────
        # Consolidation in last N bars then close above resistance with volume
        resistance, support, is_tight = _consolidation(
            df.iloc[:-1],  # exclude current bar to measure range before breakout
            bars=bb_bars,
            atr_mult=consol_atr_mult,
        )
        prev_bar = df.iloc[-2]  # bar before today
        today    = df.iloc[-1]

        breakout_signal = (
            is_tight
            and vol_ok
            and float(today["close"]) > resistance
            and float(prev_bar["close"]) <= resistance  # first close above
        )

        if breakout_signal:
            stop  = support - 0.25 * current_atr   # below consolidation base
            risk  = float(today["close"]) - stop
            if risk <= 0:
                return df  # invalid setup — stop above entry
            # Use nearest prior swing high as TP1 if it falls in 1.5–4R; else 2R
            # (breakouts tend to run — prefer 2R default over 1.5R)
            key_level = _next_resistance(df.iloc[:-1], float(today["close"]),
                                         current_atr, risk=risk, min_r=1.5, max_r=4.0)
            if key_level:
                tp1   = key_level
                tp1_r = round((tp1 - float(today["close"])) / risk, 2)
            else:
                tp1_r = 2.0
                tp1   = float(today["close"]) + tp1_r * risk
            df.iloc[-1, df.columns.get_loc("signal")]      = 1
            df.iloc[-1, df.columns.get_loc("stop_loss")]   = round(stop, 4)
            df.iloc[-1, df.columns.get_loc("take_profit")]  = round(tp1, 4)
            df.iloc[-1, df.columns.get_loc("setup_type")]  = SETUP_BREAKOUT
            if "tp1_r" not in df.columns:
                df["tp1_r"] = np.nan
            df.iloc[-1, df.columns.get_loc("tp1_r")] = tp1_r
            return df

        # ── SETUP B: PULLBACK CONTINUATION ───────────────────────────────────
        # Strong uptrend, price pulls back within pullback_tol of EMA20,
        # then today's candle shows a bullish rejection (close > open, close > prior close)
        price_near_ema20 = abs(float(today["close"]) - ema20) / ema20 <= pullback_tol
        bounce_candle = (
            float(today["close"]) > float(today["open"])   # bullish candle
            and float(today["close"]) > float(prev_bar["close"])  # closes above prior
            and float(today["low"]) < float(prev_bar["low"])      # tagged lower, rejected
        )
        pullback_volume_ok = entry_vol >= 1.2 * avg_vol  # slightly lower vol threshold

        pullback_signal = (
            price_near_ema20
            and bounce_candle
            and pullback_volume_ok
        )

        if pullback_signal:
            stop  = float(today["low"]) - 0.1 * current_atr   # below pullback low
            risk  = float(today["close"]) - stop
            if risk <= 0:
                return df  # invalid setup — stop above entry
            # Pullback: look for prior high as TP1 ceiling (1.0–2.5R range)
            key_level = _next_resistance(df.iloc[:-1], float(today["close"]),
                                         current_atr, risk=risk, min_r=1.0, max_r=2.5)
            if key_level:
                tp1   = key_level
                tp1_r = round((tp1 - float(today["close"])) / risk, 2)
            else:
                tp1_r = tp_r1  # fallback to setting default (1.5R)
                tp1   = float(today["close"]) + tp1_r * risk
            df.iloc[-1, df.columns.get_loc("signal")]      = 1
            df.iloc[-1, df.columns.get_loc("stop_loss")]   = round(stop, 4)
            df.iloc[-1, df.columns.get_loc("take_profit")]  = round(tp1, 4)
            df.iloc[-1, df.columns.get_loc("setup_type")]  = SETUP_PULLBACK
            if "tp1_r" not in df.columns:
                df["tp1_r"] = np.nan
            df.iloc[-1, df.columns.get_loc("tp1_r")] = tp1_r

        return df

    # ── get_signal ─────────────────────────────────────────────────────────────
    def get_signal(self, df: pd.DataFrame, **kwargs) -> dict:
        """
        Extract the latest signal from a prepared DataFrame.

        Returns the standard signal dict expected by the orchestrator.
        """
        if df is None or len(df) == 0:
            return self._flat()

        last = df.iloc[-1]
        sig  = int(last.get("signal", 0))

        if sig == 0:
            return self._flat(close=float(last.get("close", 0)))

        close      = float(last["close"])
        stop_loss  = float(last["stop_loss"])
        take_profit = float(last["take_profit"])
        setup_type = str(last.get("setup_type", ""))
        risk       = close - stop_loss
        tp2        = close + getattr(settings, "SWING_TP_R2", 3.0) * risk

        logger.info(
            f"[SWING] {setup_type} signal — "
            f"close={close:.2f} stop={stop_loss:.2f} tp1={take_profit:.2f} tp2={tp2:.2f} "
            f"risk={risk:.2f} R:R={(take_profit - close) / risk if risk else 0:.2f}"
        )

        return {
            "signal":      1,
            "close":       close,
            "stop_loss":   stop_loss,
            "take_profit": take_profit,
            "take_profit_2": round(tp2, 4),
            "setup_type":  setup_type,
            "ema20":       float(last.get("ema20", 0)),
            "ema50":       float(last.get("ema50", 0)),
            "atr":         float(last.get("atr", 0)),
            "rsi":         float(last.get("rsi", 0)),
            "avg_vol":     float(last.get("avg_vol_20", 0)),
            "entry_vol":   float(last.get("volume", 0)),
        }

    # ── helpers ────────────────────────────────────────────────────────────────
    @staticmethod
    def _flat(close: float = 0.0) -> dict:
        return {
            "signal":      0,
            "close":       close,
            "stop_loss":   None,
            "take_profit": None,
        }

    # ── Screener: scan full universe, return ranked setups ─────────────────────
    def scan_universe(self) -> list[dict]:
        """
        Watchlist-mode screener: always returns stocks across 10 setup categories.

        Categories (inspired by Minervini, Weinstein, IBD, O'Neil, Carter):
          VCP            — Volatility Contraction Pattern (Minervini): 3+ contracting
                           price swings with declining volume. Coiled spring setup.
          BREAKOUT       — Close above N-bar consolidation resistance on vol ≥ 1.5×.
          EMA20_BOUNCE   — Pullback to 20-day EMA in uptrend, bullish rejection candle.
          EMA50_BOUNCE   — Deeper pullback to 50-day EMA, hold + bullish candle.
          RS_LEADER      — 63-day relative strength vs SPY in top quartile. Leads in bull.
          ACCUMULATION   — 3+ of last 5 days: volume > 1.3× avg + price up. Institutions.
          SQUEEZE        — Bollinger Bands inside Keltner Channels (John Carter).
                           Low volatility pre-expansion. Directional bias TBD.
          HIGH_TIGHT_FLAG— 100%+ gain in ≤8 weeks, then ≤25% pullback. IBD power play.
          FLAT_BASE      — Price range < 15% over 5+ weeks, volume drying. Base on base.
          NEAR_52W_HIGH  — Within 15% of 52-week high and above both EMAs. Leadership.

        Bot does NOT have to trade these — this is a watchlist for research.
        Scored 0-100. Top 25 returned. Active BREAKOUT/PULLBACK signals shown first.
        """
        import yfinance as yf
        from datetime import datetime, timedelta

        # ── Dynamic broad universe: S&P 500 + popular momentum names ──────────
        universe = _get_scan_universe()
        logger.info(f"[SWING screener] Scanning {len(universe)} stocks")

        end   = datetime.utcnow().strftime("%Y-%m-%d")
        start = (datetime.utcnow() - timedelta(days=220)).strftime("%Y-%m-%d")

        # ── Batch download all tickers at once (much faster than 1-by-1) ──────
        all_tickers = universe + ["SPY"]
        batch_raw = yf.download(
            all_tickers, start=start, end=end,
            interval="1d", progress=False, auto_adjust=True,
            threads=True, group_by="ticker",
        )

        # Extract SPY for relative strength
        spy_ret_63d = None
        try:
            spy_df = batch_raw["SPY"].dropna(how="all") if "SPY" in batch_raw.columns.get_level_values(0) else None
            if spy_df is not None and len(spy_df) >= 63:
                spy_close = spy_df["Close"].values
                spy_ret_63d = float(spy_close[-1] / spy_close[-63] - 1)
        except Exception:
            pass

        results = []
        _fallback_pool = []   # stocks that didn't match any category
        for symbol in universe:
            try:
                # Pull this ticker's data from the batch result
                try:
                    raw = batch_raw[symbol].dropna(how="all").copy()
                except (KeyError, TypeError):
                    continue
                if raw is None or len(raw) < 60:
                    continue
                raw.columns = [c.lower() for c in raw.columns]

                # Core indicator prep (reuse prepare() for trade signals)
                df = self.prepare(raw)
                if df is None or len(df) < 50:
                    continue

                last     = df.iloc[-1]
                prev     = df.iloc[-2]
                close    = float(last["close"])
                ema20    = float(last["ema20"])
                ema50    = float(last["ema50"])
                atr      = float(last["atr"])
                rsi      = float(last.get("rsi", 50))
                vol_today = float(last["volume"])
                avg_vol20 = float(last.get("avg_vol_20") or df["volume"].tail(20).mean())
                vol_ratio = vol_today / max(avg_vol20, 1)

                # ── Base metrics ────────────────────────────────────────────────
                hi_52w = float(df["high"].tail(252).max())
                lo_52w = float(df["low"].tail(252).min())
                pct_from_hi = (close / hi_52w - 1) * 100
                ret_5d  = (close / float(df["close"].iloc[-5])  - 1) * 100 if len(df) >= 5  else 0
                ret_20d = (close / float(df["close"].iloc[-20]) - 1) * 100 if len(df) >= 20 else 0
                ret_63d = (close / float(df["close"].iloc[-63]) - 1) * 100 if len(df) >= 63 else 0

                above_ema20 = close > ema20
                above_ema50 = close > ema50
                ema20_slope = _slope_up(df["ema20"], 5)
                ema50_slope = _slope_up(df["ema50"], 10)
                in_uptrend  = above_ema20 and above_ema50 and ema20_slope

                # ── Detect active trade signal (existing BREAKOUT/PULLBACK logic) ─
                active_signal = int(last.get("signal", 0))
                active_setup  = str(last.get("setup_type", ""))
                trade_stop    = float(last["stop_loss"])  if active_signal else None
                trade_target  = float(last["take_profit"]) if active_signal else None

                # ── Category detectors ──────────────────────────────────────────
                categories = []
                category_notes = []

                # 1. VCP (Volatility Contraction Pattern — Minervini)
                # Three contracting price swings, each smaller than the last,
                # volume declining on each contraction, final pivot < 10% range.
                try:
                    if in_uptrend and len(df) >= 60:
                        closes_60 = df["close"].tail(60).values
                        highs_60  = df["high"].tail(60).values
                        lows_60   = df["low"].tail(60).values
                        vols_60   = df["volume"].tail(60).values
                        # Find local pivots (swing highs / swing lows)
                        pivots = []
                        for i in range(3, len(closes_60) - 3):
                            if highs_60[i] > highs_60[i-1] and highs_60[i] > highs_60[i+1]:
                                pivots.append(("H", i, highs_60[i]))
                            elif lows_60[i] < lows_60[i-1] and lows_60[i] < lows_60[i+1]:
                                pivots.append(("L", i, lows_60[i]))
                        # Need ≥3 swings, each smaller than the last
                        if len(pivots) >= 4:
                            swings = []
                            for j in range(len(pivots) - 1):
                                if pivots[j][0] != pivots[j+1][0]:
                                    swings.append(abs(pivots[j][2] - pivots[j+1][2]))
                            if len(swings) >= 3:
                                last3 = swings[-3:]
                                contracting = last3[0] > last3[1] > last3[2]
                                final_pct = last3[2] / close
                                vol_drying = vols_60[-10:].mean() < vols_60[-30:-10].mean()
                                if contracting and final_pct < 0.12 and vol_drying:
                                    categories.append("VCP")
                                    category_notes.append(
                                        f"VCP: {len(swings)} contracting swings, "
                                        f"final range {final_pct*100:.1f}%, vol drying"
                                    )
                except Exception:
                    pass

                # 2. Active BREAKOUT (from prepare() signal)
                if active_signal and active_setup == SETUP_BREAKOUT:
                    categories.append("BREAKOUT")
                    category_notes.append(
                        f"Breakout above resistance on vol ×{vol_ratio:.1f}"
                    )

                # 3. EMA20 Bounce
                try:
                    dist_ema20 = abs(close - ema20) / ema20
                    bullish_candle = (float(last["close"]) > float(last["open"]) and
                                      float(last["close"]) > float(prev["close"]) and
                                      float(last["low"])   < float(prev["low"]))
                    if in_uptrend and dist_ema20 <= 0.025 and bullish_candle:
                        categories.append("EMA20_BOUNCE")
                        category_notes.append(
                            f"Touched 20 EMA (${ema20:.2f}), bullish rejection"
                        )
                    elif (active_signal and active_setup == SETUP_PULLBACK and
                          not active_setup == SETUP_BREAKOUT):
                        categories.append("EMA20_BOUNCE")
                        category_notes.append("Pullback to EMA20 — bot signal active")
                except Exception:
                    pass

                # 4. EMA50 Bounce
                try:
                    dist_ema50 = abs(close - ema50) / ema50
                    if above_ema50 and dist_ema50 <= 0.035 and ema50_slope:
                        bullish_c = float(last["close"]) > float(last["open"])
                        if bullish_c:
                            categories.append("EMA50_BOUNCE")
                            category_notes.append(
                                f"Holding 50 EMA (${ema50:.2f}) — deeper pullback support"
                            )
                except Exception:
                    pass

                # 5. RS Leader (Relative Strength vs SPY, 63-day)
                try:
                    if spy_ret_63d is not None and len(df) >= 63:
                        rs_vs_spy = (ret_63d / 100) - spy_ret_63d
                        if rs_vs_spy > 0.10 and in_uptrend:   # outperforming SPY by 10%+
                            categories.append("RS_LEADER")
                            category_notes.append(
                                f"RS leader: +{rs_vs_spy*100:.1f}% vs SPY over 63d"
                            )
                except Exception:
                    pass

                # 6. Accumulation (volume + price rising — institutional footprint)
                try:
                    recent5 = df.tail(5)
                    accum_days = sum(
                        1 for _, row in recent5.iterrows()
                        if float(row["close"]) > float(row["open"])
                        and float(row["volume"]) > 1.3 * avg_vol20
                    )
                    if accum_days >= 3:
                        categories.append("ACCUMULATION")
                        category_notes.append(
                            f"Accumulation: {accum_days}/5 days up on elevated volume"
                        )
                except Exception:
                    pass

                # 7. Squeeze (Bollinger Bands inside Keltner Channels — John Carter)
                try:
                    if len(df) >= 20:
                        c = df["close"].tail(20)
                        h = df["high"].tail(20)
                        l = df["low"].tail(20)
                        # Bollinger Bands (20, 2)
                        bb_mid  = c.mean()
                        bb_std  = c.std()
                        bb_up   = bb_mid + 2 * bb_std
                        bb_dn   = bb_mid - 2 * bb_std
                        # Keltner (20, 1.5 × ATR)
                        kc_atr  = float(df["atr"].iloc[-1])
                        kc_up   = bb_mid + 1.5 * kc_atr
                        kc_dn   = bb_mid - 1.5 * kc_atr
                        in_squeeze = bb_up < kc_up and bb_dn > kc_dn
                        if in_squeeze:
                            categories.append("SQUEEZE")
                            category_notes.append(
                                "BB inside Keltner — volatility coil, directional move loading"
                            )
                except Exception:
                    pass

                # 8. High Tight Flag (IBD power play: 100%+ move, then ≤25% pullback)
                try:
                    if len(df) >= 40:
                        hi_8w  = float(df["high"].tail(40).max())
                        lo_pre = float(df["low"].tail(60).iloc[:20].min())
                        run_pct = (hi_8w / max(lo_pre, 0.01) - 1) * 100
                        pullback_from_hi = (hi_8w - close) / hi_8w * 100
                        if run_pct >= 80 and pullback_from_hi <= 25 and above_ema20:
                            categories.append("HIGH_TIGHT_FLAG")
                            category_notes.append(
                                f"High tight flag: +{run_pct:.0f}% run, "
                                f"only {pullback_from_hi:.1f}% off high"
                            )
                except Exception:
                    pass

                # 9. Flat Base (IBD: tight price range after advance, vol drying)
                try:
                    if len(df) >= 35 and in_uptrend:
                        base_window = df["close"].tail(35)
                        base_range  = (base_window.max() - base_window.min()) / base_window.mean()
                        base_vol    = df["volume"].tail(35).mean()
                        prior_vol   = df["volume"].tail(70).iloc[:35].mean()
                        vol_dry     = base_vol < 0.85 * prior_vol
                        # Must have advanced before base (ret_63d > 20% pre-base)
                        adv_before  = ret_63d > 20
                        if base_range < 0.14 and vol_dry and adv_before:
                            categories.append("FLAT_BASE")
                            category_notes.append(
                                f"Flat base: {base_range*100:.1f}% range, "
                                f"vol {(1-base_vol/prior_vol)*100:.0f}% below avg"
                            )
                except Exception:
                    pass

                # 10. Near 52-Week High (leadership structure)
                try:
                    if pct_from_hi > -15 and in_uptrend:
                        categories.append("NEAR_52W_HIGH")
                        category_notes.append(
                            f"Near 52w high — {pct_from_hi:.1f}% off peak, "
                            f"leadership structure"
                        )
                except Exception:
                    pass

                # 11. Oversold Bounce (works in any market regime)
                # RSI < 30, or RSI2 < 10 (mean-reversion snap-back candidate)
                try:
                    rsi2 = None
                    if len(df) >= 5:
                        delta = df["close"].diff()
                        gain2 = delta.clip(lower=0).rolling(2).mean()
                        loss2 = (-delta.clip(upper=0)).rolling(2).mean()
                        rs2 = gain2 / loss2.replace(0, 1e-9)
                        rsi2_series = 100 - 100 / (1 + rs2)
                        rsi2 = float(rsi2_series.iloc[-1])
                    if rsi < 30 or (rsi2 is not None and rsi2 < 10):
                        categories.append("OVERSOLD")
                        tag = f"RSI14={rsi:.0f}"
                        if rsi2 is not None:
                            tag += f", RSI2={rsi2:.0f}"
                        category_notes.append(
                            f"Oversold bounce candidate: {tag}"
                        )
                except Exception:
                    pass

                # 12. EMA Reclaim (price was below EMAs, now crossing back above)
                try:
                    if len(df) >= 3:
                        prev2 = df.iloc[-3]
                        was_below = (float(prev2["close"]) < float(prev2["ema20"]))
                        now_above = close > ema20
                        if was_below and now_above and vol_ratio > 1.0:
                            categories.append("EMA_RECLAIM")
                            category_notes.append(
                                f"Reclaiming 20 EMA (${ema20:.2f}) — early trend shift"
                            )
                except Exception:
                    pass

                # 13. Volume Spike (any direction — unusual institutional activity)
                try:
                    if vol_ratio >= 2.0 and avg_vol20 > 500_000:
                        categories.append("VOL_SPIKE")
                        category_notes.append(
                            f"Volume ×{vol_ratio:.1f} avg — institutional interest"
                        )
                except Exception:
                    pass

                # 14. Relative Strength (outperforming SPY even when not in uptrend)
                try:
                    if spy_ret_63d is not None and len(df) >= 63:
                        rs_vs_spy = (ret_63d / 100) - spy_ret_63d
                        if rs_vs_spy > 0.05 and not in_uptrend and above_ema50:
                            categories.append("RELATIVE_STRENGTH")
                            category_notes.append(
                                f"Holding up: +{rs_vs_spy*100:.1f}% vs SPY, "
                                f"above 50 EMA despite market weakness"
                            )
                except Exception:
                    pass

                # ── Must qualify for at least one category ──────────────────────
                if not categories:
                    # Save for fallback pool (always-show mode)
                    _fallback_pool.append({
                        "symbol": symbol, "close": round(close, 2),
                        "ema20": round(ema20, 2), "ema50": round(ema50, 2),
                        "rsi": round(rsi, 1), "vol_ratio": round(vol_ratio, 2),
                        "ret_5d": round(ret_5d, 2), "ret_20d": round(ret_20d, 2),
                        "pct_from_52w_hi": round(pct_from_hi, 1),
                        "above_ema20": above_ema20, "above_ema50": above_ema50,
                        "active_signal": False, "stop": None, "target": None,
                        "tp1_r": None, "tp2": None,
                        "_sort_score": abs(ret_5d) + vol_ratio * 5,  # activity score
                    })
                    continue

                # ── Opportunity score (0–100) ────────────────────────────────────
                score = 40   # base
                if "VCP"            in categories: score += 20
                if "BREAKOUT"       in categories: score += 18
                if "EMA20_BOUNCE"   in categories: score += 14
                if "HIGH_TIGHT_FLAG"in categories: score += 16
                if "FLAT_BASE"      in categories: score += 12
                if "RS_LEADER"      in categories: score += 12
                if "ACCUMULATION"   in categories: score += 10
                if "SQUEEZE"        in categories: score += 8
                if "EMA50_BOUNCE"   in categories: score += 6
                if "NEAR_52W_HIGH"  in categories: score += 5
                if "OVERSOLD"       in categories: score += 12
                if "EMA_RECLAIM"    in categories: score += 10
                if "VOL_SPIKE"      in categories: score += 8
                if "RELATIVE_STRENGTH" in categories: score += 7
                if len(categories) > 1:            score += 8   # confluence bonus
                if rsi < 70:                       score += 4
                if vol_ratio > 1.5:                score += 4
                if ret_20d > 5:                    score += 3
                score = min(score, 100)

                # Grade
                if score >= 80:   grade = "A"
                elif score >= 65: grade = "B"
                elif score >= 50: grade = "C"
                else:             grade = "WATCH"

                # Primary category (highest priority match)
                _priority = ["VCP","BREAKOUT","HIGH_TIGHT_FLAG","FLAT_BASE",
                             "EMA20_BOUNCE","RS_LEADER","OVERSOLD",
                             "EMA_RECLAIM","ACCUMULATION","VOL_SPIKE",
                             "SQUEEZE","EMA50_BOUNCE","NEAR_52W_HIGH",
                             "RELATIVE_STRENGTH"]
                primary = next((c for c in _priority if c in categories), categories[0])

                results.append({
                    "symbol":          symbol,
                    "setup_type":      primary,             # primary category
                    "categories":      categories,          # all matched categories
                    "category_notes":  category_notes,      # human-readable notes
                    "grade":           grade,
                    "score":           score,
                    "close":           round(close, 2),
                    "ema20":           round(ema20, 2),
                    "ema50":           round(ema50, 2),
                    "rsi":             round(rsi, 1),
                    "vol_ratio":       round(vol_ratio, 2),
                    "ret_5d":          round(ret_5d, 2),
                    "ret_20d":         round(ret_20d, 2),
                    "pct_from_52w_hi": round(pct_from_hi, 1),
                    "above_ema20":     above_ema20,
                    "above_ema50":     above_ema50,
                    # Trade signal fields (only populated if bot has an active signal)
                    "active_signal":   bool(active_signal),
                    "stop":            round(trade_stop, 2)   if trade_stop   else None,
                    "target":          round(trade_target, 2) if trade_target else None,
                    "tp1_r":           (round(float(last["tp1_r"]), 2)
                                        if "tp1_r" in last.index
                                        and not np.isnan(last.get("tp1_r", float("nan")))
                                        else None),
                    "tp2":             (round(close + 3.0 * (close - trade_stop), 2)
                                        if trade_stop else None),
                    # Legacy compat
                    "quality":         "HIGH" if score >= 70 else "MEDIUM",
                })
            except Exception as e:
                logger.debug(f"[SWING screener] {symbol}: {e}")

        # ── Fallback: always show at least 8 stocks ──────────────────────
        MIN_RESULTS = 8
        if len(results) < MIN_RESULTS and _fallback_pool:
            _fallback_pool.sort(key=lambda x: -x["_sort_score"])
            needed = MIN_RESULTS - len(results)
            already = {r["symbol"] for r in results}
            for fb in _fallback_pool:
                if fb["symbol"] in already:
                    continue
                fb.pop("_sort_score", None)
                fb.update({
                    "setup_type": "NOTABLE",
                    "categories": ["NOTABLE"],
                    "category_notes": [
                        f"Most active — {fb['ret_5d']:+.1f}% 5d, vol ×{fb['vol_ratio']:.1f}"
                    ],
                    "grade": "WATCH",
                    "score": 30,
                    "quality": "WATCH",
                })
                results.append(fb)
                if len(results) >= MIN_RESULTS:
                    break

        # Sort: active bot signals first, then by score desc
        results.sort(key=lambda x: (0 if x["active_signal"] else 1, -x["score"]))
        return results[:50]   # cap at 50 for the dashboard
