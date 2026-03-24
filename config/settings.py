import os
from dotenv import load_dotenv

load_dotenv()

# IBKR Connection (via TWS or IB Gateway)
IBKR_HOST = os.getenv("IBKR_HOST", "127.0.0.1")
IBKR_PORT = int(os.getenv("IBKR_PORT", "7497"))   # 7497 = TWS paper | 7496 = TWS live
IBKR_CLIENT_ID = int(os.getenv("IBKR_CLIENT_ID", "1"))

# Trading mode
PAPER_TRADING = os.getenv("PAPER_TRADING", "true").lower() == "true"

# Contracts and strategy assignment
SYMBOLS = os.getenv("SYMBOLS", "MES,MGC").split(",")
EXCHANGE = os.getenv("EXCHANGE", "CME")
CURRENCY = os.getenv("CURRENCY", "USD")

# Strategy per symbol
# ORB = Opening Range Breakout (index futures, hourly)
# DONCHIAN = Donchian Channel Breakout (metals, daily)
SYMBOL_STRATEGY = {
    "MES": "DONCHIAN",
    "MNQ": "DONCHIAN",
    "MGC": "DONCHIAN",
    "SIL": "DONCHIAN",
}

# Risk
RISK_PER_TRADE = float(os.getenv("RISK_PER_TRADE", "0.02"))
MAX_OPEN_POSITIONS = int(os.getenv("MAX_OPEN_POSITIONS", "3"))
MAX_DAILY_DRAWDOWN = float(os.getenv("MAX_DAILY_DRAWDOWN", "0.10"))

# Telegram
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# ── Opening Range Breakout (ORB) ──────────────────────────────────────────
# Uses 1h candles. Opening range = first candle of regular session (9:30 AM ET)
ORB_TP_MULTIPLIER = 3.0       # TP = 3x the size of the opening range
ORB_SL_BUFFER = 0.25          # SL = opposite side of OR + small buffer (% of OR size)
ORB_ENTRY_HOURS = [10, 11, 12] # Only enter trades in these hours (ET) after the OR
ORB_MAX_RANGE_ATR = 2.5       # Skip if opening range > 2.5x ATR (abnormal day)
ORB_MIN_RANGE_ATR = 0.2       # Skip if opening range < 0.2x ATR (too tight)
ATR_PERIOD = 14

# ── Donchian Channel Breakout ─────────────────────────────────────────────
# Uses daily candles. Turtle Trading system.
DONCHIAN_ENTRY_PERIOD = 20    # Enter on 20-day high/low breakout
DONCHIAN_EXIT_PERIOD = 10     # Exit on 10-day opposite channel (trailing)
DONCHIAN_ATR_PERIOD = 20      # ATR period for position sizing
DONCHIAN_ATR_SL = 2.0         # Stop = 2x ATR from entry

# Long-only symbols (no short trades taken)
LONG_ONLY_SYMBOLS = ["MES", "MNQ"]

# Yahoo Finance ticker map (backtest data source)
BACKTEST_TICKER_MAP = {
    "MES": "ES=F",
    "MNQ": "NQ=F",
    "MGC": "GC=F",
    "SIL": "SI=F",
}
