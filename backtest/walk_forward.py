"""
backtest/walk_forward.py

Walk-Forward Optimization (WFO) for strategy parameter robustness testing.

Architecture:
    1. Split historical data into N rolling windows (train + test pairs)
    2. Optimize parameters on each train window
    3. Evaluate on corresponding test window (out-of-sample)
    4. Report Walk-Forward Efficiency (WFE) = OOS Sharpe / IS Sharpe

Gate: WFE > 0.50 means the strategy retains >50% of its in-sample edge
when evaluated out-of-sample. This is the minimum acceptable threshold
per Ernest Chan ("Algorithmic Trading", 2013) and Lopez de Prado.

Walk-Forward Efficiency (WFE) interpretation:
    WFE > 0.80 : Excellent — minimal overfitting
    WFE > 0.50 : Acceptable — strategy has real edge
    WFE > 0.30 : Marginal — proceed with caution
    WFE < 0.30 : Overfit — do not trade live

Usage:
    from backtest.walk_forward import run_walk_forward
    from backtest.engine import run_backtest

    result = run_walk_forward(
        df           = price_df,
        strategy     = "BRT",
        param_grid   = {"BRT_TP_RR": [1.5, 2.0, 2.5], "BRT_ADX_MIN": [18, 20, 25]},
        n_windows    = 5,
        train_frac   = 0.70,
    )
    print(result.summary())
"""

from __future__ import annotations

import itertools
import logging
from dataclasses import dataclass, field
from typing import Any, Callable

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


# ─── Result Dataclass ─────────────────────────────────────────────────────────

@dataclass
class WalkForwardWindow:
    """Results for a single train/test window pair."""
    window_id:        int
    train_start:      pd.Timestamp
    train_end:        pd.Timestamp
    test_start:       pd.Timestamp
    test_end:         pd.Timestamp
    best_params:      dict[str, Any]       # params that maximized train Sharpe
    train_sharpe:     float
    test_sharpe:      float
    train_n_trades:   int
    test_n_trades:    int
    train_win_rate:   float
    test_win_rate:    float
    wfe:              float                 # test_sharpe / train_sharpe


@dataclass
class WalkForwardResult:
    """Aggregated walk-forward results across all windows."""
    strategy:         str
    n_windows:        int
    windows:          list[WalkForwardWindow] = field(default_factory=list)

    @property
    def avg_wfe(self) -> float:
        """Average walk-forward efficiency across all windows."""
        if not self.windows:
            return 0.0
        return float(np.mean([w.wfe for w in self.windows]))

    @property
    def avg_oos_sharpe(self) -> float:
        if not self.windows:
            return 0.0
        return float(np.mean([w.test_sharpe for w in self.windows]))

    @property
    def avg_is_sharpe(self) -> float:
        if not self.windows:
            return 0.0
        return float(np.mean([w.train_sharpe for w in self.windows]))

    @property
    def total_oos_trades(self) -> int:
        return sum(w.test_n_trades for w in self.windows)

    @property
    def passes_wfe_gate(self) -> bool:
        return self.avg_wfe >= 0.50

    def summary(self) -> str:
        lines = [
            f"Walk-Forward: {self.strategy} | {self.n_windows} windows",
            f"  IS  Sharpe avg : {self.avg_is_sharpe:.2f}",
            f"  OOS Sharpe avg : {self.avg_oos_sharpe:.2f}",
            f"  WFE            : {self.avg_wfe:.2f}  ({'✓ PASS' if self.passes_wfe_gate else '✗ FAIL — too much decay'})",
            f"  Total OOS trades: {self.total_oos_trades}",
        ]
        lines.append("")
        lines.append(f"  {'Win#':>5}  {'IS Sharpe':>10}  {'OOS Sharpe':>11}  {'WFE':>6}  {'OOS Trades':>11}  Best params")
        for w in self.windows:
            params_str = ", ".join(f"{k}={v}" for k, v in w.best_params.items())
            lines.append(
                f"  {w.window_id:>5}  {w.train_sharpe:>10.2f}  {w.test_sharpe:>11.2f}  "
                f"{w.wfe:>6.2f}  {w.test_n_trades:>11}  {params_str}"
            )
        return "\n".join(lines)


# ─── Core Walk-Forward ────────────────────────────────────────────────────────

def run_walk_forward(
    df:           pd.DataFrame,
    strategy:     str,
    param_grid:   dict[str, list[Any]],
    n_windows:    int   = 5,
    train_frac:   float = 0.70,
    capital:      float = 10_000.0,
    metric:       str   = "sharpe",
    backtest_fn:  Callable | None = None,
) -> WalkForwardResult:
    """
    Run rolling walk-forward optimization.

    Args:
        df          : OHLCV DataFrame indexed by datetime
        strategy    : Strategy name ("BRT", "ORB", "DONCHIAN")
        param_grid  : Dict of param_name → list of values to try
        n_windows   : Number of train/test windows
        train_frac  : Fraction of each window used for training (0.70 = 70/30 split)
        capital     : Starting capital for each simulation
        metric      : Optimization target: "sharpe", "profit_factor", "win_rate"
        backtest_fn : Optional custom backtest function. If None, uses backtest.engine.run_backtest.
                      Signature: fn(df, strategy, initial_capital) -> dict

    Returns:
        WalkForwardResult with per-window and aggregate statistics
    """
    if backtest_fn is None:
        from backtest.engine import run_backtest
        backtest_fn = run_backtest

    # Build parameter combinations
    param_names  = list(param_grid.keys())
    param_values = list(param_grid.values())
    param_combos = list(itertools.product(*param_values))
    n_combos     = len(param_combos)
    logger.info(
        f"WFO: {strategy} | {n_windows} windows | {n_combos} param combos | "
        f"optimize on '{metric}'"
    )

    # Generate window date boundaries
    windows_dates = _generate_windows(df.index, n_windows, train_frac)

    result = WalkForwardResult(strategy=strategy, n_windows=n_windows)

    for wid, (train_start, train_end, test_start, test_end) in enumerate(windows_dates, 1):
        train_df = df.loc[train_start:train_end]
        test_df  = df.loc[test_start:test_end]

        if len(train_df) < 50 or len(test_df) < 20:
            logger.warning(
                f"Window {wid}: insufficient data "
                f"(train={len(train_df)} bars, test={len(test_df)} bars) — skipping"
            )
            continue

        # Optimize on train window
        best_params, best_train_result = _optimize_params(
            df=train_df,
            strategy=strategy,
            param_names=param_names,
            param_combos=param_combos,
            capital=capital,
            metric=metric,
            backtest_fn=backtest_fn,
        )

        # Evaluate best params on test window
        test_result = _run_with_params(
            df=test_df,
            strategy=strategy,
            param_names=param_names,
            params=best_params,
            capital=capital,
            backtest_fn=backtest_fn,
        )

        train_sharpe = _extract_metric(best_train_result, "sharpe")
        test_sharpe  = _extract_metric(test_result, "sharpe")
        wfe = (test_sharpe / train_sharpe) if train_sharpe > 0 else 0.0

        window = WalkForwardWindow(
            window_id      = wid,
            train_start    = pd.Timestamp(train_start),
            train_end      = pd.Timestamp(train_end),
            test_start     = pd.Timestamp(test_start),
            test_end       = pd.Timestamp(test_end),
            best_params    = dict(zip(param_names, best_params)),
            train_sharpe   = train_sharpe,
            test_sharpe    = test_sharpe,
            train_n_trades = len(best_train_result.get("trades", [])),
            test_n_trades  = len(test_result.get("trades", [])),
            train_win_rate = _extract_metric(best_train_result, "win_rate"),
            test_win_rate  = _extract_metric(test_result, "win_rate"),
            wfe            = wfe,
        )
        result.windows.append(window)

        logger.info(
            f"  Window {wid}: IS Sharpe={train_sharpe:.2f}  OOS Sharpe={test_sharpe:.2f}  "
            f"WFE={wfe:.2f}  Best={dict(zip(param_names, best_params))}"
        )

    return result


# ─── Parameter Optimization ───────────────────────────────────────────────────

def _optimize_params(
    df:          pd.DataFrame,
    strategy:    str,
    param_names: list[str],
    param_combos: list[tuple],
    capital:     float,
    metric:      str,
    backtest_fn: Callable,
) -> tuple[tuple, dict]:
    """Grid search over param_combos, return (best_params, best_result)."""
    best_score  = -np.inf
    best_params = param_combos[0]
    best_result = {}

    for combo in param_combos:
        try:
            result = _run_with_params(df, strategy, param_names, combo, capital, backtest_fn)
        except Exception as e:
            logger.debug(f"Param combo {combo} failed: {e}")
            continue

        score = _extract_metric(result, metric)
        if score > best_score:
            best_score  = score
            best_params = combo
            best_result = result

    return best_params, best_result


def _run_with_params(
    df:          pd.DataFrame,
    strategy:    str,
    param_names: list[str],
    params:      tuple,
    capital:     float,
    backtest_fn: Callable,
) -> dict:
    """
    Temporarily override settings with params, run backtest, restore settings.
    """
    from config import settings as s

    # Save original values
    original = {name: getattr(s, name, None) for name in param_names}

    try:
        # Override
        for name, val in zip(param_names, params):
            setattr(s, name, val)
        return backtest_fn(df, strategy, initial_capital=capital)
    finally:
        # Always restore
        for name, val in original.items():
            setattr(s, name, val)


def _extract_metric(result: dict, metric: str) -> float:
    """Extract named metric from backtest result dict, defaulting to 0.0."""
    if not result:
        return 0.0
    if metric == "sharpe":
        return float(result.get("sharpe_ratio", result.get("sharpe", 0.0)))
    if metric == "profit_factor":
        return float(result.get("profit_factor", 0.0))
    if metric == "win_rate":
        return float(result.get("win_rate", 0.0))
    return float(result.get(metric, 0.0))


# ─── Window Generation ────────────────────────────────────────────────────────

def _generate_windows(
    index:       pd.DatetimeIndex,
    n_windows:   int,
    train_frac:  float,
) -> list[tuple]:
    """
    Generate rolling walk-forward window boundaries.

    Returns list of (train_start, train_end, test_start, test_end) tuples.
    Windows are non-overlapping test periods covering the full data range.
    """
    n_bars      = len(index)
    window_size = n_bars // n_windows
    windows     = []

    for i in range(n_windows):
        start = i * window_size
        end   = start + window_size if i < n_windows - 1 else n_bars

        split = start + int((end - start) * train_frac)

        train_start = index[start]
        train_end   = index[split - 1]
        test_start  = index[split]
        test_end    = index[end - 1]

        windows.append((train_start, train_end, test_start, test_end))

    return windows


# ─── CLI quick test ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print("Walk-forward module loaded. Run via backtest/run.py.")
