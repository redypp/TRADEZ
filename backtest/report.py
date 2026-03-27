import pandas as pd
import numpy as np
import logging

logger = logging.getLogger(__name__)


def generate_report(result: dict, symbol: str, timeframe_minutes: int = 15) -> dict:
    """
    Calculate full performance metrics from backtest results.

    Metrics:
        Total trades, win rate, profit factor, avg win/loss,
        max drawdown, Sharpe ratio (corrected), Sortino ratio,
        recovery factor, max consecutive losses, total return

    Args:
        result             : Output of run_backtest()
        symbol             : Instrument name (for display)
        timeframe_minutes  : Bar interval in minutes. Used to correctly annualize
                             the Sharpe ratio. Default 15 (BRT strategy).
                             Pass 60 for hourly, 1440 for daily.
                             BUG FIX: was hardcoded as hourly (6.5 bars/day),
                             overstating BRT Sharpe by ~2x. 15-min = 26 bars/day.
    """
    trades = result["trades"]
    equity = result["equity_curve"]
    initial = result["initial_capital"]
    final = result["final_capital"]

    if trades.empty:
        logger.warning(f"{symbol}: No trades generated.")
        return {}

    wins   = trades[trades["pnl"] > 0]
    losses = trades[trades["pnl"] <= 0]

    total_trades  = len(trades)
    win_rate      = len(wins) / total_trades * 100 if total_trades > 0 else 0
    avg_win       = wins["pnl"].mean()   if not wins.empty   else 0
    avg_loss      = losses["pnl"].mean() if not losses.empty else 0
    gross_profit  = wins["pnl"].sum()
    gross_loss    = abs(losses["pnl"].sum())
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")
    total_return  = (final - initial) / initial * 100

    # ── Max drawdown (from equity curve) ─────────────────────────────────────
    eq          = pd.Series(equity)
    rolling_max = eq.cummax()
    drawdown    = (eq - rolling_max) / rolling_max * 100
    max_drawdown = drawdown.min()

    # ── Sharpe ratio (annualized, corrected for bar timeframe) ────────────────
    # Formula: (mean_trade_pnl / std_trade_pnl) × sqrt(trades_per_year)
    # Annualization factor: trading bars per year = 252 days × bars_per_day
    # bars_per_day = (6.5 hours × 60 min/hour) / timeframe_minutes
    # BRT (15-min): 6.5 × 60 / 15 = 26 bars/day → sqrt(252 × 26) = sqrt(6552)
    # Was wrong: used sqrt(252 × 6.5) = sqrt(1638) — off by factor of 2.
    bars_per_day   = (6.5 * 60) / timeframe_minutes
    annualize_n    = 252 * bars_per_day
    pnl_series     = trades["pnl"]
    if pnl_series.std() > 0:
        sharpe = (pnl_series.mean() / pnl_series.std()) * np.sqrt(annualize_n)
    else:
        sharpe = 0.0

    # ── Sortino ratio (penalises only downside volatility) ────────────────────
    # Better than Sharpe for trading strategies — a strategy with large upside
    # outliers is NOT penalized for those; only losers count against it.
    downside_returns = pnl_series[pnl_series < 0]
    downside_std = downside_returns.std() if len(downside_returns) > 1 else 0.0
    if downside_std > 0:
        sortino = (pnl_series.mean() / downside_std) * np.sqrt(annualize_n)
    else:
        sortino = 0.0

    # ── Recovery factor ───────────────────────────────────────────────────────
    # Total return / max drawdown. How many times profits cover worst drawdown.
    # <2.0 = fragile. >3.0 = robust. >5.0 = excellent.
    recovery_factor = abs(total_return / max_drawdown) if max_drawdown < 0 else float("inf")

    # ── Max consecutive losses ────────────────────────────────────────────────
    # A 40% win rate strategy should expect streaks of 4-5 losses in a row
    # over 200+ trades — this is NORMAL. Flag only if max streak > 8.
    max_consec_losses = 0
    current_streak    = 0
    for pnl in trades["pnl"]:
        if pnl <= 0:
            current_streak += 1
            max_consec_losses = max(max_consec_losses, current_streak)
        else:
            current_streak = 0

    # ── Expectancy per trade ─────────────────────────────────────────────────
    expectancy = (win_rate / 100 * avg_win) + ((1 - win_rate / 100) * avg_loss)

    metrics = {
        "symbol":              symbol,
        "total_trades":        total_trades,
        "wins":                len(wins),
        "losses":              len(losses),
        "win_rate":            round(win_rate, 1),
        "avg_win":             round(avg_win, 2),
        "avg_loss":            round(avg_loss, 2),
        "profit_factor":       round(min(profit_factor, 99.0), 2),  # cap inf at 99
        "expectancy":          round(expectancy, 2),
        "total_return_pct":    round(total_return, 2),
        "max_drawdown_pct":    round(max_drawdown, 2),
        "sharpe_ratio":        round(sharpe, 2),
        "sortino_ratio":       round(sortino, 2),
        "recovery_factor":     round(recovery_factor, 2) if recovery_factor != float("inf") else 99.0,
        "max_consec_losses":   max_consec_losses,
        "initial_capital":     initial,
        "final_capital":       final,
        "timeframe_minutes":   timeframe_minutes,
    }

    return metrics


def print_report(metrics: dict):
    """Print a clean formatted report to the console."""
    if not metrics:
        return

    symbol  = metrics["symbol"]
    divider = "─" * 50

    print(f"\n{'═' * 50}")
    print(f"  BACKTEST REPORT — {symbol}  ({metrics.get('timeframe_minutes', '?')}min bars)")
    print(f"{'═' * 50}")
    print(f"  Capital:         ${metrics['initial_capital']:,.0f}  →  ${metrics['final_capital']:,.0f}")
    print(f"  Total Return:    {metrics['total_return_pct']:+.1f}%")
    print(f"  Max Drawdown:    {metrics['max_drawdown_pct']:.1f}%")
    print(f"  Sharpe Ratio:    {metrics['sharpe_ratio']:.2f}  (annualized, {metrics.get('timeframe_minutes','?')}-min)")
    print(f"  Sortino Ratio:   {metrics['sortino_ratio']:.2f}")
    print(f"  Recovery Factor: {metrics['recovery_factor']:.2f}x")
    print(divider)
    print(f"  Total Trades:    {metrics['total_trades']}", end="")
    if metrics["total_trades"] < 30:
        print("  ⚠️  < 30 trades — statistically insufficient", end="")
    elif metrics["total_trades"] < 100:
        print("  ⚠️  < 100 trades — treat results with caution", end="")
    print()
    print(f"  Win Rate:        {metrics['win_rate']}%  ({metrics['wins']}W / {metrics['losses']}L)")
    print(f"  Max Consec Loss: {metrics['max_consec_losses']} in a row", end="")
    if metrics["max_consec_losses"] > 6:
        print("  ⚠️  high streak risk", end="")
    print()
    print(f"  Avg Win:         ${metrics['avg_win']:,.2f}")
    print(f"  Avg Loss:        ${metrics['avg_loss']:,.2f}")
    print(f"  Profit Factor:   {metrics['profit_factor']:.2f}")
    print(f"  Expectancy:      ${metrics['expectancy']:,.2f} per trade")
    print(f"{'═' * 50}")

    # Grade the results
    grade, notes = _grade(metrics)
    print(f"  VERDICT: {grade}")
    for note in notes:
        print(f"  {note}")
    print(f"{'═' * 50}\n")


def print_brt_breakdown(trades: pd.DataFrame) -> None:
    """
    Print a breakdown of BRT backtest results by key dimensions:
        - Level type (VWAP, PDH, PDL, SWING, etc.)
        - Entry hour (9, 10, 11 ... 15)
        - ADX range at entry (<15, 15–25, 25+)
        - RSI range at entry (<40, 40–60, 60+)
        - Liquidity sweep (yes / no)

    This is the primary tool for understanding WHICH setups are driving
    performance and WHERE the edge actually lives after loosening filters.
    """
    if trades.empty:
        return

    def _wr_row(label: str, subset: pd.DataFrame, total: pd.DataFrame) -> str:
        n = len(subset)
        if n == 0:
            return f"  {label:<22} —"
        wins = (subset["pnl"] > 0).sum()
        wr   = wins / n * 100
        pf_g = subset[subset["pnl"] > 0]["pnl"].sum()
        pf_l = abs(subset[subset["pnl"] <= 0]["pnl"].sum())
        pf   = pf_g / pf_l if pf_l > 0 else float("inf")
        pf_s = f"{pf:.2f}" if pf != float("inf") else " INF"
        pct_of_total = n / len(total) * 100
        return (f"  {label:<22} {n:>4} trades ({pct_of_total:4.0f}%)  "
                f"WR: {wr:5.1f}%  PF: {pf_s}")

    divider = "─" * 60
    print(f"\n{'═' * 60}")
    print(f"  BRT BREAKDOWN ANALYSIS  ({len(trades)} trades)")
    print(f"{'═' * 60}")

    # ── By level type ─────────────────────────────────────────────
    print(f"\n  BY LEVEL TYPE")
    print(divider)
    for ltype in sorted(trades["level_type"].unique()):
        subset = trades[trades["level_type"] == ltype]
        print(_wr_row(ltype or "(unknown)", subset, trades))

    # ── By entry hour ─────────────────────────────────────────────
    if "entry_hour" in trades.columns:
        print(f"\n  BY ENTRY HOUR (ET)")
        print(divider)
        for hour in sorted(trades["entry_hour"].dropna().unique()):
            subset = trades[trades["entry_hour"] == hour]
            label  = f"{int(hour):02d}:00–{int(hour)+1:02d}:00"
            print(_wr_row(label, subset, trades))

    # ── By ADX range ──────────────────────────────────────────────
    if "adx" in trades.columns:
        print(f"\n  BY ADX AT ENTRY")
        print(divider)
        bins   = [(0, 15, "ADX < 15  (choppy)"),
                  (15, 25, "ADX 15–25 (moderate)"),
                  (25, 999, "ADX > 25  (trending)")]
        for lo, hi, label in bins:
            subset = trades[(trades["adx"] >= lo) & (trades["adx"] < hi)]
            print(_wr_row(label, subset, trades))

    # ── By RSI range ──────────────────────────────────────────────
    if "rsi" in trades.columns:
        print(f"\n  BY RSI AT ENTRY")
        print(divider)
        bins = [(0,  40, "RSI < 40  (oversold)"),
                (40, 60, "RSI 40–60 (neutral)"),
                (60, 999, "RSI > 60  (hot)")]
        for lo, hi, label in bins:
            subset = trades[(trades["rsi"] >= lo) & (trades["rsi"] < hi)]
            print(_wr_row(label, subset, trades))

    # ── By liquidity sweep ────────────────────────────────────────
    if "liquidity_sweep" in trades.columns:
        print(f"\n  BY LIQUIDITY SWEEP")
        print(divider)
        print(_wr_row("Sweep confirmed", trades[trades["liquidity_sweep"] == 1], trades))
        print(_wr_row("No sweep",        trades[trades["liquidity_sweep"] == 0], trades))

    print(f"{'═' * 60}\n")


def _grade(m: dict) -> tuple:
    """Return a verdict and notes based on key metrics."""
    issues    = []
    positives = []

    # Win rate
    if m["win_rate"] < 35:
        issues.append("✗ Win rate below 35% — edge too thin at standard R:R")
    elif m["win_rate"] < 40:
        issues.append(f"⚠ Win rate {m['win_rate']}% — marginal, verify at higher sample size")
    else:
        positives.append(f"✓ Win rate {m['win_rate']}%")

    # Profit factor
    if m["profit_factor"] < 1.3:
        issues.append("✗ Profit factor below 1.3 — not enough edge over costs")
    elif m["profit_factor"] < 1.5:
        issues.append(f"⚠ Profit factor {m['profit_factor']} — marginal, watch slippage sensitivity")
    else:
        positives.append(f"✓ Profit factor {m['profit_factor']}")

    # Max drawdown
    if m["max_drawdown_pct"] < -25:
        issues.append(f"✗ Max drawdown {m['max_drawdown_pct']:.1f}% — too high for live trading")
    elif m["max_drawdown_pct"] < -15:
        issues.append(f"⚠ Max drawdown {m['max_drawdown_pct']:.1f}% — high, tighten risk controls")
    else:
        positives.append(f"✓ Max drawdown {m['max_drawdown_pct']:.1f}% within limits")

    # Sharpe ratio
    if m["sharpe_ratio"] < 0.5:
        issues.append("✗ Sharpe below 0.5 — risk-adjusted returns are very weak")
    elif m["sharpe_ratio"] < 1.0:
        issues.append(f"⚠ Sharpe {m['sharpe_ratio']} — below institutional 1.0 threshold")
    else:
        positives.append(f"✓ Sharpe ratio {m['sharpe_ratio']}")

    # Sortino ratio
    if m.get("sortino_ratio", 0) < 1.0:
        issues.append(f"⚠ Sortino {m.get('sortino_ratio', 0):.2f} — downside risk is elevated")
    else:
        positives.append(f"✓ Sortino ratio {m.get('sortino_ratio', 0):.2f}")

    # Recovery factor
    if m.get("recovery_factor", 0) < 1.5:
        issues.append(f"✗ Recovery factor {m.get('recovery_factor', 0):.2f} — profits barely cover worst drawdown")
    elif m.get("recovery_factor", 0) < 2.5:
        issues.append(f"⚠ Recovery factor {m.get('recovery_factor', 0):.2f} — target >2.5 for live trading")
    else:
        positives.append(f"✓ Recovery factor {m.get('recovery_factor', 0):.2f}x")

    # Max consecutive losses
    if m.get("max_consec_losses", 0) > 8:
        issues.append(f"✗ Max consecutive losses: {m.get('max_consec_losses')} — high streak risk, check position sizing")
    elif m.get("max_consec_losses", 0) > 5:
        issues.append(f"⚠ Max consecutive losses: {m.get('max_consec_losses')} — ensure step-down risk is active")

    # Sample size
    if m["total_trades"] < 30:
        issues.append("✗ Fewer than 30 trades — statistically meaningless")
    elif m["total_trades"] < 100:
        issues.append(f"⚠ Only {m['total_trades']} trades — treat with caution, target 100+ before live")

    if issues:
        return "NEEDS REVIEW ⚠️", issues + positives
    return "PASS — READY FOR PAPER TRADING ✓", positives
