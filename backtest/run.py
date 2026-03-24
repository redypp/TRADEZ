import sys
import os
import logging

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

from config import settings
from data.fetcher import fetch_historical
from strategy.orb import prepare_orb
from strategy.donchian import prepare_donchian
from backtest.engine import run_backtest
from backtest.report import generate_report, print_report

INITIAL_CAPITAL = 3000.0

# Timeframe per strategy
STRATEGY_TIMEFRAME = {
    "ORB": 60,      # 1h candles
    "DONCHIAN": 1440,  # Daily candles
}

# yfinance period per strategy
STRATEGY_PERIOD = {
    "ORB": "730d",
    "DONCHIAN": "5y",
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

    result = run_backtest(df, strategy=strategy, initial_capital=INITIAL_CAPITAL)
    metrics = generate_report(result, symbol)
    print_report(metrics)

    if not result["trades"].empty:
        os.makedirs("data", exist_ok=True)
        path = f"data/backtest_{symbol}.csv"
        result["trades"].to_csv(path, index=False)
        print(f"  Trade log saved → {path}")

    return metrics


if __name__ == "__main__":
    print("\n" + "=" * 45)
    print("  TRADEZ — BACKTEST RUNNER")
    print(f"  Symbols: {settings.SYMBOLS}")
    print(f"  Capital: ${INITIAL_CAPITAL:,.0f}")
    print("=" * 45)

    all_metrics = {}
    for symbol in settings.SYMBOLS:
        metrics = backtest_symbol(symbol)
        if metrics:
            all_metrics[symbol] = metrics

    if len(all_metrics) > 1:
        print("\n" + "=" * 45)
        print("  COMBINED SUMMARY")
        print("=" * 45)
        for sym, m in all_metrics.items():
            print(f"  {sym:6s}  Return: {m['total_return_pct']:+.1f}%  "
                  f"DD: {m['max_drawdown_pct']:.1f}%  "
                  f"Sharpe: {m['sharpe_ratio']:.2f}  "
                  f"WR: {m['win_rate']}%")
        print("=" * 45)
