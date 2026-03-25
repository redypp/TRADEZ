import sys
import os
import logging

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

import pandas as pd
import yfinance as yf
from config import settings
from data.fetcher import fetch_historical
from strategy.orb import prepare_orb
from strategy.donchian import prepare_donchian
from strategy.break_retest import prepare_break_retest
from strategy.rsi2_daily import prepare_rsi2
from strategy.vwap_reversion import prepare_vwap_reversion
from backtest.engine import run_backtest
from backtest.report import generate_report, print_report


def _fetch_vix_daily() -> pd.Series:
    """
    Fetch daily VIX close prices for the backtest window.
    Returns a Series indexed by date (naive, date only) for easy merging.
    """
    try:
        df = yf.download("^VIX", period="730d", interval="1d",
                         progress=False, auto_adjust=True)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df.columns = [c.lower() for c in df.columns]
        series = df["close"].dropna()
        series.index = pd.to_datetime(series.index).normalize()
        return series
    except Exception:
        return pd.Series(dtype=float)


def _apply_vix_filter(df: pd.DataFrame, vix: pd.Series) -> pd.DataFrame:
    """
    Zero out any signals on days where the closing VIX exceeded VIX_EXTREME.
    This mirrors the live fundamentals gate applied in main.py.
    """
    if vix.empty:
        return df
    try:
        bar_dates = df.index.normalize()
    except Exception:
        bar_dates = pd.to_datetime(df.index).normalize()

    daily_vix = bar_dates.map(vix)
    blocked = daily_vix > settings.VIX_EXTREME
    df = df.copy()
    df.loc[blocked, "signal"]      = 0
    df.loc[blocked, "stop_loss"]   = float("nan")
    df.loc[blocked, "take_profit"] = float("nan")
    n_blocked = int(blocked.sum())
    if n_blocked:
        print(f"  VIX gate blocked signals on {blocked[blocked].index.normalize().unique().shape[0]} days"
              f" ({n_blocked} bars) where VIX > {settings.VIX_EXTREME}")
    return df

INITIAL_CAPITAL = 3000.0

# Timeframe per strategy
STRATEGY_TIMEFRAME = {
    "ORB":      60,    # 1h candles
    "DONCHIAN": 1440,  # Daily candles
    "BRT":      15,    # 15-min candles (60 days max from yfinance)
    "VWAP_MR":  5,     # 5-min candles (60 days max from yfinance)
    "RSI2":     1440,  # Daily candles
}

# yfinance period per strategy
STRATEGY_PERIOD = {
    "ORB":      "730d",
    "DONCHIAN": "5y",
    "BRT":      "60d",   # max for 15-min interval from yfinance
    "VWAP_MR":  "60d",  # max for 5-min interval from yfinance
    "RSI2":     "5y",   # 5y of daily data (~200+ trades on SPY)
}


def backtest_symbol(symbol: str):
    strategy = settings.SYMBOL_STRATEGY.get(symbol, "ORB")
    timeframe = STRATEGY_TIMEFRAME[strategy]
    period = STRATEGY_PERIOD[strategy]

    print(f"\nRunning {strategy} backtest for {symbol}...")

    df = fetch_historical(symbol, period=period, timeframe_minutes=timeframe)

    if strategy == "ORB":
        df = prepare_orb(df)
    elif strategy == "DONCHIAN":
        long_only = symbol in settings.LONG_ONLY_SYMBOLS
        df = prepare_donchian(df, long_only=long_only)
    elif strategy == "BRT":
        long_only = symbol in settings.LONG_ONLY_SYMBOLS
        df = prepare_break_retest(df, long_only=long_only)
        # Apply historical VIX gate — mirrors the live fundamentals filter
        vix = _fetch_vix_daily()
        df  = _apply_vix_filter(df, vix)
    elif strategy == "VWAP_MR":
        df = prepare_vwap_reversion(df)
    elif strategy == "RSI2":
        df = prepare_rsi2(df)

    result = run_backtest(df, strategy=strategy, initial_capital=INITIAL_CAPITAL)
    metrics = generate_report(result, symbol)
    print_report(metrics)

    if not result["trades"].empty:
        os.makedirs("data", exist_ok=True)
        path = f"data/backtest_{symbol}.csv"
        result["trades"].to_csv(path, index=False)
        print(f"  Trade log saved → {path}")

    return metrics


def backtest_rsi2(symbol: str = "SPY") -> dict:
    """
    Run RSI(2) Daily Mean Reversion backtest on a stock/ETF (e.g. SPY).
    SPY is fetched directly from yfinance — no TRADEZ symbol mapping needed.
    Uses _run_generic() via run_backtest("RSI2").
    """
    timeframe = STRATEGY_TIMEFRAME["RSI2"]
    period    = STRATEGY_PERIOD["RSI2"]

    print(f"\nRunning RSI2 backtest for {symbol} (daily, {period})...")

    # Fetch directly using ticker (SPY doesn't need TRADEZ symbol mapping)
    df = yf.download(symbol, period=period, interval="1d", progress=False, auto_adjust=True)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df.columns = [c.lower() for c in df.columns]
    df = df[["open", "high", "low", "close", "volume"]].dropna()
    print(f"  Fetched {len(df)} daily bars for {symbol}")

    df = prepare_rsi2(df)

    result  = run_backtest(df, strategy="RSI2", initial_capital=INITIAL_CAPITAL)
    metrics = generate_report(result, symbol)
    print_report(metrics)

    if not result["trades"].empty:
        os.makedirs("data", exist_ok=True)
        path = f"data/backtest_{symbol}_RSI2.csv"
        result["trades"].to_csv(path, index=False)
        print(f"  Trade log saved → {path}")

    return metrics


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="TRADEZ Backtest Runner")
    parser.add_argument("--strategy", choices=["all", "BRT", "ORB", "DONCHIAN", "VWAP_MR", "RSI2"],
                        default="all", help="Strategy to backtest (default: all)")
    args = parser.parse_args()

    print("\n" + "=" * 45)
    print("  TRADEZ — BACKTEST RUNNER")
    print(f"  Capital: ${INITIAL_CAPITAL:,.0f}")
    print("=" * 45)

    all_metrics = {}

    run_all = args.strategy == "all"

    # ── Standard symbol strategies (BRT, ORB, DONCHIAN, VWAP_MR) ────────────
    for symbol in settings.SYMBOLS:
        strategy = settings.SYMBOL_STRATEGY.get(symbol, "ORB")
        if run_all or args.strategy == strategy:
            metrics = backtest_symbol(symbol)
            if metrics:
                all_metrics[symbol] = metrics

    # ── VWAP MR on MES (if not already run above) ────────────────────────────
    if (run_all or args.strategy == "VWAP_MR") and "MES" not in all_metrics:
        # Temporarily override strategy for VWAP_MR run
        orig = settings.SYMBOL_STRATEGY.get("MES")
        settings.SYMBOL_STRATEGY["MES"] = "VWAP_MR"
        metrics = backtest_symbol("MES")
        if metrics:
            all_metrics["MES_VWAP"] = metrics
        settings.SYMBOL_STRATEGY["MES"] = orig

    # ── RSI(2) on SPY ────────────────────────────────────────────────────────
    if run_all or args.strategy == "RSI2":
        metrics = backtest_rsi2("SPY")
        if metrics:
            all_metrics["SPY_RSI2"] = metrics

    if len(all_metrics) > 1:
        print("\n" + "=" * 45)
        print("  COMBINED SUMMARY")
        print("=" * 45)
        for sym, m in all_metrics.items():
            print(f"  {sym:8s}  Return: {m['total_return_pct']:+.1f}%  "
                  f"DD: {m['max_drawdown_pct']:.1f}%  "
                  f"Sharpe: {m['sharpe_ratio']:.2f}  "
                  f"WR: {m['win_rate']}%")
        print("=" * 45)
