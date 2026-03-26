import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env", override=True)

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

# Alpaca API credentials (stocks / ETFs)
ALPACA_API_KEY    = os.getenv("ALPACA_API_KEY", "")
ALPACA_SECRET_KEY = os.getenv("ALPACA_SECRET_KEY", "")

# ── Multi-LLM Advisory & Strategy Selector ────────────────────────────────
# Two independent feature flags:
#
# LLM_ADVISORY_ENABLED — Background market intelligence (Grok + GPT-4 + Claude).
#   Logs to SQLite and sends Telegram on SIGNAL/PRE_MARKET triggers.
#   NEVER blocks execution. Recommended: enable first to build advisory track record.
#   Set LLM_ADVISORY_ENABLED=true in .env.
#
# LLM_SELECTOR_ENABLED — AI strategy selection layer (overrides rule-based routing).
#   Only activate after advisory has been running for 50+ trades.
#   When disabled, rule-based BRT runs as normal.
#   Set LLM_SELECTOR_ENABLED=true in .env.
LLM_ADVISORY_ENABLED = os.getenv("LLM_ADVISORY_ENABLED", "false").lower() == "true"
LLM_SELECTOR_ENABLED = os.getenv("LLM_SELECTOR_ENABLED", "false").lower() == "true"

# ── COT Filter ─────────────────────────────────────────────────────────────
# CFTC Commitment of Traders weekly directional bias filter.
# For MES: if Leveraged Funds are at extreme net long (contrarian SHORT signal),
#   long entries are blocked for the week.
# For commodities (MGC, SIL): blocks entries against commercial positioning extremes.
# Data cached locally for 48h. Returns NEUTRAL if fetch fails (never hard-blocks).
COT_FILTER_ENABLED = os.getenv("COT_FILTER_ENABLED", "true").lower() == "true"

# Claude (Anthropic) — orchestrator: receives all specialist inputs, makes final call
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

# OpenAI GPT-4 — macro/quantitative analyst
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")

# xAI Grok — real-time X/Twitter sentiment + live news (OpenAI-compatible API)
XAI_API_KEY = os.getenv("XAI_API_KEY", "")

# Minimum LLM confidence to act on a recommendation (below this → FLAT)
LLM_MIN_CONFIDENCE = float(os.getenv("LLM_MIN_CONFIDENCE", "0.60"))

# Trading mode
PAPER_TRADING = os.getenv("PAPER_TRADING", "true").lower() == "true"

# ── Equity fallback ────────────────────────────────────────────────────────────
# If the broker API fails to return account equity, the bot needs to know what
# to do. Two options, controlled by EQUITY_FALLBACK in .env:
#
#   EQUITY_FALLBACK=0 (default) — HALT the tick. No equity confirmed = no trade.
#       Safest option. The hourly job simply skips and retries next tick.
#
#   EQUITY_FALLBACK=10000 — Use this value as emergency fallback equity.
#       Use ONLY if you know your account balance and accept the risk of trading
#       on a stale/estimated equity figure. Set to YOUR actual account size.
#       Example: EQUITY_FALLBACK=5000 for a $5,000 account.
#
# Never leave this at 3000 (old hardcoded value) if your account is larger —
# it would undersize every trade and break the risk model.
EQUITY_FALLBACK = float(os.getenv("EQUITY_FALLBACK", "0"))

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

# ── Algo trading robustness controls ──────────────────────────────────────────

# Maximum trades per day (hard cap to prevent churn on choppy days)
# A BRT strategy should fire 1-3 signals on a good day, not 10+.
# If this cap is hit, it's a signal the market is choppy — stop, don't force trades.
MAX_TRADES_PER_DAY = int(os.getenv("MAX_TRADES_PER_DAY", "5"))

# Absolute equity floor — halt all trading if account falls below this level.
# Prevents a runaway losing streak from wiping the account entirely.
# Set to your "I quit for the month" threshold. 0 = disabled.
# Example: $5,000 account → set floor at $4,000 (20% max account drawdown).
EQUITY_FLOOR = float(os.getenv("EQUITY_FLOOR", "0"))

# Slippage stress multiplier for backtesting robustness checks.
# BRT_COST_PER_RT × this factor = stressed round-trip cost.
# Run backtest at 2.0x (normal stress) and 3.0x (worst-case) to verify edge survives.
# Research: at 3x cost, edges below ~1.5 profit factor break even or go negative.
SLIPPAGE_STRESS_FACTOR = float(os.getenv("SLIPPAGE_STRESS_FACTOR", "1.0"))  # 1.0 = no stress

# Time-based sizing reduction: reduce position size after BRT_LATE_SESSION_HOUR ET.
# Liquidity thins after ~14:30 ET. Slippage increases. Smaller size = same dollar risk.
BRT_LATE_SESSION_HOUR        = 14   # After this hour ET, apply late-session size factor
BRT_LATE_SESSION_SIZE_FACTOR = 0.75  # 75% of normal size after 14:30 ET

# Risk
# 1% per trade: enough to grow the account, small enough to survive a losing streak.
# 3% daily stop: a 3-trade sweep-out day ends the session — protects capital on bad days.
# 5% portfolio heat: max total dollar risk at stop across ALL open trades (all brokers).
#   Example: $10K account → max $500 at risk across all open positions simultaneously.
#   5% is the AQR / Two Sigma standard for diversified intraday portfolios.
RISK_PER_TRADE      = float(os.getenv("RISK_PER_TRADE",      "0.01"))  # 1% per trade
MAX_TRADE_RISK      = float(os.getenv("MAX_TRADE_RISK",       "0.02"))  # 2% hard cap per trade
MAX_OPEN_POSITIONS  = int(os.getenv("MAX_OPEN_POSITIONS",    "3"))     # max simultaneous positions
MAX_DAILY_DRAWDOWN  = float(os.getenv("MAX_DAILY_DRAWDOWN",  "0.03"))  # 3% daily stop
PORTFOLIO_HEAT_MAX  = float(os.getenv("PORTFOLIO_HEAT_MAX",  "0.05"))  # 5% total risk at stop

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
BRT_RSI_PERIOD       = 9      # RSI period — 9 is more responsive on 15-min than 14
                              # RSI(14) smooths over 3.5h of bars; RSI(9) reflects
                              # current momentum better for intraday confirmation.
BRT_RSI_LONG_MIN     = 35     # RSI floor: skip if price in freefall
BRT_RSI_LONG_MAX     = 75     # RSI ceiling: skip if severely overextended
BRT_RSI_SHORT_MIN    = 25     # RSI floor for shorts
BRT_RSI_SHORT_MAX    = 65     # RSI ceiling for shorts
BRT_TP_RR            = 2.0    # Take profit as multiple of risk (R:R)
BRT_SL_BUFFER        = 0.30   # Extra ATR buffer below retest low
BRT_EMA_PERIOD       = 20     # EMA period for trend alignment filter
BRT_ATR_PERIOD       = 14     # ATR period for level tolerance + stop sizing
BRT_VWAP_TOLERANCE   = 0.15   # ATR fraction for VWAP retest zone (tighter — VWAP is precise)
# VSA (Volume Spread Analysis) close-position filter — Tom Williams framework
# For longs: retest candle close must be in the UPPER half of the bar's high-low range
#   (close - low) / (high - low) >= 0.5 → strong close, buyers in control
# For shorts: close must be in the LOWER half → sellers in control
# Research finding: reduces entry frequency ~20%, improves win rate 5-8 percentage points.
# On by default — it filters weak "doji-like" candles where close > open but close is
# still in the bottom half of the bar's range (low conviction close).
BRT_VSA_CLOSE_POSITION = True  # Enforce close in correct half of bar range

BRT_REQUIRE_SWEEP    = False  # If True: retest candle must show a liquidity sweep
                              #   LONG : low < broken_level AND close > broken_level
                              #   SHORT: high > broken_level AND close < broken_level
                              # SMC validation: stop-hunt before reversal = institutional confirmation.
                              # Leave False during initial paper trading; enable once 50+ trades logged.

# ── Level-specific ADX adjustments ───────────────────────────────────────────
# Different level types have different trend requirements at confirmation.
# Adjustments are applied as DELTAS on top of the regime-adaptive adx_min base.
#   VWAP:  -5  — VWAP mean-reverts in ranging markets; lower ADX OK
#   PDH/PDL/ORH/ORL/VP: 0 — default, use regime base
#   SWING: +2  — swing levels are less institutionally validated; need more trend
#   FVG:   +2  — FVGs are already lowest-priority; extra trend filter reduces noise
# Example: NORMAL regime (adx_min=20) → VWAP threshold=15, SWING threshold=22.
# Floor: never below 12 (ADX <12 = pure noise regardless of level type).
BRT_ADX_DELTA_VWAP   = -5   # VWAP works with less trend (mean-reversion tendency)
BRT_ADX_DELTA_SWING  = +2   # Swing needs slightly more trend confidence
BRT_ADX_DELTA_FVG    = +2   # FVG — weakest level type, extra filter
BRT_ADX_FLOOR        = 12   # Absolute minimum ADX — below this is noise

# ── Breakeven stop management ──────────────────────────────────────────────────
# Move stop to breakeven (entry price) once trade reaches 1:1 R:R profit.
# Prevents a winner from becoming a full loser. Checked each hourly tick.
# Requires Tradovate order modification via router.modify_stop(symbol, new_stop).
BRT_BREAKEVEN_AT_1R  = True

# ── Drawdown recovery — step-down position sizing ─────────────────────────────
# After N consecutive losses, trade at a reduced risk fraction until recovered.
# Recovery defined as: 1 winning trade resets the streak counter.
# Example: 2 losses in a row → trade at 50% normal risk on the next setup.
#   $10K account, 1% risk = $100/trade → during step-down = $50/trade.
# This prevents a bad streak from cascading into a session-ending drawdown.
BRT_LOSING_STREAK_MAX         = 2    # Trigger step-down after N consecutive losses
BRT_LOSING_STREAK_RISK_FACTOR = 0.5  # Trade at X fraction of normal risk when triggered

# VSA no-demand volume filter on retest entry candle
# Research: MICROSTRUCTURE_RESEARCH.md § VSA — "no demand" bar = low vol + narrow spread + weak close
# A retest candle with very suppressed volume has no institutional participation → low-quality setup
# BRT_VSA_MIN_VOLUME_RATIO: retest bar volume must be >= ratio × 20-bar vol_ma to pass
# Default: 0.0 (off) — enable at 0.6 after gathering 50+ paper trades for calibration
BRT_VSA_NO_DEMAND_CHECK    = False  # Toggle on/off
BRT_VSA_MIN_VOLUME_RATIO   = 0.60   # Minimum volume ratio (of vol_ma) for retest bar

# ── VWAP Mean Reversion (MES, 5-min) ─────────────────────────────────────
# ADX_MAX is the most impactful parameter — controls regime filter.
# Sweep result (2026-03-25, SPY 1h 730d):
#   ADX_MAX=30 → 45.8% WR, 1.01 PF (too loose — trades in trending days)
#   ADX_MAX=18 → best Sharpe + PF in sweep (only trade true ranging days)
# BAND_MULTIPLIER: deviation band width. 1.5 SD = conservative, fewer but higher-quality entries.
VWAP_MR_BAND_MULTIPLIER = float(os.getenv("VWAP_MR_BAND_MULTIPLIER", "1.5"))
VWAP_MR_ADX_MAX         = float(os.getenv("VWAP_MR_ADX_MAX",         "18"))   # tightened from 30
VWAP_MR_RSI_PERIOD      = int(os.getenv("VWAP_MR_RSI_PERIOD",        "5"))
VWAP_MR_RSI_LONG_MAX    = float(os.getenv("VWAP_MR_RSI_LONG_MAX",    "40"))
VWAP_MR_RSI_SHORT_MIN   = float(os.getenv("VWAP_MR_RSI_SHORT_MIN",   "60"))
VWAP_MR_TP_BUFFER       = float(os.getenv("VWAP_MR_TP_BUFFER",       "0.20"))
VWAP_MR_SESSION_START   = int(os.getenv("VWAP_MR_SESSION_START",     "10"))
VWAP_MR_SESSION_END     = int(os.getenv("VWAP_MR_SESSION_END",       "15"))
VWAP_MR_MAX_ENTRIES     = int(os.getenv("VWAP_MR_MAX_ENTRIES",       "2"))

# ── MES cost model (used in backtest for realistic P&L) ──────────────────
BRT_POINT_VALUE      = 5.00  # MES: $5 per index point per contract (ES = $50)
BRT_COST_PER_RT      = 2.40  # Round-trip cost per contract (Tradovate):
                              #   Tradovate commission: $0.79 x 2 = $1.58
                              #   CME exchange fee    : $0.35 x 2 = $0.70
                              #   NFA fee             : $0.02 x 2 = $0.04
                              #   Slippage (1 tick)   : $0.25 x 2 = $0.08 (MES tick = $1.25 but avg 0.5 slip)
                              #   Total               : ~$2.40 per round trip
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

# Lunch avoidance window (ET) — validated by ICT kill zone research:
#   NY lunch (12:00–13:30 ET) = low liquidity, no institutional participation,
#   choppy whipsaw price action. NY PM session resumes ~13:30–14:00.
#   We skip 12:00–13:59 (conservative) to avoid the entire dead zone.
BRT_LUNCH_START_HOUR   = 12   # Avoid entries from 12:00 ET
BRT_LUNCH_END_HOUR     = 13   # Resume entries from 13:00 ET
                              # Narrowed from 14:00 — skipping 12:00-14:00 was losing 2 of 5
                              # trading hours. VWAP retests and ORH/PDH retests set up at 1 PM.
                              # 12:00-13:00 = true dead zone (NY lunch, no institutional flow).
                              # 13:00+ = institutions re-engage for the PM session.

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
