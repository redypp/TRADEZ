import pandas as pd
import numpy as np
import logging

logger = logging.getLogger(__name__)


def generate_report(result: dict, symbol: str) -> dict:
    """
    Calculate full performance metrics from backtest results.

    Metrics:
        Total trades, win rate, profit factor, avg win/loss,
        max drawdown, Sharpe ratio, total return
    """
    trades = result["trades"]
    equity = result["equity_curve"]
    initial = result["initial_capital"]
    final = result["final_capital"]

    if trades.empty:
        logger.warning(f"{symbol}: No trades generated.")
        return {}

    wins = trades[trades["pnl"] > 0]
    losses = trades[trades["pnl"] <= 0]

    total_trades = len(trades)
    win_rate = len(wins) / total_trades * 100 if total_trades > 0 else 0
    avg_win = wins["pnl"].mean() if not wins.empty else 0
    avg_loss = losses["pnl"].mean() if not losses.empty else 0
    gross_profit = wins["pnl"].sum()
    gross_loss = abs(losses["pnl"].sum())
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")
    total_return = (final - initial) / initial * 100

    # Max drawdown
    eq = pd.Series(equity)
    rolling_max = eq.cummax()
    drawdown = (eq - rolling_max) / rolling_max * 100
    max_drawdown = drawdown.min()

    # Sharpe ratio (annualized, assuming hourly candles)
    pnl_series = trades["pnl"]
    if pnl_series.std() > 0:
        sharpe = (pnl_series.mean() / pnl_series.std()) * np.sqrt(252 * 6.5)
    else:
        sharpe = 0.0

    # Expectancy per trade
    expectancy = (win_rate / 100 * avg_win) + ((1 - win_rate / 100) * avg_loss)

    metrics = {
        "symbol": symbol,
        "total_trades": total_trades,
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(win_rate, 1),
        "avg_win": round(avg_win, 2),
        "avg_loss": round(avg_loss, 2),
        "profit_factor": round(profit_factor, 2),
        "expectancy": round(expectancy, 2),
        "total_return_pct": round(total_return, 2),
        "max_drawdown_pct": round(max_drawdown, 2),
        "sharpe_ratio": round(sharpe, 2),
        "initial_capital": initial,
        "final_capital": final,
    }

    return metrics


def print_report(metrics: dict):
    """Print a clean formatted report to the console."""
    if not metrics:
        return

    symbol = metrics["symbol"]
    divider = "─" * 45

    print(f"\n{'═' * 45}")
    print(f"  BACKTEST REPORT — {symbol}")
    print(f"{'═' * 45}")
    print(f"  Capital:      ${metrics['initial_capital']:,.0f}  →  ${metrics['final_capital']:,.0f}")
    print(f"  Total Return: {metrics['total_return_pct']:+.1f}%")
    print(f"  Max Drawdown: {metrics['max_drawdown_pct']:.1f}%")
    print(f"  Sharpe Ratio: {metrics['sharpe_ratio']:.2f}")
    print(divider)
    print(f"  Total Trades: {metrics['total_trades']}")
    print(f"  Win Rate:     {metrics['win_rate']}%  ({metrics['wins']}W / {metrics['losses']}L)")
    print(f"  Avg Win:      ${metrics['avg_win']:,.2f}")
    print(f"  Avg Loss:     ${metrics['avg_loss']:,.2f}")
    print(f"  Profit Factor:{metrics['profit_factor']:.2f}")
    print(f"  Expectancy:   ${metrics['expectancy']:,.2f} per trade")
    print(f"{'═' * 45}")

    # Grade the results
    grade, notes = _grade(metrics)
    print(f"  VERDICT: {grade}")
    for note in notes:
        print(f"  {note}")
    print(f"{'═' * 45}\n")


def _grade(m: dict) -> tuple:
    """Return a verdict and notes based on key metrics."""
    issues = []
    positives = []

    if m["win_rate"] < 40:
        issues.append("✗ Win rate below 40% — strategy loses too often")
    else:
        positives.append(f"✓ Win rate {m['win_rate']}%")

    if m["profit_factor"] < 1.5:
        issues.append("✗ Profit factor below 1.5 — not enough edge")
    else:
        positives.append(f"✓ Profit factor {m['profit_factor']}")

    if m["max_drawdown_pct"] < -20:
        issues.append(f"✗ Max drawdown {m['max_drawdown_pct']:.1f}% — too high for live trading")
    else:
        positives.append(f"✓ Max drawdown within limits")

    if m["sharpe_ratio"] < 1.0:
        issues.append("✗ Sharpe ratio below 1.0 — risk-adjusted returns are weak")
    else:
        positives.append(f"✓ Sharpe ratio {m['sharpe_ratio']}")

    if m["total_trades"] < 30:
        issues.append("✗ Fewer than 30 trades — not statistically significant")

    if issues:
        return "NEEDS TUNING ⚠️", issues + positives
    return "PASS — READY FOR RISK MODULE ✓", positives
