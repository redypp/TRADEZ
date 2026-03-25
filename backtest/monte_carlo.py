"""
backtest/monte_carlo.py

Monte Carlo simulation for strategy robustness validation.

Two simulation methods:
    1. Trade shuffling  — randomly reorder actual trade returns, 10,000 times.
       Tests whether the equity curve depends on lucky sequencing.

    2. Sampling with replacement (bootstrap) — resample trades with replacement.
       Tests how strategy performs across all possible trade orderings, including
       streaks that didn't happen in the actual backtest.

Key outputs:
    - Ruin probability (drawdown exceeds RUIN_THRESHOLD)
    - Median / 5th / 95th percentile equity curves
    - Expected max drawdown distribution
    - Probability of profit over N trades

Usage:
    from backtest.monte_carlo import run_monte_carlo
    result = run_monte_carlo(trades_df, initial_capital=10000.0)
    print(result.summary())

Required columns in trades_df:
    - pnl_dollars : P&L per trade in dollars (positive = win, negative = loss)

Lopez de Prado reference:
    "Advances in Financial Machine Learning" (2018), Chapter 14 — Backtest Statistics.
    Probability of Backtest Overfitting (PBO) requires minimum 200 trades;
    Monte Carlo is meaningful from ~30 trades but conclusions are weak below 100.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# ─── Constants ────────────────────────────────────────────────────────────────

N_SIMULATIONS      = 10_000   # Monte Carlo runs per simulation
RUIN_THRESHOLD     = 0.25     # Max drawdown that constitutes "ruin" (25%)
CONFIDENCE_LOW     = 0.05     # 5th percentile
CONFIDENCE_HIGH    = 0.95     # 95th percentile


# ─── Result Dataclass ─────────────────────────────────────────────────────────

@dataclass
class MonteCarloResult:
    """Full Monte Carlo simulation results for one strategy."""

    method:              str           # "shuffle" or "bootstrap"
    n_trades:            int
    n_simulations:       int
    initial_capital:     float

    # Ruin statistics
    ruin_probability:    float         # fraction of sims that hit RUIN_THRESHOLD drawdown
    ruin_threshold:      float

    # Final equity distribution
    median_final_equity: float
    p05_final_equity:    float         # 5th percentile (worst 5%)
    p95_final_equity:    float         # 95th percentile (best 5%)

    # Max drawdown distribution
    median_max_dd:       float         # median max drawdown across all sims
    p95_max_dd:          float         # 95th percentile worst drawdown (tail risk)

    # Probability of profit
    prob_profit:         float         # fraction of sims ending above initial capital

    # Raw equity curves (shape: n_simulations × n_trades+1) — optional for plotting
    equity_curves:       np.ndarray | None = field(default=None, repr=False)

    def summary(self) -> str:
        lines = [
            f"Monte Carlo ({self.method}) | {self.n_simulations:,} sims | {self.n_trades} trades",
            f"  Ruin probability  : {self.ruin_probability*100:.1f}%  (>{self.ruin_threshold*100:.0f}% DD)",
            f"  Prob of profit    : {self.prob_profit*100:.1f}%",
            f"  Final equity      : median=${self.median_final_equity:,.0f} | "
            f"p05=${self.p05_final_equity:,.0f} | p95=${self.p95_final_equity:,.0f}",
            f"  Max drawdown      : median={self.median_max_dd*100:.1f}% | "
            f"p95={self.p95_max_dd*100:.1f}%",
        ]
        # Pass/fail gates
        gates = []
        if self.ruin_probability < 0.05:
            gates.append("✓ RUIN < 5%")
        else:
            gates.append(f"✗ RUIN {self.ruin_probability*100:.1f}% — FAIL (must be < 5%)")
        if self.prob_profit > 0.70:
            gates.append("✓ PROFIT PROB > 70%")
        else:
            gates.append(f"✗ PROFIT PROB {self.prob_profit*100:.1f}% — marginal")
        if self.p95_max_dd < 0.40:
            gates.append("✓ TAIL DRAWDOWN < 40%")
        else:
            gates.append(f"✗ TAIL DRAWDOWN {self.p95_max_dd*100:.1f}% — FAIL")
        lines.append("  Gates: " + " | ".join(gates))
        return "\n".join(lines)

    @property
    def passes_all_gates(self) -> bool:
        return (
            self.ruin_probability < 0.05
            and self.prob_profit > 0.70
            and self.p95_max_dd < 0.40
        )


# ─── Core Simulation ──────────────────────────────────────────────────────────

def run_monte_carlo(
    trades:          pd.DataFrame,
    initial_capital: float = 10_000.0,
    n_simulations:   int   = N_SIMULATIONS,
    ruin_threshold:  float = RUIN_THRESHOLD,
    method:          str   = "both",
    store_curves:    bool  = False,
) -> dict[str, MonteCarloResult]:
    """
    Run Monte Carlo simulation on a set of completed trades.

    Args:
        trades          : DataFrame with 'pnl_dollars' column per trade
        initial_capital : Starting capital for each simulation run
        n_simulations   : Number of Monte Carlo paths to generate
        ruin_threshold  : Drawdown level that counts as ruin (default 25%)
        method          : "shuffle", "bootstrap", or "both"
        store_curves    : If True, store full equity curve matrix (memory intensive)

    Returns:
        Dict mapping method name → MonteCarloResult.
        If method="both", returns {"shuffle": ..., "bootstrap": ...}.
        If method="shuffle" or "bootstrap", returns {method: ...}.
    """
    if "pnl_dollars" not in trades.columns:
        raise ValueError("trades DataFrame must have 'pnl_dollars' column")

    pnl = trades["pnl_dollars"].values.astype(float)
    n_trades = len(pnl)

    if n_trades < 10:
        raise ValueError(
            f"Only {n_trades} trades — Monte Carlo requires at least 10. "
            f"Results are unreliable below 30."
        )
    if n_trades < 30:
        logger.warning(
            f"Monte Carlo has only {n_trades} trades — results have wide confidence intervals. "
            f"Minimum 100 trades for reliable conclusions."
        )

    results: dict[str, MonteCarloResult] = {}

    methods = ["shuffle", "bootstrap"] if method == "both" else [method]

    for m in methods:
        results[m] = _simulate(
            pnl=pnl,
            n_trades=n_trades,
            initial_capital=initial_capital,
            n_simulations=n_simulations,
            ruin_threshold=ruin_threshold,
            method=m,
            store_curves=store_curves,
        )

    return results


def _simulate(
    pnl:             np.ndarray,
    n_trades:        int,
    initial_capital: float,
    n_simulations:   int,
    ruin_threshold:  float,
    method:          str,
    store_curves:    bool,
) -> MonteCarloResult:
    """Run a single simulation method and compute statistics."""

    rng = np.random.default_rng(seed=42)  # reproducible

    # Build equity curve matrix: shape (n_simulations, n_trades + 1)
    equity_matrix = np.empty((n_simulations, n_trades + 1), dtype=np.float64)
    equity_matrix[:, 0] = initial_capital

    for i in range(n_simulations):
        if method == "shuffle":
            # Shuffle actual trades (same trades, different order)
            shuffled = rng.permutation(pnl)
        else:
            # Bootstrap: sample with replacement (allows streaks not in history)
            shuffled = rng.choice(pnl, size=n_trades, replace=True)

        equity_matrix[i, 1:] = initial_capital + np.cumsum(shuffled)

    # ── Compute statistics ─────────────────────────────────────────────────────

    final_equity = equity_matrix[:, -1]

    # Max drawdown for each simulation path
    max_drawdowns = _compute_max_drawdowns(equity_matrix, initial_capital)

    ruin_count = np.sum(max_drawdowns >= ruin_threshold)
    ruin_prob  = ruin_count / n_simulations

    return MonteCarloResult(
        method              = method,
        n_trades            = n_trades,
        n_simulations       = n_simulations,
        initial_capital     = initial_capital,
        ruin_probability    = float(ruin_prob),
        ruin_threshold      = ruin_threshold,
        median_final_equity = float(np.median(final_equity)),
        p05_final_equity    = float(np.percentile(final_equity, 5)),
        p95_final_equity    = float(np.percentile(final_equity, 95)),
        median_max_dd       = float(np.median(max_drawdowns)),
        p95_max_dd          = float(np.percentile(max_drawdowns, 95)),
        prob_profit         = float(np.mean(final_equity > initial_capital)),
        equity_curves       = equity_matrix if store_curves else None,
    )


def _compute_max_drawdowns(equity_matrix: np.ndarray, initial_capital: float) -> np.ndarray:
    """
    Compute maximum drawdown (from peak) for each simulation path.
    Returns array of shape (n_simulations,) with drawdown as a positive fraction.
    """
    n_sims = equity_matrix.shape[0]
    max_dds = np.empty(n_sims, dtype=np.float64)

    for i in range(n_sims):
        curve   = equity_matrix[i]
        running_peak = np.maximum.accumulate(curve)
        drawdowns    = (running_peak - curve) / running_peak
        max_dds[i]   = drawdowns.max()

    return max_dds


# ─── Convenience: load from backtest engine output ────────────────────────────

def from_backtest_result(backtest_result: dict, **kwargs) -> dict[str, MonteCarloResult]:
    """
    Run Monte Carlo directly from a run_backtest() result dict.

    Args:
        backtest_result : dict returned by backtest.engine.run_backtest()
        **kwargs        : passed to run_monte_carlo()

    Returns:
        Same as run_monte_carlo() — dict of method → MonteCarloResult
    """
    trades_df = backtest_result.get("trades")
    if trades_df is None or len(trades_df) == 0:
        raise ValueError("Backtest result has no trades")

    if "pnl_dollars" not in trades_df.columns:
        # Try to compute from available columns
        if "pnl" in trades_df.columns:
            trades_df = trades_df.copy()
            trades_df["pnl_dollars"] = trades_df["pnl"]
        else:
            raise ValueError(
                "trades DataFrame must have 'pnl_dollars' or 'pnl' column. "
                f"Available columns: {list(trades_df.columns)}"
            )

    initial_capital = backtest_result.get("initial_capital", 10_000.0)
    return run_monte_carlo(trades_df, initial_capital=initial_capital, **kwargs)


# ─── CLI / quick test ─────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO)

    # Generate synthetic trades for testing: 45% win rate, 2:1 R:R, $50 per R
    rng = np.random.default_rng(99)
    n = 200
    wins = rng.random(n) < 0.45
    pnl  = np.where(wins, 100.0, -50.0)  # $100 winner, $50 loser → 2:1 R:R
    trades = pd.DataFrame({"pnl_dollars": pnl})

    print(f"\nTest strategy: 45% WR | 2:1 R:R | {n} trades | $10K capital")
    results = run_monte_carlo(trades, initial_capital=10_000.0, method="both")
    for method, result in results.items():
        print(f"\n{'─'*60}")
        print(result.summary())
