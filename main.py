import logging
import sys
import os
from config import settings
from data.fetcher import fetch_historical
from strategy.indicators import add_indicators
from strategy.signals import generate_signals, get_latest_signal

os.makedirs("logs", exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("logs/tradez.log"),
    ],
)
logger = logging.getLogger("TRADEZ")


def run_strategy_check(symbol: str):
    """Pull data, calculate indicators, and print latest signal for a symbol."""
    logger.info(f"--- {symbol} ---")

    df = fetch_historical(symbol, period="2y", timeframe_minutes=settings.TIMEFRAME)
    df = add_indicators(df)
    df = generate_signals(df)

    latest = get_latest_signal(df)
    signal_label = {1: "LONG", -1: "SHORT", 0: "FLAT"}.get(latest["signal"], "FLAT")

    logger.info(f"Signal     : {signal_label}")
    logger.info(f"Close      : {latest['close']}")
    logger.info(f"EMA Fast   : {latest['ema_fast']:.2f}  |  EMA Slow: {latest['ema_slow']:.2f}")
    logger.info(f"ADX        : {latest['adx']:.2f}  |  ATR: {latest['atr']:.2f}")
    if latest["signal"] != 0:
        logger.info(f"Stop Loss  : {latest['stop_loss']}")
        logger.info(f"Take Profit: {latest['take_profit']}")

    return latest


def main():
    logger.info("=== TRADEZ Bot Starting ===")
    logger.info(f"Mode     : {'PAPER' if settings.PAPER_TRADING else 'LIVE'}")
    logger.info(f"Symbols  : {settings.SYMBOLS}")
    logger.info(f"Timeframe: {settings.TIMEFRAME}m  |  Risk/trade: {settings.RISK_PER_TRADE*100}%")

    for symbol in settings.SYMBOLS:
        run_strategy_check(symbol)

    logger.info("=== Strategy check complete ===")


if __name__ == "__main__":
    main()
