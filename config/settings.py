import os
from dotenv import load_dotenv

load_dotenv()

# Exchange
EXCHANGE = os.getenv("EXCHANGE", "bybit")
API_KEY = os.getenv("API_KEY", "")
API_SECRET = os.getenv("API_SECRET", "")
TESTNET = os.getenv("TESTNET", "true").lower() == "true"

# Trading
SYMBOLS = os.getenv("SYMBOLS", "BTC/USDT:USDT").split(",")
TIMEFRAME = os.getenv("TIMEFRAME", "1h")
LEVERAGE = int(os.getenv("LEVERAGE", "5"))

# Risk
RISK_PER_TRADE = float(os.getenv("RISK_PER_TRADE", "0.02"))
MAX_OPEN_POSITIONS = int(os.getenv("MAX_OPEN_POSITIONS", "3"))
MAX_DAILY_DRAWDOWN = float(os.getenv("MAX_DAILY_DRAWDOWN", "0.10"))

# Telegram
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# Strategy params
EMA_FAST = 20
EMA_SLOW = 50
ADX_PERIOD = 14
ADX_THRESHOLD = 25
ATR_PERIOD = 14
ATR_SL_MULTIPLIER = 1.5
ATR_TP_MULTIPLIER = 3.0
