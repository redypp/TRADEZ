"""
backtest/sensitivity.py

Parameter sensitivity analysis — checks whether strategy performance
degrades gracefully or cliff-drops when parameters are varied ±15%.

Purpose:
    Distinguishes strategies with REAL edge from curve-fit strategies.

    A curve-fit strategy looks exceptional at exact parameter values
    but falls off a cliff when parameters are varied even slightly.

    A robust strategy shows SMOOTH degradation:
        param ±15% → performance changes < 20% — acceptable
        param ±15% → performance changes > 50% — curve-fit, do not trade

Methodology:
    For each parameter, sweep it from -30% to +30% in 7 steps,
    hold all other parameters at their default, run the backtest,
    record Sharpe / profit factor / win rate at each step.

    The "sensitivity score" for a parameter is the max percentage
    change in the target metric across the ±15% range.

    sensitivity_score = max(|metric(p±15%) - metric(p_default)| / metric(p_default))

    Gate: all critical parameters must have sensitivity_score < 0.30
    (i.e., ±15% parameter change causes < 30% metric change).

Usage:
    from backtest.sensitivity import run_sensitivity
    result = run_sensitivity(df, "BRT", params=["BRT_ADX_MIN", "BRT_TP_RR"])
    print(result.summary())
    result.plot()  # requires matplotlib
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# ─── Sweep configuration ──────────────────────────────────────────────────────

SWEEP_STEPS  = 7       # Number of steps in the sweep (-30%, -20%, -10%, 0, +10%, +20%, +30%)
SWEEP_RANGE  = 0.30    # ±30% from default
GATE_15PCT   = 0.15    # ±15% sensitivity gate
MAX_METRIC_CHANGE_AT_15PCT = 0.30   # Max allowed metric change at ±15%


# ─── Result Dataclasses ───────────────────────────────────────────────────────

@dataclass
class ParamSensitivity:
    """Sensitivity results for a single parameter."""
    param_name:      str
    default_value:   float
    swept_values:    list[float]          # parameter values tested
    swept_metrics:   list[float]          # metric (Sharpe) at each swept value
    metric_name:     str

    @property
    def default_metric(self) -> float:
        """Metric at the default parameter value."""
        mid = len(self.swept_values) // 2
        return self.swept_metrics[mid]

    @property
    def sensitivity_at_15pct(self) -> float:
        """
        Max percentage change in metric when parameter is varied ±15%.
        Lower is better — 0.0 means completely insensitive.
        """
        target_low  = self.default_value * (1 - GATE_15PCT)
        target_high = self.default_value * (1 + GATE_15PCT)

        metric_changes = []
        for v, m in zip(self.swept_values, self.swept_metrics):
            if target_low <= v <= target_high and self.default_metric != 0:
                change = abs(m - self.default_metric) / abs(self.default_metric)
                metric_changes.append(change)

        return max(metric_changes) if metric_changes else 0.0

    @property
    def passes_gate(self) -> bool:
        return self.sensitivity_at_15pct <= MAX_METRIC_CHANGE_AT_15PCT

    @property
    def cliff_detected(self) -> bool:
        """True if there's a > 50% metric drop at any step (cliff-edge behavior)."""
        if self.default_metric == 0:
            return False
        for m in self.swept_metrics:
            if abs(m - self.default_metric) / abs(self.default_metric) > 0.50:
                return True
        return False


@dataclass
class SensitivityResult:
    """Full sensitivity analysis results for all tested parameters."""
    strategy:   str
    metric:     str
    params:     list[ParamSensitivity] = field(default_factory=list)

    @property
    def passes_all_gates(self) -> bool:
        return all(p.passes_gate for p in self.params)

    @property
    def cliff_params(self) -> list[str]:
        return [p.param_name for p in self.params if p.cliff_detected]

    def summary(self) -> str:
        lines = [
            f"Sensitivity Analysis: {self.strategy} | metric={self.metric}",
            f"  Gate: ±15% param change must cause < {MAX_METRIC_CHANGE_AT_15PCT*100:.0f}% metric change",
            "",
            f"  {'Parameter':25s}  {'Default':>10}  {'±15% sensitivity':>18}  {'Cliff':>6}  {'Status':>8}",
        ]
        for p in self.params:
            cliff_flag = "YES ⚠" if p.cliff_detected else "no"
            status     = "✓ PASS" if p.passes_gate else "✗ FAIL"
            lines.append(
                f"  {p.param_name:25s}  {p.default_value:>10.3g}  "
                f"{p.sensitivity_at_15pct*100:>17.1f}%  {cliff_flag:>6}  {status:>8}"
            )
        lines.append("")
        if self.passes_all_gates:
            lines.append("  OVERALL: ✓ PASS — parameters are robust")
        else:
            lines.append("  OVERALL: ✗ FAIL — curve-fit parameters detected")
        if self.cliff_params:
            lines.append(f"  Cliff-edge params: {', '.join(self.cliff_params)}")
        return "\n".join(lines)

    def plot(self) -> None:
        """Plot sensitivity curves for all parameters. Requires matplotlib."""
        try:
            import matplotlib.pyplot as plt
        except ImportError:
            print("matplotlib not installed — run: pip install matplotlib")
            return

        n = len(self.params)
        fig, axes = plt.subplots(1, n, figsize=(5 * n, 4), sharey=False)
        if n == 1:
            axes = [axes]

        for ax, ps in zip(axes, self.params):
            pct_changes = [
                (v - ps.default_value) / ps.default_value * 100
                for v in ps.swept_values
            ]
            ax.plot(pct_changes, ps.swept_metrics, marker="o", color="steelblue")
            ax.axvline(-15, color="red", linestyle="--", alpha=0.5, label="±15%")
            ax.axvline(+15, color="red", linestyle="--", alpha=0.5)
            ax.axhline(ps.default_metric, color="green", linestyle=":", alpha=0.7, label="default")
            ax.set_title(ps.param_name)
            ax.set_xlabel("Param change (%)")
            ax.set_ylabel(self.metric)
            ax.legend(fontsize=8)
            color = "lightgreen" if ps.passes_gate else "lightsalmon"
            ax.set_facecolor(color)

        fig.suptitle(f"Parameter Sensitivity: {self.strategy}", fontsize=13)
        plt.tight_layout()
        plt.show()


# ─── Core Analysis ────────────────────────────────────────────────────────────

def run_sensitivity(
    df:          pd.DataFrame,
    strategy:    str,
    params:      list[str],
    capital:     float   = 10_000.0,
    metric:      str     = "sharpe",
    sweep_range: float   = SWEEP_RANGE,
    n_steps:     int     = SWEEP_STEPS,
    backtest_fn: Callable | None = None,
) -> SensitivityResult:
    """
    Sweep each parameter individually while holding others at default.

    Args:
        df          : OHLCV price DataFrame
        strategy    : Strategy name ("BRT", "ORB", "DONCHIAN")
        params      : List of settings attribute names to sweep (e.g. ["BRT_ADX_MIN"])
        capital     : Initial capital for each backtest run
        metric      : Performance metric to track ("sharpe", "profit_factor", "win_rate")
        sweep_range : Fraction of default value to sweep (0.30 = ±30%)
        n_steps     : Total number of steps in sweep (odd number centers on default)
        backtest_fn : Custom backtest function. If None, uses backtest.engine.run_backtest.

    Returns:
        SensitivityResult
    """
    if backtest_fn is None:
        from backtest.engine import run_backtest
        backtest_fn = run_backtest

    from config import settings as s

    result = SensitivityResult(strategy=strategy, metric=metric)

    for param_name in params:
        default_val = getattr(s, param_name, None)
        if default_val is None:
            logger.warning(f"Parameter '{param_name}' not found in settings — skipping")
            continue
        if not isinstance(default_val, (int, float)):
            logger.warning(f"Parameter '{param_name}' is not numeric ({type(default_val)}) — skipping")
            continue

        logger.info(f"Sweeping {param_name} (default={default_val}) ...")

        # Generate sweep values: -30%, -20%, -10%, 0, +10%, +20%, +30% of default
        multipliers = np.linspace(1 - sweep_range, 1 + sweep_range, n_steps)

        # For integer params, round to nearest int; for floats keep precision
        if isinstance(default_val, int):
            swept_vals = [max(1, round(default_val * m)) for m in multipliers]
        else:
            swept_vals = [round(default_val * m, 6) for m in multipliers]

        swept_metrics = []
        for val in swept_vals:
            try:
                setattr(s, param_name, type(default_val)(val))
                bt_result = backtest_fn(df, strategy, initial_capital=capital)
                m_val = _extract_metric(bt_result, metric)
            except Exception as e:
                logger.debug(f"  {param_name}={val} → error: {e}")
                m_val = 0.0
            finally:
                setattr(s, param_name, default_val)  # always restore

            swept_metrics.append(m_val)
            logger.debug(f"  {param_name}={val:.4g} → {metric}={m_val:.3f}")

        ps = ParamSensitivity(
            param_name    = param_name,
            default_value = float(default_val),
            swept_values  = [float(v) for v in swept_vals],
            swept_metrics = swept_metrics,
            metric_name   = metric,
        )
        result.params.append(ps)
        logger.info(
            f"  {param_name}: ±15% sensitivity={ps.sensitivity_at_15pct*100:.1f}% "
            f"cliff={ps.cliff_detected} {'✓' if ps.passes_gate else '✗'}"
        )

    return result


def _extract_metric(result: dict, metric: str) -> float:
    if not result:
        return 0.0
    if metric == "sharpe":
        return float(result.get("sharpe_ratio", result.get("sharpe", 0.0)))
    if metric == "profit_factor":
        return float(result.get("profit_factor", 0.0))
    if metric == "win_rate":
        return float(result.get("win_rate", 0.0))
    return float(result.get(metric, 0.0))


# ─── CLI quick test ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print("Sensitivity module loaded. Run via backtest/run.py with --sensitivity flag.")
