"""
monitor/performance.py

Rolling live performance monitor — detects edge decay before it becomes catastrophic.

What it does:
    1. Maintains a rolling window of the last N trades (default 20)
    2. Computes rolling win rate, average R:R, and profit factor
    3. Compares rolling stats to baseline backtest expectations
    4. Issues warnings (and optionally pauses the bot) when degradation is detected

Why this matters:
    A strategy with 44% backtest win rate should expect natural variance — runs
    of 5-8 consecutive losses are NORMAL over 200+ trades. This monitor distinguishes
    between normal variance and genuine edge decay (mean shift) using pre-defined
    thresholds calibrated to the strategy's expected distribution.

    Academic basis: Maven Securities (2024) — rolling-window Sharpe divergence
    identifies systematic decay vs. transient drawdown. A 2-standard-deviation
    drop sustained over 30+ trades signals decay, not noise.

Degradation thresholds:
    WARNING  → rolling WR < 30% for 20 trades (possible decay, watch closely)
    PAUSE    → rolling WR < 25% for 30 trades OR 5+ consecutive daily stop hits
    RETIRE   → rolling WR < 20% for 50 trades with no regime explanation

Usage:
    from monitor.performance import PerformanceMonitor

    monitor = PerformanceMonitor(baseline_win_rate=44.0, baseline_rr=2.0)
    monitor.record_trade(won=True, pnl=50.0, r_multiple=2.1)
    status = monitor.get_status()  # → "OK", "WARNING", or "PAUSE"
"""

from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass, field
from datetime import date
from statistics import mean, stdev

logger = logging.getLogger(__name__)


# ─── Thresholds ────────────────────────────────────────────────────────────────
# Calibrated for a strategy with ~44% win rate and 2:1 R:R.
# Adjust if your backtest baseline differs significantly.

ROLLING_WINDOW          = 20    # trades in the rolling window
WARN_WIN_RATE           = 30.0  # rolling WR below this → WARNING
PAUSE_WIN_RATE          = 25.0  # rolling WR below this → PAUSE
PAUSE_WINDOW_EXTENDED   = 30    # must persist for this many trades to trigger PAUSE
RETIRE_WIN_RATE         = 20.0  # rolling WR below this for 50 trades → consider retiring
RETIRE_WINDOW           = 50
WARN_PROFIT_FACTOR      = 0.7   # rolling PF below this → WARNING (losing more than winning)
PAUSE_DAILY_STOPS       = 5     # daily stop-out (3% DD) hit this many times in a month → PAUSE
SIGNAL_FREQ_DEVIATION   = 2.0   # alert if signal frequency deviates > 2x from baseline


# ─── Trade record ──────────────────────────────────────────────────────────────

@dataclass
class TradeRecord:
    """Lightweight record for one completed trade."""
    date:       date
    won:        bool
    pnl:        float
    r_multiple: float   # actual R multiple achieved (pnl / risk)


# ─── Monitor ──────────────────────────────────────────────────────────────────

class PerformanceMonitor:
    """
    Rolling performance tracker for a single strategy.

    Maintains a sliding window of recent trades and computes live metrics.
    Call record_trade() after every closed trade, get_status() before each entry.
    """

    def __init__(
        self,
        baseline_win_rate:  float = 44.0,   # backtest win rate %
        baseline_rr:        float = 2.0,    # backtest average R:R
        rolling_window:     int   = ROLLING_WINDOW,
    ):
        self.baseline_win_rate = baseline_win_rate
        self.baseline_rr       = baseline_rr
        self.rolling_window    = rolling_window

        # Recent trades (sliding window)
        self._window: deque[TradeRecord] = deque(maxlen=rolling_window)
        # Extended window for PAUSE detection
        self._extended: deque[TradeRecord] = deque(maxlen=RETIRE_WINDOW)

        # Daily stop-out counter (resets monthly)
        self._daily_stops_this_month: int = 0
        self._last_daily_stop_month:  int = -1

        # Signal frequency tracking
        self._signal_count_this_week: int  = 0
        self._baseline_signals_per_week: float | None = None

    # ── Public API ──────────────────────────────────────────────────────────────

    def record_trade(self, won: bool, pnl: float, r_multiple: float) -> None:
        """Record a completed trade and update rolling metrics."""
        rec = TradeRecord(date=date.today(), won=won, pnl=pnl, r_multiple=r_multiple)
        self._window.append(rec)
        self._extended.append(rec)
        self._log_rolling_metrics()

    def record_daily_stop(self) -> None:
        """Call whenever the daily drawdown limit is hit (3% stop triggered)."""
        today = date.today()
        if self._last_daily_stop_month != today.month:
            self._daily_stops_this_month = 0
            self._last_daily_stop_month  = today.month
        self._daily_stops_this_month += 1
        logger.warning(
            f"Daily stop hit — {self._daily_stops_this_month} this month "
            f"(pause threshold: {PAUSE_DAILY_STOPS})"
        )

    def record_signal(self) -> None:
        """Call each time a BRT signal fires (for frequency tracking)."""
        self._signal_count_this_week += 1

    def set_baseline_signal_frequency(self, signals_per_week: float) -> None:
        """Set expected weekly signal frequency from backtest (for anomaly detection)."""
        self._baseline_signals_per_week = signals_per_week

    def get_status(self) -> str:
        """
        Return current performance status.

        Returns:
            "OK"      — performance within expected range
            "WARNING" — degradation detected, watch closely
            "PAUSE"   — sustained degradation, pause new entries
        """
        if len(self._window) < 10:
            return "OK"  # too few trades to assess

        rolling_wr = self._rolling_win_rate(self._window)
        rolling_pf = self._rolling_profit_factor(self._window)

        # Check PAUSE conditions first (more severe)
        if len(self._extended) >= PAUSE_WINDOW_EXTENDED:
            extended_wr = self._rolling_win_rate(self._extended)
            if extended_wr < PAUSE_WIN_RATE:
                logger.error(
                    f"PERFORMANCE PAUSE — rolling win rate {extended_wr:.1f}% "
                    f"below {PAUSE_WIN_RATE}% over {len(self._extended)} trades. "
                    f"New entries should be paused. Review regime and strategy parameters."
                )
                return "PAUSE"

        if self._daily_stops_this_month >= PAUSE_DAILY_STOPS:
            logger.error(
                f"PERFORMANCE PAUSE — {self._daily_stops_this_month} daily stop-outs this month "
                f"(threshold: {PAUSE_DAILY_STOPS}). Review market conditions."
            )
            return "PAUSE"

        # Check WARNING conditions
        if rolling_wr < WARN_WIN_RATE:
            logger.warning(
                f"PERFORMANCE WARNING — rolling win rate {rolling_wr:.1f}% "
                f"below {WARN_WIN_RATE}% over last {len(self._window)} trades. "
                f"Normal variance or early decay — monitor closely."
            )
            return "WARNING"

        if rolling_pf < WARN_PROFIT_FACTOR:
            logger.warning(
                f"PERFORMANCE WARNING — rolling profit factor {rolling_pf:.2f} "
                f"below {WARN_PROFIT_FACTOR} over last {len(self._window)} trades."
            )
            return "WARNING"

        return "OK"

    def get_metrics(self) -> dict:
        """Return current rolling metrics dict for dashboard/logging."""
        if not self._window:
            return {"status": "OK", "trades_in_window": 0}

        rolling_wr = self._rolling_win_rate(self._window)
        rolling_pf = self._rolling_profit_factor(self._window)
        avg_r      = mean(r.r_multiple for r in self._window)

        return {
            "status":                self.get_status(),
            "trades_in_window":      len(self._window),
            "rolling_win_rate":      round(rolling_wr, 1),
            "rolling_profit_factor": round(rolling_pf, 2),
            "rolling_avg_r":         round(avg_r, 2),
            "baseline_win_rate":     self.baseline_win_rate,
            "wr_vs_baseline":        round(rolling_wr - self.baseline_win_rate, 1),
            "daily_stops_month":     self._daily_stops_this_month,
            "total_tracked":         len(self._extended),
        }

    def should_trade(self) -> bool:
        """Returns False if performance status is PAUSE. Use as pre-entry gate."""
        return self.get_status() != "PAUSE"

    # ── Signal frequency monitoring ─────────────────────────────────────────────

    def check_signal_frequency(self, signals_this_week: int) -> None:
        """
        Compare current week's signal count to baseline.

        Too many signals → parameters may have loosened (or regime changed to choppy).
        Too few signals → parameters may have tightened too aggressively.

        Logs warnings but never blocks — frequency is informational.
        """
        if self._baseline_signals_per_week is None:
            return

        ratio = signals_this_week / max(self._baseline_signals_per_week, 1)

        if ratio > SIGNAL_FREQ_DEVIATION:
            logger.warning(
                f"Signal frequency ELEVATED: {signals_this_week} signals this week vs "
                f"{self._baseline_signals_per_week:.0f} baseline ({ratio:.1f}x). "
                f"Possible parameter loosening or increased volatility."
            )
        elif ratio < (1.0 / SIGNAL_FREQ_DEVIATION):
            logger.warning(
                f"Signal frequency LOW: {signals_this_week} signals this week vs "
                f"{self._baseline_signals_per_week:.0f} baseline ({ratio:.1f}x). "
                f"Possible parameter tightening or regime suppression."
            )

    # ── Internal helpers ────────────────────────────────────────────────────────

    @staticmethod
    def _rolling_win_rate(window: deque) -> float:
        if not window:
            return 0.0
        return sum(1 for r in window if r.won) / len(window) * 100

    @staticmethod
    def _rolling_profit_factor(window: deque) -> float:
        gross_win  = sum(r.pnl for r in window if r.pnl > 0)
        gross_loss = abs(sum(r.pnl for r in window if r.pnl < 0))
        return gross_win / gross_loss if gross_loss > 0 else float("inf")

    def _log_rolling_metrics(self) -> None:
        if len(self._window) < 5:
            return
        m = self.get_metrics()
        logger.info(
            f"[Performance] Rolling {len(self._window)} trades | "
            f"WR={m['rolling_win_rate']:.1f}% (base={self.baseline_win_rate}%) | "
            f"PF={m['rolling_profit_factor']:.2f} | "
            f"Avg R={m['rolling_avg_r']:.2f} | "
            f"Status={m['status']}"
        )


# ─── Module-level singleton ────────────────────────────────────────────────────
# A single shared monitor instance for the BRT strategy.
# Import and use this in scheduler.py to track live performance.
#
#   from monitor.performance import brt_monitor
#   brt_monitor.record_trade(won=True, pnl=62.50, r_multiple=2.1)

brt_monitor = PerformanceMonitor(
    baseline_win_rate = 44.0,
    baseline_rr       = 2.0,
    rolling_window    = ROLLING_WINDOW,
)
