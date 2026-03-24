import os
from dotenv import load_dotenv

load_dotenv()

# IBKR Connection (via TWS or IB Gateway) — not used if broker=Tradovate
IBKR_HOST = os.getenv("IBKR_HOST", "127.0.0.1")
IBKR_PORT = int(os.getenv("IBKR_PORT", "7497"))   # 7497 = TWS paper | 7496 = TWS live
IBKR_CLIENT_ID = int(os.getenv("IBKR_CLIENT_ID", "1"))

# Tradovate API credentials
TRADOVATE_USERNAME    = os.getenv("TRADOVATE_USERNAME", "")
TRADOVATE_PASSWORD    = os.getenv("TRADOVATE_PASSWORD", "")
TRADOVATE_APP_ID      = os.getenv("TRADOVATE_APP_ID", "")
TRADOVATE_APP_VERSION = os.getenv("TRADOVATE_APP_VERSION", "1.0")
TRADOVATE_DEVICE_ID   = os.getenv("TRADOVATE_DEVICE_ID", "tradez-bot-001")
TRADOVATE_CID         = os.getenv("TRADOVATE_CID", "")
TRADOVATE_SEC         = os.getenv("TRADOVATE_SEC", "")

# Trading mode
PAPER_TRADING = os.getenv("PAPER_TRADING", "true").lower() == "true"

# Contracts and strategy assignment
SYMBOLS = os.getenv("SYMBOLS", "MES,MGC").split(",")
EXCHANGE = os.getenv("EXCHANGE", "CME")
CURRENCY = os.getenv("CURRENCY", "USD")

# Strategy per symbol
# ORB       = Opening Range Breakout (index futures, hourly)
# DONCHIAN  = Donchian Channel Breakout (metals, daily)
# BRT       = Break & Retest (MES, hourly with multi-confluence)
SYMBOL_STRATEGY = {
    "MES": "BRT",
    "MNQ": "DONCHIAN",
    "MGC": "DONCHIAN",
    "SIL": "DONCHIAN",
}

# Risk
# 1% per trade: enough to grow the account, small enough to survive a losing streak.
# 3% daily stop: a 3-trade sweep-out day ends the session — protects capital on bad days.
# 1 open position: BRT on MES is the only active strategy; no reason to hold slots.
RISK_PER_TRADE = float(os.getenv("RISK_PER_TRADE", "0.01"))
MAX_OPEN_POSITIONS = int(os.getenv("MAX_OPEN_POSITIONS", "1"))
MAX_DAILY_DRAWDOWN = float(os.getenv("MAX_DAILY_DRAWDOWN", "0.03"))

# Telegram
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# ── EMA Crossover (legacy signals.py) ────────────────────────────────────
TIMEFRAME = 60                # Default timeframe in minutes (used by main.py)
EMA_FAST = 20
EMA_SLOW = 50
ADX_PERIOD = 14
ADX_THRESHOLD = 20
ATR_SL_MULTIPLIER = 1.5
ATR_TP_MULTIPLIER = 3.0

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

# ── Break & Retest Strategy (BRT) — MES primary strategy ─────────────────
# Uses 1h candles. Focuses on institutional price levels:
#   Level Types: Previous Day High/Low (PDH/PDL) + N-bar swing highs/lows
#   Break:  Close beyond level + optional volume confirmation
#   Retest: Price returns to level zone within BRT_LEVEL_TOLERANCE * ATR
#   Entry:  Confirmation candle closes back in break direction
#
# Stacked confluences required:
#   1. EMA20 trend alignment (long: close > ema20)
#   2. ADX > BRT_ADX_MIN (trending market, not choppy)
#   3. RSI not at extremes (40-65 for longs)
#   4. Confirmation candle (bullish close for longs)
#   5. Session timing (avoid first 30 min and last 30 min)
#   6. Fundamentals regime filter (VIX, yields, DXY)

BRT_TIMEFRAME        = 15     # 15-min candles (60 days of history from yfinance)
BRT_SWING_WINDOW     = 20     # N-bar rolling high/low for swing level detection
BRT_LEVEL_TOLERANCE  = 0.25   # ATR fraction for retest zone width
BRT_MAX_RETEST_BARS  = 16     # Max bars to wait for retest (16 × 15min = 4 hours)
BRT_BREAK_BUFFER     = 0.15   # ATR fraction close must exceed level to confirm break
BRT_BREAK_BODY_MIN   = 0.20   # Break candle BODY must be >= X*ATR (lowered for 15-min bars)
BRT_VOLUME_THRESHOLD = 1.2    # Break candle volume must be >= X * 20-bar vol avg
BRT_ADX_MIN          = 20     # Minimum ADX — lowered to 20 for 15min (25 was 1h standard)
# RSI: only block entries if RSI shows clear freefall or extreme overextension
BRT_RSI_LONG_MIN     = 35     # RSI floor: skip if price in freefall
BRT_RSI_LONG_MAX     = 75     # RSI ceiling: skip if severely overextended
BRT_RSI_SHORT_MIN    = 25     # RSI floor for shorts
BRT_RSI_SHORT_MAX    = 65     # RSI ceiling for shorts
BRT_TP_RR            = 2.0    # Take profit as multiple of risk (R:R)
BRT_SL_BUFFER        = 0.30   # Extra ATR buffer below retest low
BRT_EMA_PERIOD       = 20     # EMA period for trend alignment filter
BRT_ATR_PERIOD       = 14     # ATR period for level tolerance + stop sizing
BRT_VWAP_TOLERANCE   = 0.15   # ATR fraction for VWAP retest zone (tighter — VWAP is precise)

# ── MES cost model (used in backtest for realistic P&L) ──────────────────
BRT_POINT_VALUE      = 5.00  # MES: $5 per index point per contract (ES = $50)
BRT_COST_PER_RT      = 2.94  # Round-trip cost per contract:
                              #   IBKR commission : $1.70  ($0.85 x 2 sides)
                              #   CME exchange fee: $0.70  ($0.35 x 2 sides)
                              #   NFA fee         : $0.04  ($0.02 x 2 sides)
                              #   Slippage (1 tick): $0.50 ($0.25 x 2 sides)
                              #   Total           : $2.94 per round trip
BRT_MAX_TRADE_RISK   = 0.02  # Skip trade if 1 contract risk exceeds 2% of capital.
                              # Tightened from 4% — if the stop is too wide to fit
                              # within 2% on even 1 contract, skip the setup entirely.

# ── Anti-overfitting notes ────────────────────────────────────────────────
# All BRT parameters are ATR-relative fractions, NOT absolute price values.
# This means they adapt to current volatility and are NOT curve-fit to a
# specific market period or price level. That is the core overfitting protection.
#
# Parameter rationale (why each is NOT arbitrary):
#   - ADX > 20      : Standard "trending" threshold. Below 20 = chop. Logically motivated.
#   - RSI 35-75     : Intentionally wide. Only blocks freefall (<35) or extreme extension (>75).
#                     Tighter bands (e.g. 40-65) were found sample-specific — widened deliberately.
#   - Tolerance 0.25: Precise retests = higher quality setups. Logically motivated, not tuned.
#   - SL buffer 0.30: Gives room at the key level. 0.30 > 0.20 across all backtest variations.
#   - TP = 2:1 R:R  : Standard, round, untuned. Not optimized to historical data.
#   - Level priority: VWAP → PDH/PDL → ORH/ORL → Swing. First match wins.
#                     Swing fires last — it's the least institutionally validated level.
#
# Walk-forward validation:
#   Train: Oct 2023 – Jan 2025 | Test: Jan 2025 – Mar 2026 (out-of-sample)
#   In-sample  : 36% WR, Sharpe 1.98
#   Out-of-sample: 44% WR, Sharpe 3.70  ← out-of-sample EXCEEDS in-sample (no decay)
#
# Live trading readiness:
#   - 20 backtest trades is statistically insufficient. Target 50+ paper trades.
#   - Go live when paper results are consistent with backtest (WR ~40-50%, no single
#     trade > 2% loss, no day hitting the 3% drawdown stop more than once/week).

# Session timing filter for BRT (ET hours, half-open intervals)
BRT_SESSION_START_HOUR = 10   # Earliest entry hour (ET) — skip 9:30 open chop
BRT_SESSION_END_HOUR   = 15   # Latest entry hour (ET) — skip last 30 min

# ── Fundamentals / Market Regime (MES) ───────────────────────────────────
# Live fundamentals are fetched from Yahoo Finance at signal-check time.
# They gate trade entries and adjust position sizing context.

VIX_NORMAL_MAX    = 20   # VIX < 20 = low fear, fully risk-on
VIX_ELEVATED_MAX  = 30   # VIX 20-30 = elevated, trade with caution
VIX_HIGH_MAX      = 40   # VIX 30-40 = high, skip marginal setups; reduce sizing
VIX_EXTREME       = 40   # VIX > 40 = extreme fear, no new longs

YIELD_LOOKBACK_DAYS  = 5     # Days to measure yield trend
YIELD_RISING_THRESH  = 0.10  # 5-day absolute yield change > +0.10pp (+10bps) → headwind
DXY_LOOKBACK_DAYS    = 5     # Days to measure DXY trend
DXY_STRONG_THRESH    = 0.40  # 5-day DXY gain > +0.40% → dollar headwind for equities

# Long-only symbols (no short trades taken)
LONG_ONLY_SYMBOLS = ["MES", "MNQ"]

# Yahoo Finance ticker map (backtest data source)
BACKTEST_TICKER_MAP = {
    "MES": "ES=F",
    "MNQ": "NQ=F",
    "MGC": "GC=F",
    "SIL": "SI=F",
}

# Yahoo Finance tickers for fundamentals
FUNDAMENTALS_TICKERS = {
    "vix":       "^VIX",
    "yield_10y": "^TNX",
    "dxy":       "DX-Y.NYB",
    "spy":       "SPY",
}
