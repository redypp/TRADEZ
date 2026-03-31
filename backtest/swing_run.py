"""
backtest/swing_run.py

Backtester for the Momentum Swing strategy.

Usage:
    python -m backtest.swing_run
    python -m backtest.swing_run --symbols AAPL NVDA MSFT --years 3
    python -m backtest.swing_run --capital 25000 --years 2

What it does:
    1. Downloads daily OHLCV for each symbol in the universe via yfinance
    2. Runs MomentumSwingStrategy.prepare() on each
    3. Simulates trades with partial exits (TP1 at 1.5R, runner at 3R)
    4. Prints per-symbol and aggregate performance metrics

Metrics:
    Win rate, avg win, avg loss, profit factor, max drawdown,
    Sharpe ratio, expectancy, total return, number of trades
"""

import argparse
import sys
import os
import logging
from datetime import datetime, timedelta

import pandas as pd
import numpy as np
import yfinance as yf

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(
    level=logging.WARNING,   # suppress yfinance noise
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def _download(symbol: str, years: int) -> pd.DataFrame | None:
    """Download daily OHLCV for *symbol* covering *years* of history."""
    end   = datetime.utcnow()
    start = end - timedelta(days=years * 365 + 30)
    try:
        raw = yf.download(
            symbol,
            start=start.strftime("%Y-%m-%d"),
            end=end.strftime("%Y-%m-%d"),
            interval="1d",
            progress=False,
            auto_adjust=True,
        )
        if raw is None or len(raw) < 60:
            return None
        # Flatten MultiIndex columns if present
        if isinstance(raw.columns, pd.MultiIndex):
            raw.columns = raw.columns.get_level_values(0)
        raw.columns = [c.lower() for c in raw.columns]
        return raw.dropna(subset=["close", "volume"])
    except Exception as e:
        logger.warning(f"Download failed for {symbol}: {e}")
        return None


def _simulate_trades(df: pd.DataFrame, capital: float, risk_pct: float,
                     tp1_r: float, tp2_r: float) -> list[dict]:
    """
    Walk forward through the prepared DataFrame bar by bar.

    Entry: when signal == 1 on bar close (enter next bar's open).
    Exit rules:
        - TP1 hit (1.5R): close half the position, move stop to breakeven
        - TP2 hit (3R):   close remaining half
        - Stop hit:       close all
        - EMA20 cross:    close all (trend break exit)
    """
    trades = []
    position = None

    for i in range(1, len(df)):
        bar      = df.iloc[i]
        prev_bar = df.iloc[i - 1]

        # ── Manage open position ──────────────────────────────────────────────
        if position is not None:
            entry  = position["entry"]
            stop   = position["stop"]
            tp1    = position["tp1"]
            tp2    = position["tp2"]
            shares = position["shares"]
            half1  = position["half1_open"]

            hi, lo, cl = float(bar["high"]), float(bar["low"]), float(bar["close"])

            # Check stop (always first — worst case)
            if lo <= stop:
                # Stopped out at stop price
                exit_price = stop
                pnl = (exit_price - entry) * shares
                trades.append({
                    **position["meta"],
                    "exit_date":  bar.name,
                    "exit_price": round(exit_price, 4),
                    "exit_reason":"STOP",
                    "shares":     shares,
                    "pnl":        round(pnl, 2),
                })
                position = None
                continue

            # TP1 — first partial exit at 1.5R
            if half1 and hi >= tp1:
                half_shares  = max(1, shares // 2)
                pnl_partial  = (tp1 - entry) * half_shares
                position["shares"]     -= half_shares
                position["half1_open"]  = False
                position["stop"]        = entry  # move stop to breakeven
                trades.append({
                    **position["meta"],
                    "exit_date":  bar.name,
                    "exit_price": round(tp1, 4),
                    "exit_reason":"TP1",
                    "shares":     half_shares,
                    "pnl":        round(pnl_partial, 2),
                })

            # TP2 — runner exits at 3R
            if position is not None and hi >= tp2:
                remaining = position["shares"]
                pnl_final = (tp2 - entry) * remaining
                trades.append({
                    **position["meta"],
                    "exit_date":  bar.name,
                    "exit_price": round(tp2, 4),
                    "exit_reason":"TP2",
                    "shares":     remaining,
                    "pnl":        round(pnl_final, 2),
                })
                position = None
                continue

            # Trend break exit: close below EMA20
            ema20 = float(bar.get("ema20", 0))
            if ema20 > 0 and cl < ema20:
                remaining = position["shares"]
                pnl_exit  = (cl - entry) * remaining
                trades.append({
                    **position["meta"],
                    "exit_date":  bar.name,
                    "exit_price": round(cl, 4),
                    "exit_reason":"EMA_BREAK",
                    "shares":     remaining,
                    "pnl":        round(pnl_exit, 2),
                })
                position = None
                continue

        # ── Check for new signal (previous bar close) ─────────────────────────
        if position is None and int(prev_bar.get("signal", 0)) == 1:
            sl    = float(prev_bar["stop_loss"])
            entry = float(bar["open"])   # enter at next bar's open
            risk  = entry - sl
            if risk <= 0:
                continue

            # Position sizing based on risk_pct of current capital
            dollar_risk = capital * risk_pct
            shares = max(1, int(dollar_risk / risk))

            tp1_price = entry + tp1_r * risk
            tp2_price = entry + tp2_r * risk

            position = {
                "entry":     entry,
                "stop":      sl,
                "tp1":       tp1_price,
                "tp2":       tp2_price,
                "shares":    shares,
                "half1_open": True,
                "meta": {
                    "symbol":      prev_bar.get("_symbol", "?"),
                    "setup_type":  prev_bar.get("setup_type", ""),
                    "entry_date":  bar.name,
                    "entry_price": round(entry, 4),
                    "stop_loss":   round(sl, 4),
                    "tp1":         round(tp1_price, 4),
                    "tp2":         round(tp2_price, 4),
                    "ema20_at_entry": round(float(prev_bar.get("ema20", 0)), 2),
                    "rsi_at_entry":   round(float(prev_bar.get("rsi", 0)), 1),
                },
            }

    return trades


def _metrics(trades: list[dict], capital: float, years: int) -> dict:
    """Compute standard performance metrics from a list of trade dicts."""
    if not trades:
        return {"total_trades": 0}

    df = pd.DataFrame(trades)
    pnls = df["pnl"].values

    wins   = pnls[pnls > 0]
    losses = pnls[pnls < 0]

    total_pnl = float(pnls.sum())
    win_rate  = len(wins) / len(pnls) * 100

    gross_profit = float(wins.sum())  if len(wins) else 0
    gross_loss   = float(losses.sum()) if len(losses) else 0
    profit_factor = abs(gross_profit / gross_loss) if gross_loss != 0 else float("inf")

    avg_win  = float(wins.mean())   if len(wins)   else 0
    avg_loss = float(losses.mean()) if len(losses) else 0
    expectancy = (win_rate / 100 * avg_win) + ((1 - win_rate / 100) * avg_loss)

    # Running equity curve (simplified — ignore position sizing compounding)
    equity = [capital]
    for p in pnls:
        equity.append(equity[-1] + p)
    equity = np.array(equity)
    peak   = np.maximum.accumulate(equity)
    dd     = (equity - peak) / peak * 100
    max_dd = float(dd.min())

    total_return = (equity[-1] - capital) / capital * 100
    ann_return   = ((equity[-1] / capital) ** (1 / max(years, 1)) - 1) * 100

    # Sharpe (annualized, assuming daily pnl)
    daily_returns = pd.Series(pnls) / capital
    sharpe = float(daily_returns.mean() / daily_returns.std() * np.sqrt(252)) if len(daily_returns) > 1 else 0.0

    return {
        "total_trades":   len(pnls),
        "win_rate":       round(win_rate, 1),
        "avg_win":        round(avg_win, 2),
        "avg_loss":       round(avg_loss, 2),
        "profit_factor":  round(profit_factor, 2),
        "expectancy":     round(expectancy, 2),
        "total_pnl":      round(total_pnl, 2),
        "total_return":   round(total_return, 1),
        "ann_return":     round(ann_return, 1),
        "max_drawdown":   round(max_dd, 1),
        "sharpe":         round(sharpe, 2),
        "final_equity":   round(float(equity[-1]), 2),
        "breakouts":      int((df["setup_type"] == "BREAKOUT").sum()),
        "pullbacks":      int((df["setup_type"] == "PULLBACK").sum()),
        "tp1_exits":      int((df["exit_reason"] == "TP1").sum()),
        "tp2_exits":      int((df["exit_reason"] == "TP2").sum()),
        "stop_exits":     int((df["exit_reason"] == "STOP").sum()),
        "ema_exits":      int((df["exit_reason"] == "EMA_BREAK").sum()),
    }


def _print_metrics(symbol: str, m: dict) -> None:
    """Pretty-print metrics for one symbol."""
    if m.get("total_trades", 0) == 0:
        print(f"  {symbol:<8}  No trades generated.")
        return

    sign = "+" if m["total_pnl"] >= 0 else ""
    dd_warn = " ⚠" if m["max_drawdown"] < -20 else ""
    print(
        f"  {symbol:<8} "
        f"Trades:{m['total_trades']:>4}  "
        f"WR:{m['win_rate']:>5.1f}%  "
        f"PF:{m['profit_factor']:>5.2f}  "
        f"Exp:${m['expectancy']:>+7.2f}  "
        f"P&L:${m['total_pnl']:>+9.2f}  "
        f"Ret:{sign}{m['total_return']:>5.1f}%  "
        f"DD:{m['max_drawdown']:>6.1f}%{dd_warn}  "
        f"Sharpe:{m['sharpe']:>5.2f}"
    )


def run(symbols: list[str], capital: float, years: int,
        risk_pct: float, tp1_r: float, tp2_r: float) -> None:
    """Run the full backtest across all symbols and print results."""
    from strategy.momentum_swing import MomentumSwingStrategy
    strategy = MomentumSwingStrategy()

    print(f"\n{'═'*90}")
    print(f"  MOMENTUM SWING BACKTEST  |  {years}yr  |  ${capital:,.0f} capital  |  "
          f"Risk {risk_pct*100:.2f}%/trade  |  TP1={tp1_r}R  TP2={tp2_r}R")
    print(f"{'═'*90}")
    print(f"  {'SYMBOL':<8} {'TRADES':>7}  {'WIN%':>7}  {'PF':>6}  "
          f"{'EXP':>9}  {'P&L':>11}  {'RET':>7}  {'DD':>8}  SHARPE")
    print(f"  {'─'*84}")

    all_trades = []

    for symbol in symbols:
        raw = _download(symbol, years)
        if raw is None:
            print(f"  {symbol:<8}  No data.")
            continue

        # Tag symbol onto each bar so trade logs reference the symbol
        raw["_symbol"] = symbol

        df = strategy.prepare(raw)
        trades = _simulate_trades(df, capital, risk_pct, tp1_r, tp2_r)

        m = _metrics(trades, capital, years)
        _print_metrics(symbol, m)

        all_trades.extend(trades)

    # ── Aggregate summary ─────────────────────────────────────────────────────
    print(f"\n  {'─'*84}")
    agg = _metrics(all_trades, capital, years)
    if agg.get("total_trades", 0) > 0:
        print(f"\n  AGGREGATE ACROSS {len(symbols)} SYMBOLS:")
        print(f"    Total trades:   {agg['total_trades']}")
        print(f"    Win rate:       {agg['win_rate']}%")
        print(f"    Profit factor:  {agg['profit_factor']}")
        print(f"    Expectancy:     ${agg['expectancy']:+.2f}/trade")
        print(f"    Total P&L:      ${agg['total_pnl']:+,.2f}")
        print(f"    Max drawdown:   {agg['max_drawdown']}%")
        print(f"    Sharpe:         {agg['sharpe']}")
        print(f"\n    Setup breakdown:")
        print(f"      Breakouts:    {agg['breakouts']}  |  Pullbacks: {agg['pullbacks']}")
        print(f"    Exit breakdown:")
        print(f"      TP1:          {agg['tp1_exits']}  |  TP2: {agg['tp2_exits']}  "
              f"|  Stop: {agg['stop_exits']}  |  EMA break: {agg['ema_exits']}")
    print(f"\n{'═'*90}\n")


def main():
    from config import settings

    parser = argparse.ArgumentParser(description="Momentum Swing Backtest")
    parser.add_argument(
        "--symbols", nargs="+",
        default=settings.SWING_UNIVERSE.split(","),
        help="Symbols to test (default: full SWING_UNIVERSE from settings)",
    )
    parser.add_argument("--capital",  type=float, default=25_000, help="Starting capital ($)")
    parser.add_argument("--years",    type=int,   default=3,      help="Years of history")
    parser.add_argument("--risk",     type=float, default=0.0075, help="Risk per trade (0.0075 = 0.75%%)")
    parser.add_argument("--tp1",      type=float, default=1.5,    help="TP1 R-multiple")
    parser.add_argument("--tp2",      type=float, default=3.0,    help="TP2 R-multiple")
    args = parser.parse_args()

    symbols = [s.strip().upper() for s in args.symbols if s.strip()]
    run(
        symbols=symbols,
        capital=args.capital,
        years=args.years,
        risk_pct=args.risk,
        tp1_r=args.tp1,
        tp2_r=args.tp2,
    )


if __name__ == "__main__":
    main()
