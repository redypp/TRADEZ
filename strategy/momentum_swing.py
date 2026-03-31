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
        """
        # Only evaluate during off-hours (daily signals, not intraday)
        intraday = 9 <= session_hour <= 15
        if intraday:
            return False

        # Hard block if VIX is in panic territory
        vix = fundamentals.get("vix") or 0
        if vix > 35:
            logger.debug(f"[SWING] {symbol} — blocked: VIX={vix:.1f} > 35")
            return False

        # Block in NO_TRADE regime
        if regime == "NO_TRADE":
            return False

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
            tp1   = float(today["close"]) + tp_r1 * risk
            df.iloc[-1, df.columns.get_loc("signal")]     = 1
            df.iloc[-1, df.columns.get_loc("stop_loss")]  = round(stop, 4)
            df.iloc[-1, df.columns.get_loc("take_profit")] = round(tp1, 4)
            df.iloc[-1, df.columns.get_loc("setup_type")] = SETUP_BREAKOUT
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
            tp1   = float(today["close"]) + tp_r1 * risk
            df.iloc[-1, df.columns.get_loc("signal")]     = 1
            df.iloc[-1, df.columns.get_loc("stop_loss")]  = round(stop, 4)
            df.iloc[-1, df.columns.get_loc("take_profit")] = round(tp1, 4)
            df.iloc[-1, df.columns.get_loc("setup_type")] = SETUP_PULLBACK

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
            f"risk={risk:.2f} R:R={take_profit/close if close else 0:.2f}"
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
        Scan the full symbol universe and return all valid setups ranked by quality.

        Used by the AI Screener dashboard — returns a list of setup dicts:
            symbol, setup_type, close, stop, target, risk_pct, rsi, ema20, ema50, quality
        """
        import yfinance as yf
        from datetime import datetime, timedelta

        lookback_days = getattr(settings, "SWING_LOOKBACK_DAYS", 90)
        end   = datetime.utcnow().strftime("%Y-%m-%d")
        start = (datetime.utcnow() - timedelta(days=lookback_days + 10)).strftime("%Y-%m-%d")

        results = []
        for symbol in self.symbols:
            try:
                raw = yf.download(symbol, start=start, end=end,
                                  interval="1d", progress=False, auto_adjust=True)
                if raw is None or len(raw) < 60:
                    continue
                raw.columns = [c.lower() for c in raw.columns]
                df = self.prepare(raw)
                last = df.iloc[-1]
                sig  = int(last.get("signal", 0))
                if sig == 0:
                    continue

                close     = float(last["close"])
                stop      = float(last["stop_loss"])
                target    = float(last["take_profit"])
                rsi       = float(last.get("rsi", 0))
                setup     = str(last.get("setup_type", ""))
                risk_pct  = (close - stop) / close if close > 0 else 0
                quality   = "HIGH" if setup == SETUP_BREAKOUT and rsi < 70 else "MEDIUM"

                results.append({
                    "symbol":     symbol,
                    "setup_type": setup,
                    "close":      round(close, 2),
                    "stop":       round(stop, 2),
                    "target":     round(target, 2),
                    "risk_pct":   round(risk_pct * 100, 2),
                    "rsi":        round(rsi, 1),
                    "ema20":      round(float(last.get("ema20", 0)), 2),
                    "ema50":      round(float(last.get("ema50", 0)), 2),
                    "quality":    quality,
                })
            except Exception as e:
                logger.debug(f"[SWING] scan {symbol}: {e}")

        # Rank: HIGH quality first, then by setup type (breakouts before pullbacks)
        results.sort(key=lambda x: (0 if x["quality"] == "HIGH" else 1,
                                    0 if x["setup_type"] == SETUP_BREAKOUT else 1))
        return results
