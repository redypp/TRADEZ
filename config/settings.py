import os
from dotenv import load_dotenv

load_dotenv()

# IBKR Connection
IBKR_HOST = os.getenv("IBKR_HOST", "127.0.0.1")
IBKR_PORT = int(os.getenv("IBKR_PORT", "7497"))   # 7497 = TWS paper trading
IBKR_CLIENT_ID = int(os.getenv("IBKR_CLIENT_ID", "1"))

# Trading mode
PAPER_TRADING = os.getenv("PAPER_TRADING", "true").lower() == "true"

# Contracts
SYMBOLS = os.getenv("SYMBOLS", "MES,MGC").split(",")
EXCHANGE = os.getenv("EXCHANGE", "CME")
CURRENCY = os.getenv("CURRENCY", "USD")

# Timeframe in minutes
TIMEFRAME = int(os.getenv("TIMEFRAME", "60"))

# Risk
RISK_PER_TRADE = float(os.getenv("RISK_PER_TRADE", "0.02"))
MAX_OPEN_POSITIONS = int(os.getenv("MAX_OPEN_POSITIONS", "3"))
MAX_DAILY_DRAWDOWN = float(os.getenv("MAX_DAILY_DRAWDOWN", "0.10"))

# Telegram
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# Strategy parameters
EMA_FAST = 20
EMA_SLOW = 50
ADX_PERIOD = 14
ADX_THRESHOLD = 25
ATR_PERIOD = 14
ATR_SL_MULTIPLIER = 1.5
ATR_TP_MULTIPLIER = 3.0

# Yahoo Finance ticker map (used for backtesting without IBKR)
BACKTEST_TICKER_MAP = {
    "MES": "ES=F",
    "MNQ": "NQ=F",
    "MGC": "GC=F",
    "SIL": "SI=F",
}
