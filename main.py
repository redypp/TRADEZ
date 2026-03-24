import logging
import sys
from config import settings
from data.fetcher import get_exchange, fetch_ohlcv, fetch_balance

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("logs/tradez.log"),
    ],
)
logger = logging.getLogger("TRADEZ")


def main():
    logger.info("=== TRADEZ Bot Starting ===")
    logger.info(f"Exchange : {settings.EXCHANGE} | Testnet: {settings.TESTNET}")
    logger.info(f"Symbols  : {settings.SYMBOLS}")
    logger.info(f"Timeframe: {settings.TIMEFRAME} | Leverage: {settings.LEVERAGE}x")

    exchange = get_exchange()
    logger.info("Exchange connection established.")

    balance = fetch_balance(exchange)
    logger.info(f"Account balance — Total: {balance['total']} USDT | Free: {balance['free']} USDT")

    for symbol in settings.SYMBOLS:
        df = fetch_ohlcv(exchange, symbol, settings.TIMEFRAME)
        logger.info(f"{symbol} — Latest close: {df['close'].iloc[-1]}")

    logger.info("=== Phase 1 Complete: Connection OK ===")


if __name__ == "__main__":
    main()
