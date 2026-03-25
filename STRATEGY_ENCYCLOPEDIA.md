# TRADEZ Strategy Encyclopedia
> Compiled: 2026-03-24 | Research sources: TradingView community scripts, QuantifiedStrategies.com backtested database,
> Netpicks, LuxAlgo, MindMathMoney, TrendSpider, Tradeciety, FluxCharts, Edgeful, QuantVPS, MetroTrade.
> This document is a deep-reference companion to RESEARCH.md. Every strategy below includes exact rules,
> validated parameter settings, community-sourced backtest statistics, known failure modes, and confluence upgrades.

---

## TABLE OF CONTENTS

1. [EMA Crossover — Dual / Triple](#1-ema-crossover--dual--triple)
2. [SuperTrend](#2-supertrend)
3. [RSI Mean Reversion (2-Period / Connors)](#3-rsi-mean-reversion-2-period--connors)
4. [MACD Momentum](#4-macd-momentum)
5. [Bollinger Band Mean Reversion](#5-bollinger-band-mean-reversion)
6. [Bollinger Band Breakout](#6-bollinger-band-breakout)
7. [VWAP Intraday (Trend + Pullback)](#7-vwap-intraday-trend--pullback)
8. [TTM Squeeze / Keltner-Bollinger Compression](#8-ttm-squeeze--keltner-bollinger-compression)
9. [Opening Range Breakout (ORB)](#9-opening-range-breakout-orb)
10. [Donchian Channel Breakout (Turtle System)](#10-donchian-channel-breakout-turtle-system)
11. [Momentum Volume Breakout](#11-momentum-volume-breakout)
12. [NR4 / NR7 Narrow Range Breakout](#12-nr4--nr7-narrow-range-breakout)
13. [RSI Pullback in Trend (Continuation)](#13-rsi-pullback-in-trend-continuation)
14. [MACD + RSI Combined (QuantifiedStrategies)](#14-macd--rsi-combined-quantifiedstrategies)
15. [Linda Raschke 3-10-16 MACD (Fast MACD)](#15-linda-raschke-3-10-16-macd-fast-macd)

---

## 1. EMA Crossover — Dual / Triple

### Overview
Tracks trend direction using the intersection of a fast and slow exponential moving average. Signals a trend reversal or new trend start. One of the most widely tested strategies in existence. Effective when combined with an ADX or momentum filter to eliminate whipsaw in choppy markets.

### Optimal Parameter Sets

| Name | Fast EMA | Slow EMA | Filter EMA | Best Use |
|---|---|---|---|---|
| Scalping | 9 | 21 | — | 5–15min intraday |
| Short-term | 10 | 20 | — | 30min–1h |
| Classic | 20 | 50 | 200 | 1h–Daily swing |
| Swing (Ed Seykota rule: slow = 3× fast) | 21 | 55 | 200 | Daily swing |
| Trend bias only | 50 | 200 | — | Daily / weekly |

Ed Seykota's guideline: the slow EMA should be at least 3× the fast EMA to avoid whipsaws.

### Entry Rules
**Long:**
1. Fast EMA crosses above slow EMA (crossover bar)
2. Price closes above both EMAs
3. ADX > 18 (trend in place, not choppy)
4. RSI between 40–70 (not overbought at entry)
5. Optional: Price above the 200 EMA (long-only filter for stock markets)
6. Optional: Volume > 1.2× 20-bar volume MA on the crossover bar

**Short:**
1. Fast EMA crosses below slow EMA
2. Price closes below both EMAs
3. ADX > 18
4. RSI between 30–60
5. Optional: Price below 200 EMA

### Exit Rules
**Stop Loss:** Below the swing low preceding the crossover (for longs) or above the swing high (for shorts). Minimum 0.5× ATR(14) below/above entry.

**Take Profit:** 2.5–3R for trend-following mode. Alternatively, hold until the EMAs cross back in the opposite direction (trend-following mode, maximum profit, wider drawdown).

**Trailing Stop (trend following mode):** Trail stop to the fast EMA after price moves 1R in your favor. Exit when price closes below the fast EMA.

### Best Timeframe
- Intraday scalping: 5–15 min (9/21 EMA)
- Intraday swing: 30min–1h (10/20 or 20/50 EMA)
- Swing trading: Daily (20/50 or 21/55 with 200 EMA filter)

### Best Instruments
- Stocks (long-only with 200 EMA filter, daily): best performance
- Forex (XAUUSD on 3h showed PF 2.00 with 21/55/200 setup)
- Futures (ES, NQ): use on 1h minimum; 5min generates excessive whipsaw
- ETFs (SPY, QQQ): daily 20/50 reliable

### Community Backtest Statistics
| Setup | Win Rate | Profit Factor | Notes |
|---|---|---|---|
| EMA 10/20 (1h, various) | ~45–52% | 1.27 | 1,500+ trades over 1 year |
| EMA 21/55/200 (XAUUSD 3h) | ~50–55% | 2.00 | Best forex/gold result found |
| EMA 20/50 (TQQQ daily) | ~47% | ~1.4 | Long-only bias helps in bull market |

Win rate is typically 40–55%. The edge comes from asymmetric RR (3R targets vs 1R stops).

### Known Weaknesses
- Severely lags price: enters after trend is already underway
- Whipsaws badly in ranging/choppy markets (ADX < 18)
- Can generate 5–8 consecutive losses in a sideways period
- 5-minute signals are noise — minimum 30min for meaningful signals
- Long-only strategies outperform in stock markets (structural upward drift)

### Confluence Upgrades
1. Add ADX > 20 filter: reduces losing trades by ~25%
2. Add RSI momentum filter (RSI > 50 for longs): improves entry timing
3. Add volume confirmation: eliminates thin-market false crossovers
4. Add higher-timeframe bias: daily EMA alignment must agree with 1h signal
5. Add MACD zero-line filter: enter only if MACD histogram is positive (longs)

---

## 2. SuperTrend

### Overview
ATR-based dynamic trailing indicator. The line sits below price in uptrends (green) and above price in downtrends (red). When price closes through the line, it flips direction. Functions simultaneously as a trend signal AND a trailing stop. Developed by Oliver Seban.

**Formula:** SuperTrend = close ± (multiplier × ATR(period))

### Optimal Parameter Sets

| Use Case | ATR Period | Multiplier | Notes |
|---|---|---|---|
| Default (any) | 10 | 3.0 | TradingView default, universally cited |
| Intraday scalping | 7 | 2.0 | More signals, more noise |
| Intraday standard | 10 | 2.0–2.5 | Day trading 15–60min |
| Swing trading | 14 | 3.0–4.0 | Fewer signals, cleaner |
| High-volatility assets | 10 | 4.0–6.0 | Prevents excessive whipsaw in crypto |
| Trend confirmation only | 14 | 5.0 | Use as a macro trend filter only |

Best practice: keep ATR period 10–20; adjust the multiplier for the instrument's volatility. A higher multiplier = wider band = fewer signals = higher win rate per signal but lower total trade count.

### Entry Rules
**Long:**
1. SuperTrend flips bullish: line was above price, now flips below price (turns green)
2. Close > SuperTrend line on the flip bar
3. ADX > 18 (trend must be present, not just noise flip)
4. RSI 35–70 (not oversold below 35 at a "trend start")
5. Avoid entry if price has been in a sideways band for 10+ bars before the flip

**Short:**
1. SuperTrend flips bearish: line was below price, flips above price (turns red)
2. Close < SuperTrend line on the flip bar
3. ADX > 18
4. RSI 30–65

### Exit Rules
**Stop Loss:** The SuperTrend line itself IS the stop. Trail it as price moves. No additional stop needed in pure trend-following mode.

**Take Profit (optional fixed target):** 3R. In pure trend-following, hold until the line flips again.

**ATR-Based TP/SL variant (TradingView community standard):**
- TP multiplier: 3.0× ATR from entry
- SL multiplier: 1.5× ATR from entry (if not using the line itself)

### Best Timeframe
- 1h (intraday swing): primary recommended
- 4h–Daily (swing): highest reliability per signal
- 15min with strict ADX filter: acceptable
- Sub-15min: noise dominates, avoid

### Best Instruments
- Gold (GC/MGC): excellent — strong trending behavior
- Silver: excellent with wider multiplier
- Index futures (ES, NQ): works but generates more whipsaws due to mean-reversion tendencies
- Stocks: daily timeframe preferred
- Crypto: use multiplier 4–6 to avoid noise

### Community Backtest Statistics
| Condition | Win Rate | Notes |
|---|---|---|
| Standalone, no filters | 40–43% | Low win rate confirmed across multiple large tests (4,052 trade study) |
| With ADX + EMA filter | 50–67% | Filters eliminate low-conviction flips |
| As trailing stop only | N/A | Best use: as the exit mechanism for a different entry trigger |

**Profit expectancy standalone:** approximately 0.24 per trade (low). Must be combined with filters.

**Key finding from 4,052-trade large-scale study (Liberated Stock Trader):** SuperTrend alone is not reliably profitable. The indicator's value is in stop management and trend confirmation, not as a standalone signal generator.

### Known Weaknesses
- Severely underperforms in choppy/ranging markets (frequent small losses)
- 40–43% win rate standalone — relies on asymmetric winners to be profitable
- False signals during news-driven reversals where ATR expands suddenly
- In tight consolidations, can flip 3–4 times in a row generating losses
- Does not distinguish between trend continuation and counter-trend moves

### Confluence Upgrades
1. Add ADX > 20 filter (most impactful single upgrade)
2. Add EMA(50) or EMA(200) direction match: only take longs if price above
3. Add RSI > 50 for long entries, < 50 for shorts
4. Use on higher timeframe as a bias filter for a lower-TF entry system
5. Combine with volume spike on the flip bar

---

## 3. RSI Mean Reversion (2-Period / Connors)

### Overview
The most extensively backtested mean-reversion strategy in retail algo trading. Developed and popularized by Larry Connors. Uses a very short RSI period (2–3 days) to catch extreme oversold/overbought readings in otherwise uptrending markets. Works because equity markets have a well-documented mean-reverting tendency on short timescales while trending on longer timescales.

**Core insight (QuantifiedStrategies.com):** RSI(2) below 10 on a daily chart within an uptrend (price > 200 EMA) is a statistically significant edge. The setup captures the dip-buying behavior of institutional investors who accumulate into weakness.

### Optimal Parameter Sets

| RSI Period | Buy Threshold | Sell Threshold | Notes |
|---|---|---|---|
| 2 | < 10 | > 85–90 | Connors classic — most backtested |
| 2 | < 5 | > 95 | Connors aggressive variant |
| 3 | < 15 | > 85 | More signals, slightly lower win rate |
| 14 | < 30 | > 70 | Classic settings, weaker edge |
| 21 | < 30 | > 70 | Smoother signals, lower frequency |

For the mean-reversion edge: shorter RSI period (2–3) consistently outperforms the default 14 in backtesting on daily equity data.

### Entry Rules (Connors RSI-2 Classic)
**Long:**
1. Price > 200-period SMA (long-only filter — only trade the upside of an uptrend)
2. RSI(2) drops below 10 (extreme short-term oversold within the uptrend)
3. Enter at market close on the trigger day

**Exit:**
- Sell when price closes above the prior day's high (the "QS Exit" — widely confirmed as optimal)
- Alternatively: sell when RSI(2) crosses above 85–90

**Enhanced variant (QuantifiedStrategies QQQ):**
1. Price > 200 EMA (trend filter)
2. RSI(2) < 10 (oversold)
3. Add a second indicator filter (details behind paywall — use volume, ATR-based compression, or MACD histogram as a proxy)
4. Exit: close above prior day's high

### Stop Loss
The Connors system does not use a hard stop (mean reversion relies on the edge of reversion, not trending). This is academically defensible but **for live trading**, add:
- Hard stop: 2× ATR(14) below entry
- Or: 5% below entry price (for stocks)
- Time stop: exit after 5 bars if not profitable

### Best Timeframe
Daily bars. The edge has been verified on daily data since 1993.

Intraday data (sub-daily) produced unreliable results in extensive backtesting. Do not apply this strategy to 1h or 15min bars.

### Best Instruments
- US equity ETFs (SPY, QQQ): primary use case — tested since 1993
- Individual large-cap stocks with mean-reverting character
- Consumer staples ETF (XLP) showed strong results on weekly bars
- Semiconductor ETF (SMH): MACD+RSI combo showed 73% win rate
- **Does not work in forex markets** — confirmed by QuantifiedStrategies

### Community Backtest Statistics (QuantifiedStrategies.com)
| Strategy | Instrument | Win Rate | Avg Gain/Trade | Profit Factor | Max DD | Notes |
|---|---|---|---|---|---|---|
| RSI(2) < 10, exit > prior high | SPY (daily, 1993–2025) | 75% | 0.57% | 2.3 | 23% | $100k → ~$1.7M over 33 years |
| RSI(2) < 10, RSI exit > 85 | SPY | 91% | Lower per-trade | — | — | High win rate, smaller wins |
| RSI(2) + QQQ + second filter | QQQ | 75% | 2.4% avg win | 3.0 | 19.5% | CAGR 12.7%, Sharpe 2.85 |
| 2-week RSI < 15 | XLP (weekly) | — | 1.2% | — | — | Invested only 11% of time |

**Key metrics:** Strategy is invested only 10–27% of the time (very selective), with risk-adjusted returns ~37% annualized on equity (risk-adjusted). Maximum drawdown of ~23% on SPY is better than buy-and-hold (~55%).

### Known Weaknesses
- Works for equities but NOT forex — equity markets have an upward drift that supports mean-reversion in downturns
- Hard stop placement is tricky — the strategy relies on mean reversion, so stops that are too tight get hit before reversion occurs
- Can experience extended drawdowns during market crashes (2008, 2020) when mean reversion fails
- Requires daily bar data — does not translate to intraday
- Cherry-picking signals (only longs in uptrends) is necessary for the edge to hold

### Confluence Upgrades
1. Add price > 200 EMA (non-negotiable long filter for the strategy's edge)
2. Add MACD histogram as secondary filter: enter only if histogram is turning up
3. Add volume: entry bar volume > average (confirms institutional buying)
4. RSI(2) < 5 instead of < 10 for higher-conviction entries (fewer but better trades)
5. Multi-timeframe: weekly RSI should not be deeply overbought at entry

---

## 4. MACD Momentum

### Overview
The MACD (Moving Average Convergence/Divergence) measures the relationship between a fast and slow EMA and surfaces trend direction and momentum. The histogram (MACD line minus signal line) crossing zero is the primary signal. Works best in trending markets, degrades sharply in ranging conditions.

**Standard settings (universally cited):** Fast = 12, Slow = 26, Signal = 9

### Optimal Parameter Sets

| Version | Fast | Slow | Signal | Best For |
|---|---|---|---|---|
| Standard | 12 | 26 | 9 | All markets, default |
| Linda Raschke (3-10-16) | 3 | 10 | 16 | Intraday, scalping, early signals |
| Connors-style | 3 | 10 | 16 | Intraday — detects 5–10 candles earlier than 12/26/9 |

### Entry Rules (Standard 12/26/9)
**Long:**
1. MACD histogram crosses from negative to positive (fast line crosses above signal line)
2. EMA(20) > EMA(50) (trend alignment)
3. ADX > 18
4. RSI 40–70 (not overbought at entry)
5. Volume > vol_ma on signal bar

**Short:**
1. MACD histogram crosses from positive to negative
2. EMA(20) < EMA(50)
3. ADX > 18
4. RSI 30–60

**Zero-line confirmation variant (higher reliability):**
Enter long only when MACD LINE (not histogram) is above zero in addition to the histogram crossover. This ensures the underlying trend EMAs are already bullish.

### Exit Rules
**Stop Loss:** Below EMA(50) or recent swing low for longs (1× ATR below swing low minimum)

**Take Profit:** 2.5R fixed, or hold until MACD histogram crosses back in opposite direction. For intraday: 1.5% fixed target, stop at 1%.

**Linda Raschke (3/10/16) exits:** Exit on first bar where momentum starts reversing (histogram starts declining after a peak), not when it crosses zero. This preserves more of the gain.

### Best Timeframe
- 4h and Daily: highest reliability
- 1h: acceptable with volume filter
- 15min and below: too many false signals — avoid
- Intraday (scalping): use 3/10/16 settings on 5–15min

### Best Instruments
- Stocks (daily): primary — MACD works best with trending equity behavior
- Gold/GC (daily): strong results
- Index futures (1h): acceptable with trend filter
- Commodities: MACD+RSI combo shown to outperform S&P GSCI benchmark (2010–2019 study)
- Forex: works but requires strict trend filter (zero-line confirmation)

### Community Backtest Statistics
| Setup | Win Rate | Avg Gain | Profit Factor | Notes |
|---|---|---|---|---|
| MACD crossover (45min, BTC 2015+) | 42% | — | ~2.0 | 189 trades, risk 1%/trade |
| MACD histogram (12,26,9) SPY | — | 0.95%/trade | 4.22 | S&P 500, mean reversion mode |
| MACD histogram + RSI(2) filter | — | 0.76%/trade | 2.45 | More trades, lower per-trade gain |
| MACD + RSI + mean reversion filter | 73% | 0.88% | — | 235 trades, SMH (semiconductors) |

**Standard MACD alone:** ~40–50% win rate. The edge is in large winners; expect losing streaks in ranging markets.

### Known Weaknesses
- Lagging indicator: enters after trend is established
- Generates excessive false signals on sub-hourly charts
- Performs poorly in sideways/choppy markets
- In strong extended trends, MACD can give early exit signals (crossback) before the move is complete
- The histogram can compress without crossing zero — producing a false reversal signal

### Confluence Upgrades
1. Zero-line filter: MACD line > 0 for longs (most impactful)
2. EMA alignment: fast EMA > slow EMA before taking crossover signal
3. ADX > 20: eliminates 70%+ of false signals in ranging markets
4. RSI(2) oversold dip entry: combine with RSI pullback within uptrend
5. Linda Raschke 3/10/16: use faster settings for earlier entries (more signals, same logic)
6. Stochastic confirmation: Stochastic < 20 for longs when MACD crosses up

---

## 5. Bollinger Band Mean Reversion

### Overview
Price touches or crosses the outer Bollinger Band (2 standard deviations from the 20-period SMA), then reverts back toward the middle band (SMA20). The middle band is the natural target — it represents the "fair value" of recent price. Works in range-bound, low-volatility environments. Fails during breakouts.

### Optimal Parameter Sets

| Use Case | BB Length | Std Dev | Notes |
|---|---|---|---|
| Default / standard | 20 | 2.0 | Most widely used |
| Intraday (day trading) | 10 | 1.5 | Tighter bands, more signals, 5–15min charts |
| Swing trading | 50 | 2.5 | Wider setting, fewer signals, daily |
| Conservative | 20 | 2.5 | Fewer touches, higher conviction entries |

### Entry Rules
**Long:**
1. Price closes below the lower Bollinger Band (20, 2σ)
2. RSI < 35 (confirms oversold condition)
3. ADX < 22 (confirms NOT in a strong trend — trend-following setup kills mean-reversion)
4. Wait for confirmation: next candle closes back above the lower band

**Short:**
1. Price closes above the upper Bollinger Band (20, 2σ)
2. RSI > 65
3. ADX < 22
4. Wait for confirmation: next candle closes back below the upper band

**Advanced (TTM Squeeze pre-filter):** Only enter mean-reversion trades after a period of Bollinger Band compression (bands are tight, inside Keltner Channel). The contraction + touch combination has higher probability.

### Exit Rules
**Stop Loss:** 0.5× ATR(14) beyond the band that was touched. Hard stop — do not widen.

**Take Profit:** Middle band (SMA20). This is the primary target. Approximately 1.5–2R on average.

**Secondary TP:** 1.5–2× risk in points/ticks.

### Best Timeframe
- 15min–1h: primary for intraday
- Daily: works for stock swing trading
- 5min: acceptable with strict filters

### Best Instruments
- MES / ES (intraday, range-bound sessions): excellent
- Gold (choppy periods): works well
- Large-cap stocks (daily): reliable in non-trending environments
- ETFs (SPY, QQQ): works well in range-bound market regimes

### Community Backtest Statistics
| Setup | Win Rate | Reward:Risk | Sample | Notes |
|---|---|---|---|---|
| BB(20,2) + RSI confirmation, 15min | ~35% | ~1.8 | 132 trades | With 0.1% commission + 1 tick slippage |
| BB mean reversion (daily stocks) | ~55–65% | ~1.3–1.5 | varies | Higher win rate, smaller RR than intraday |

Note: The 35% win rate with 1.8 RR is approximately breakeven (0.35 × 1.8 − 0.65 = −0.02). This strategy requires the RSI confirmation candle and volume filters to push it into profitability.

### Known Weaknesses
- Major risk: price can "walk the band" during breakouts for many consecutive candles
- Fails entirely in trending markets — must have ADX filter
- The confirmation candle requirement misses entries but prevents many losing trades
- Low win rate without RSI/ADX filters — the filter combination is required, not optional
- VIX > 25 makes bands expand rapidly, invalidating the setup

### Confluence Upgrades
1. ADX < 20 filter (non-negotiable for mean reversion)
2. RSI confirmation: RSI must be confirming the expected reversal direction
3. VWAP proximity: enter only if VWAP is near the middle band (adds institutional level confluence)
4. Volume declining on the touch (exhaustion move) then rising on the confirmation candle
5. Daily trend alignment: ensure the higher-TF trend supports the reversion direction

---

## 6. Bollinger Band Breakout

### Overview
The opposite of mean reversion. Price has been compressed (bands have narrowed) and then breaks out explosively beyond the band. The compression period signals energy accumulation. The breakout signals the energy release. This is the "squeeze-and-pop" setup.

### Setup Requirements
1. Bollinger Band Width (BBW) is at or near a multi-month low (bands are tight)
2. Optionally: Bollinger Bands are inside the Keltner Channel (TTM Squeeze condition)
3. Price breaks and closes ABOVE the upper band (long) or BELOW the lower band (short)

### Entry Rules
**Long:**
1. BBW in the lowest 20th percentile of the past 3–6 months (compression confirmed)
2. Price closes above the upper Bollinger Band
3. MACD histogram is positive (momentum confirms direction)
4. RSI 50–70 (moderate momentum, not overbought)
5. Volume > 1.5× vol_ma on breakout bar

**Short:**
1. BBW compressed as above
2. Price closes below the lower Bollinger Band
3. MACD histogram is negative
4. RSI 30–50
5. Volume > 1.5× vol_ma

### Exit Rules
**Stop Loss:** Lower band at time of entry (for longs); upper band (for shorts). This is a natural volatility-based stop.

**Take Profit:** 2× the breakout distance (1:2 R:R minimum). Or: trail using the middle band (SMA20) as trailing stop once price is 1R in profit.

### Best Timeframe
- 15min–1h: intraday breakout
- Daily: swing breakout (most reliable)
- Weekly: position trading (fewest false breakouts)

### Best Instruments
- All instruments where periods of low volatility alternate with explosive moves
- Crypto (high BBW compression + expansion cycles)
- Gold (excellent)
- Index futures before major economic releases

### Known Weaknesses
- False breakouts are common — price breaks the band and immediately reverses
- Requires volume confirmation to filter false breaks
- Bands expand during news events, generating false squeeze signals

### Confluence Upgrades
1. TTM Squeeze condition (BB inside KC): strongest pre-filter available
2. Volume > 2× average: eliminates majority of false breakouts
3. MACD direction confirmation
4. RSI in 50–65 range (not already overbought at breakout)
5. Higher-timeframe trend alignment

---

## 7. VWAP Intraday (Trend + Pullback)

### Overview
VWAP (Volume Weighted Average Price) is the most-watched intraday level for institutional order flow. Institutions use VWAP as a benchmark for execution quality. When price is above VWAP, institutions are long and defending it as support. When below, they're short and defending it as resistance. The pullback-to-VWAP entry catches the institutional buy/sell at the most liquid intraday level.

**VWAP resets every session.** Only relevant on intraday charts; becomes meaningless on daily/weekly bars.

### Configuration
- **Anchor Period:** Session (daily reset, non-negotiable for intraday)
- **Standard Deviation Bands:** Plot 1σ and 2σ bands for overbought/oversold targets
- **Timeframe:** 5–15min primary; 1–5min for scalping

### Entry Rules

**Strategy A — Trend-Following VWAP (high-momentum days)**

Long:
1. Price is above VWAP at session start (first 30 minutes establishes bias)
2. Price pulls back to VWAP but does not close below it
3. A bullish candle forms at VWAP (pin bar, engulfing, or strong close > open)
4. Volume increases on the bounce bar
5. EMA(20) is above VWAP (confirms trend direction)

Short:
1. Price is below VWAP after the opening 30 minutes
2. Price rallies up to VWAP but fails to close above it
3. Bearish candle forms at VWAP level
4. Volume increases on the rejection bar

**Strategy B — VWAP Mean Reversion (range-bound days)**

Long:
1. Price extends to VWAP − 1.5× ATR or to the lower 1σ band
2. RSI < 40
3. ADX < 25 (range-bound session, not trending hard)
4. CVD divergence (optional): price makes lower low but CVD makes higher low (institutional absorption)
5. Enter on confirmation candle closing back toward VWAP

Short:
1. Price extends to VWAP + 1.5× ATR or upper 1σ band
2. RSI > 60
3. ADX < 25

### Exit Rules
**Stop Loss:** Just beyond the VWAP level (for Trend-Following): 0.3× ATR below VWAP for longs, above VWAP for shorts. Or below the low of the confirmation candle.

**Take Profit:**
- Trend-Following: VWAP + 1σ band or 2R
- Mean Reversion: VWAP itself (natural target)
- Session close: close all positions at 15:45 ET (avoid holding through close)

**ATR-based exits:** Size stop at 1× ATR from entry; TP at 2× ATR.

### Best Timeframe
- 5min: scalping entries
- 15min: primary recommended for futures
- 1min: only for scalpers with direct market access

### Best Instruments
- MES / ES: VWAP is the most-watched level for S&P 500 futures
- MNQ / NQ: highly VWAP-responsive
- Individual stocks (high volume): excellent
- Low-volume instruments: unreliable (VWAP meaningless without volume)

### Community Backtest Statistics
VWAP strategies are difficult to backtest at scale due to the daily reset. Community consensus:
- Trend-following VWAP pullback in trending sessions: win rate ~55–65%
- VWAP mean-reversion in range-bound sessions: win rate ~55–60%
- Combined approach: profit factor typically 1.5–2.0 when session regime is correctly classified

### Known Weaknesses
- Only intraday — useless on daily/weekly charts
- Fails on strong trending days (price can run from VWAP all session; mean-reversion entries are fatal)
- Requires real-time session regime classification (trending vs. ranging)
- Volume-light instruments give unreliable VWAP signals
- First 30 minutes of session are often erratic — wait for VWAP to "settle"

### Confluence Upgrades
1. Session regime filter: classify each day as trending or ranging before session starts (prior-day ADX, overnight range, futures premium vs. prior close)
2. EMA(20) above/below VWAP for trend confirmation
3. CVD divergence for mean-reversion entries (institutional absorption signal)
4. Time filter: 9:45–11:30 and 13:00–15:00 ET (avoid first 15min and lunch)
5. Key level proximity: VWAP near previous day high/low adds confluence

---

## 8. TTM Squeeze / Keltner-Bollinger Compression

### Overview
The TTM Squeeze (developed by John Carter) identifies periods of extreme volatility compression. When Bollinger Bands are entirely inside Keltner Channels, the market is in a "squeeze" — building energy for a large move. When the Bollinger Bands expand back outside the Keltner Channel, the "squeeze fires" and the move begins. The momentum histogram provides direction.

This strategy does NOT predict direction. It identifies the WHEN (compression about to release). A direction filter is mandatory.

### Settings

| Parameter | Default | Notes |
|---|---|---|
| Bollinger Band Length | 20 | Standard |
| BB Standard Deviation | 2.0 | Standard |
| Keltner Channel Length | 20 | Standard |
| KC ATR Multiplier | 1.5 | Carter's original setting |
| KC ATR Multiplier (Pro, tight) | 1.0 | TTM Squeeze Pro — more sensitive |
| KC ATR Multiplier (Pro, wide) | 2.0 | TTM Squeeze Pro — less sensitive |

TTM Squeeze Pro uses three KC levels (1.0, 1.5, 2.0) simultaneously. If all three are compressed (all three KC variants are outside the BB), this is a "maximum compression" event — historically precedes the largest moves.

### Entry Rules
**Squeeze Detection:**
- Bollinger Band upper < Keltner Channel upper (same period/multiplier) AND
- Bollinger Band lower > Keltner Channel lower
- Red dots: squeeze is ON (do NOT enter yet)

**Squeeze Fire:**
- Bollinger Bands expand back OUTSIDE the Keltner Channel
- Green dot appears: squeeze has fired

**Direction Entry (Long):**
1. Green dot fires (squeeze off)
2. Momentum histogram is positive and rising (above zero, increasing)
3. Price > EMA(20)
4. ADX turning up from below 20 (new trend starting)
5. Enter on the first green dot bar

**Direction Entry (Short):**
1. Green dot fires
2. Momentum histogram is negative and falling (below zero, decreasing)
3. Price < EMA(20)

### Exit Rules
**Stop Loss:** Opposite Keltner Channel line at entry. For longs: lower KC line at entry bar. For shorts: upper KC line.

**Take Profit:**
- 2–3R based on pre-trade risk
- Alternatively: exit when momentum histogram peaks and begins declining (histogram fade = momentum exhaustion)

**Trailing Stop:** After 1R gain, trail stop to the entry bar's low (longs) / high (shorts).

### Best Timeframe
- Daily: most reliable for swing trading
- 4h: good for multi-day moves
- 1h: intraday plays on strong compression events
- 15min: valid but more false squeezes

### Best Instruments
- All trending instruments work
- Stocks (especially before earnings or major catalysts): excellent
- Index futures (ES, NQ): the overnight compression before major open = TTM Squeeze signal
- Gold, Oil: works well on daily

### Community Backtest Statistics
TTM Squeeze is widely used but formal backtest statistics are rarely published because results vary significantly by market regime. Community consensus:
- Win rate after squeeze fires with direction filter: 55–65%
- False squeeze rate (fires but no follow-through): 30–40% of firings
- Maximum compression squeezes (all three KC levels): fire with higher reliability, ~65–70% success
- Best performance during high-ADX trending periods post-squeeze release

### Known Weaknesses
- Does not predict direction — requires a separate direction filter (MACD, EMA, price action)
- False firings occur when the market squeezes, briefly pops, then returns to consolidation
- Can stay compressed (red dots) for extended periods (weeks on daily charts) — requires patience
- Entry timing after the squeeze fires is critical — entering too late reduces R:R significantly
- Momentum histogram can be misleading if the initial move is news-driven and quickly retraces

### Confluence Upgrades
1. Maximum compression (all three KC levels compressed): highest-probability setup
2. Volume spike on the first fired candle: confirms real breakout
3. Daily trend alignment before entering intraday squeeze play
4. Wait for one bar of follow-through before entering (reduces false breakout entries)
5. Key level proximity: squeeze firing near a key level (VWAP, prior week high) adds conviction

---

## 9. Opening Range Breakout (ORB)

### Overview
The ORB strategy captures the high and low of the first N minutes of the trading session. These levels represent the "opening range" — the market's initial price discovery zone. When price breaks above the high, it signals bullish momentum. When it breaks below the low, bearish momentum. Invented by Arthur Merrill in the 1960s; remains one of the most reliable intraday strategies.

**Why it works:** The opening 15–30 minutes sets the tone for institutional flow. A directional break beyond this range signals that the dominant institutional bias has emerged.

### Configuration
| Range Period | Notes |
|---|---|
| 5-minute | Earliest signals, highest false breakout rate |
| 15-minute | Most popular for futures; best balance of signal quality and timing |
| 30-minute | More reliable signals, later entry (more price has already moved) |
| 60-minute | Best for high-volatility environments like earnings/FOMC days |

**Session start times:**
- NY session: 9:30 AM ET (stocks) or 8:30 AM CT (CME futures)
- Most futures traders use 9:30–9:45 AM ET as the 15-min ORB window

### Entry Rules
**Long:**
1. Define opening range: high (ORH) and low (ORL) of first 15 minutes after open
2. Price closes a full candle above ORH (close > ORH, not just a wick)
3. Daily bias is bullish (optional: price above prior day close, above prior week high, or daily EMA aligned)
4. Volume on breakout bar > 1.5× session average
5. Entry at the close of the breakout bar (or limit order at ORH retest if preferred)

**Short:**
1. Same setup — price closes below ORL
2. Daily bias is bearish
3. Volume > 1.5× session average

### Exit Rules
**Stop Loss:**
- Tight: 50% of the ORB range below ORH (for longs). Risk is half the range.
- Standard: below ORL (for longs). Risk is the full range.
- Wide: 1× ORB range below ORH. More room but larger risk.

**Take Profit:**
- 1:2 R:R minimum
- Standard target: ORH + (1× ORB range) = 2R
- Extended target: ORH + (2× ORB range) = 3R if momentum is strong

**Time stop:** Exit by 12:00 ET if price hasn't moved toward target. ORB setups that haven't resolved by midday rarely resolve cleanly.

### Best Timeframe
Chart: 5min (for execution and monitoring). Opening range: 15min.

### Best Instruments
- ES / MES (E-mini S&P 500): top pick — high liquidity, clean ORB respect
- NQ / MNQ (Nasdaq 100): more volatile, bigger moves, acceptable
- Crude Oil (CL): strong opening range behavior
- Gold (GC): works but more erratic at open
- SPY, QQQ: proven track record over the last decade
- Individual stocks (earnings days): ORB on high-volume stocks is powerful

### Community Backtest Statistics
| Instrument | Win Rate | Notes |
|---|---|---|
| SPY / QQQ (15-min ORB, directional filter) | ~55–60% | Proven over 10+ years |
| ES futures (15-min ORB) | ~50–57% | Requires daily bias filter |
| Stocks (earnings ORB) | ~60–65% | Higher volatility, larger targets |

The ORB strategy gets killed in choppy, directionless markets. The number-one filter is prior-day trend + daily bias. Taking ORB trades only in the direction of the daily trend significantly improves win rate.

### Known Weaknesses
- False breakouts ("fakeouts"): price briefly breaks ORH/ORL then reverses
- Pre-market gaps that are large make the ORB range less meaningful
- News-driven opens (CPI, NFP, FOMC) create erratic openings — avoid ORB on major news days
- Very tight ORBs (range < 0.3× prior-day ATR) often result in large whipsaws
- Does not work in low-volume markets where the opening range is random noise

### Confluence Upgrades
1. Daily bias filter: only long ORB above prior day close; only short ORB below (most impactful)
2. Volume spike on breakout: 2× session average = high conviction
3. VWAP proximity: if ORH is near VWAP, a breakout above both is stronger
4. Prior day high/low alignment: if ORH breaks out at or near PDH (previous day high), add confluence
5. Wait for pullback + retest of ORH (for longs) before entering — reduces false breakout entries at cost of some trades

---

## 10. Donchian Channel Breakout (Turtle System)

### Overview
The Donchian Channel plots the N-period high and N-period low. Price breaking above the N-day high represents a new high — a momentum signal that the trend is resuming or beginning. Made famous by Richard Donchian and the "Turtle Traders" (Richard Dennis / William Eckhardt). One of the longest-tested trend-following systems in existence (40+ year track record in futures).

**Formula:** Upper = highest(high, N) | Lower = lowest(low, N) | Middle = (Upper + Lower) / 2

### Optimal Parameter Sets

| System | Entry Channel | Exit Channel | Notes |
|---|---|---|---|
| Turtle System 1 (short-term) | 20 days | 10 days | Classic, most tested |
| Turtle System 2 (long-term) | 55 days | 20 days | Fewer signals, larger moves |
| Day trading | 10–20 bars | 5–10 bars | Scaled to intraday bars |
| Swing trading | 20–55 bars | 10–20 bars | Standard retail adaptation |

### Entry Rules (Turtle System 1)
**Long:**
1. Price closes above the 20-day Donchian upper band (new 20-day high)
2. ADX > 18 (optional, reduces false breakouts)
3. Volume > 1.2× vol_ma
4. Previous 20-day breakout did NOT result in a winning trade (filter: skip if prior signal was profitable — reduces pyramiding into extended moves)

**Short:**
1. Price closes below the 20-day Donchian lower band (new 20-day low)
2. Same confirmations as above

**Entry with RSI momentum filter (community upgrade):**
- Long only if RSI > 60 at breakout (momentum confirms)
- Short only if RSI < 40 at breakout

### Exit Rules
**Stop Loss (Turtle standard):** 2× ATR(20) from entry. This is a wide, volatility-adjusted stop designed for daily charts.

**Exit Channel (Turtle standard):** Exit long when price closes below the 10-day Donchian low. Exit short when price closes above the 10-day Donchian high.

**Note on the Turtle exit:** The 10-day channel trailing exit gives back significant profit but ensures you stay in winning trades. For retail traders who want a tighter exit, use 20-day channel for exit instead.

### Best Timeframe
- Daily: primary and most tested
- Weekly: position trading, very long timeframe
- 1h: adapted for futures intraday — use 20-bar and 10-bar versions

### Best Instruments
- Gold and Silver: excellent — strongly trending commodity that works with Turtle system
- Crude Oil: classic Turtle market
- Currencies: trend well on daily
- Bonds: institutional use
- Index futures (ES/NQ): less suitable due to frequent mean-reversion tendency

### Community Backtest Statistics
The Turtle system is one of the most backtested systems in existence. Community consensus:
- Win rate: ~35–45% (typical for trend-following breakout systems)
- Profit factor: ~1.5–2.5 depending on market regime and timeframe
- The system generates large winners (10R+) that offset many small losses
- Works best during trending macro environments (2000s commodity boom, 2020–2022 inflation trade)
- Underperforms in low-volatility, range-bound environments (2017, post-2022 US equities)

**Dual Donchian upgrade:** Fast(20) + Slow(55). Bullish signal when fast upper > slow upper. Filters false breakouts significantly.

### Known Weaknesses
- Low win rate requires psychological discipline (accepting 60%+ loss rate)
- Wide stops = large per-trade risk in dollar terms
- Severely underperforms in ranging/mean-reverting markets
- Multiple consecutive losing signals are normal before a large winner
- The edge has decayed from the 1980s as the strategy became widely known — requires adaptation (shorter periods, tighter stops) for modern markets

### Confluence Upgrades
1. RSI momentum filter: RSI > 60 on long breakouts reduces false breakouts significantly
2. Volume confirmation (1.5× average): eliminates low-conviction breakouts
3. 200 EMA filter: long only above 200 EMA (trend alignment)
4. Dual Donchian (20 + 55): use the 55-day channel as the macro bias filter
5. ATR percentile filter: only trade breakouts when ATR is in the upper 50th percentile (volatility required for trend-following to work)

---

## 11. Momentum Volume Breakout

### Overview
Price breaks to a new N-bar high or low with elevated volume, strong candle body, and trend confirmation. Enters immediately on the breakout bar (no retest required). Different from the Break-Retest strategy (BRT) which waits for a pullback to the broken level.

The setup catches institutional buying/selling on the initial breakout momentum before retail catches up. The volume filter ensures institutional participation is present.

### Entry Rules
**Long:**
1. Price closes above the rolling 20-bar high + 0.1× ATR(14) (new momentum high)
2. Candle body > 0.4× ATR (strong directional candle, not a doji at the high)
3. Volume > 2.0× vol_ma (institutional participation filter)
4. ADX > 20 (trend is present)
5. EMA(20) > EMA(50) (trend alignment)
6. RSI 50–70 (momentum present, not overbought)
7. Session timing: 10:00–14:00 ET for intraday (peak institutional hours)

**Short:**
1. Price closes below rolling 20-bar low − 0.1× ATR
2. Candle body > 0.4× ATR
3. Volume > 2.0× vol_ma
4. ADX > 20
5. EMA(20) < EMA(50)
6. RSI 30–50

### Exit Rules
**Stop Loss:** Below the breakout bar's low (for longs) + 0.3× ATR cushion. OR 1× ATR below entry.

**Take Profit:** 2.0R fixed. Or trail using the 20-bar high as a trailing stop.

**Partial exits:** Take 50% off at 1R, trail the rest with a 0.5× ATR trailing stop.

### Best Timeframe
- 15min–1h: primary
- 5min: acceptable with strict volume filter (2× average is non-negotiable)
- Daily: works for swing breakouts

### Best Instruments
- Stocks with news catalysts: top pick
- Small-cap stocks: volume spikes are more distinctive
- Index futures (ES, NQ): works on momentum breakout days
- Gold: excellent when breaking above multi-day ranges

### Community Backtest Statistics
- Win rate with volume filter: ~45–55%
- Without volume filter: ~35–40% (false breakouts dominate)
- The volume filter (2× average) is the single most impactful improvement to this strategy
- Profit factor with full filter stack: ~1.5–2.0

### Known Weaknesses
- Higher false breakout rate than retest-based strategies (no confirmation wait)
- Should use smaller position size than BRT due to lower reliability
- Volume filter is critical — without it, this strategy does not work
- Susceptible to "trap" breakouts in low-liquidity environments
- After-hours gaps can create false opening breakouts

### Confluence Upgrades
1. Volume 2× filter (non-negotiable)
2. ADX > 20 (non-negotiable)
3. Candle body quality: body should be > 60% of the candle's total range
4. Pre-breakout consolidation: minimum 3–5 bars of tight range before the breakout
5. RVOL (relative volume): volume must be elevated relative to the same time of day on prior sessions

---

## 12. NR4 / NR7 Narrow Range Breakout

### Overview
NR4 (Narrow Range 4): the current bar has the narrowest high-low range of the last 4 bars.
NR7 (Narrow Range 7): the current bar has the narrowest high-low range of the last 7 bars.

Originally researched by Toby Crabel. These patterns signal extreme volatility compression. Markets alternate between compression and expansion. The NR4/NR7 bar is the compression marker — the next bar frequently expands directionally. NR7 bars require more compression than NR4 and historically produce larger subsequent moves.

### Detection Rules
- NR4: `range(current) < range(all of prior 3 bars)` where range = high − low
- NR7: `range(current) < range(all of prior 6 bars)`
- Optimal setup: NR7 + Inside Bar (current bar's high/low is within prior bar's high/low) = maximum compression

### Entry Rules
**Day After NR4/NR7 (most common setup — daily charts)**

Long:
1. NR4 or NR7 bar identified on close
2. Next day: enter buy stop above the NR bar's high
3. Price must be above 89-period SMA (trend filter)
4. ADX may be below 20 (anticipating new trend starting from compression)

Short:
1. NR4 or NR7 bar identified on close
2. Next day: enter sell stop below the NR bar's low
3. Price must be below 89-period SMA

**Same-day entry (intraday):**
1. NR7 bar detected on the current bar close (intraday)
2. Enter breakout stop above/below NR bar with volume confirmation
3. 10 EMA > 20 EMA > 50 EMA (trend alignment for longs)

### Exit Rules
**Stop Loss:** Opposite side of the NR bar. For long entry (above NR high), stop at NR low. Risk = full NR range.

**Take Profit:**
- Crabel classic: hold 1–3 bars (short hold period: NR bars frequently resolve quickly)
- Modern adaptation: exit after 6 bars if not at target, or use 1.5× NR range as TP
- Alternatively: trail using a 3-bar low (for longs)

### Best Timeframe
- Daily: original and most tested (Crabel's research was on daily data)
- 1h–4h: adapted for futures
- 15min: valid with trend filter

### Best Instruments
- Stocks (daily): primary — the pattern is most reliable on equity daily bars
- Futures (all): works well due to clear alternation between trending and consolidating
- Forex (daily): tested and reliable

### Community Backtest Statistics
| Version | Win Rate | Notes |
|---|---|---|
| NR7 + EMA trend filter | ~55–65% | With 10>20>50 EMA alignment |
| NR4 + Inside Day | ~50–58% | Combined compression signal |
| NR7 standalone | ~48–55% | Without trend filter |

NR7 bars produce stronger follow-through than NR4 bars in community testing. The combined NR7 + Inside Bar is the highest-probability version.

### Known Weaknesses
- Low frequency: NR7 bars do not appear often, especially with trend filter applied
- The breakout can be a fake: price tags the entry level then reverses
- Works best when the prior trend is clear — ambiguous markets generate false NR breakouts
- Does not specify direction — requires a trend filter to take directional entries

### Confluence Upgrades
1. NR7 + Inside Bar combination: maximum compression, highest historical follow-through
2. EMA alignment: 10 > 20 > 50 for longs (required for meaningful edge)
3. Volume expansion: first bar after NR should show volume spike
4. Trend context: NR7 within established trend = continuation; NR7 at key reversal level = potential reversal
5. Time of week: NR7 on Tuesday–Thursday has better follow-through than Monday/Friday

---

## 13. RSI Pullback in Trend (Continuation)

### Overview
In an established uptrend, the RSI pulls back to a moderate oversold level (40–55 for bull trends), then turns back up. This catches the institutional "buy the dip" behavior in trending markets. Unlike the RSI(2) mean reversion strategy which works on any dip, this strategy requires an established trend structure.

### Optimal Parameters
- RSI period: 14 (standard)
- Bull trend pullback zone: RSI drops to 40–55 range
- Bear trend rally zone: RSI rallies to 45–60 range
- Required: Price above EMA(50) and ADX > 20

### Entry Rules
**Long:**
1. Price is above EMA(50) (confirmed uptrend)
2. ADX > 20 (trend has sufficient strength)
3. RSI(14) pulls back to the 40–55 range
4. RSI(14) turns back up (current RSI > prior bar RSI)
5. Confirmation: bullish candle with close > open
6. Volume on the entry candle > prior bar volume

**Short:**
1. Price below EMA(50)
2. ADX > 20
3. RSI(14) rallies to 45–60
4. RSI(14) turns back down
5. Bearish candle confirmation

### Exit Rules
**Stop Loss:** Below the recent swing low (for longs) − 0.3× ATR

**Take Profit:** Recent swing high (risk-defined exit) or 2.5R. In strong trends, use a trailing stop on the EMA(20).

### Best Timeframe
- 1h–Daily: primary
- 4h: ideal for swing trades

### Best Instruments
- Large-cap stocks (daily): excellent — strong trending tendency
- Index futures (daily): works well
- Gold (daily): strong uptrend structure

### Community Backtest Statistics
- Win rate: 55–65% in established trends
- Degrades to 35–45% when ADX filter is absent (choppy markets generate many false signals)
- The ADX > 20 filter is the most critical for this strategy's reliability

### Known Weaknesses
- In the strongest trending phases, RSI never pulls back to 40–55 — the strategy misses the best momentum runs
- In choppy markets (ADX < 20), RSI oscillates through the 40–55 zone constantly, generating noise
- Lagging: by the time RSI pulls back to the zone, significant price movement has already occurred

### Confluence Upgrades
1. ADX > 25 (stronger trend = better results)
2. Higher-timeframe trend alignment (e.g., weekly EMA direction)
3. Fibonacci level at the pullback zone: RSI pullback coincides with 38.2% or 50% price retracement
4. VWAP/key level: pullback ends near VWAP or key daily level
5. Volume: entry bar volume > prior bar (institutional re-entry signal)

---

## 14. MACD + RSI Combined (QuantifiedStrategies)

### Overview
A mean-reversion combo strategy that uses both MACD and RSI to identify high-probability entries. Verified by QuantifiedStrategies.com with extensive backtesting. Most effective on equities in range-bound or mildly trending conditions. The combination filters out the significant false signals that MACD or RSI generate in isolation.

### Entry Rules (MACD + RSI Mean Reversion — SMH / semiconductor focused)
**Long:**
1. MACD histogram is negative (short-term price below trend)
2. RSI(2) or RSI(3) drops below 30 (oversold)
3. Third filter (mean reversion): price is within a recent distribution range (not making new 52-week lows)
4. Enter at close

**Exit:**
- Exit when MACD histogram crosses back positive
- Or exit when RSI(2) crosses above 70
- Whichever comes first

### MACD + RSI for Commodities Variant
**Long:**
1. MACD(12,26,9) generates a bullish crossover (fast above slow)
2. RSI(14) rises above 50 (from below) confirming momentum
3. Combined signal — both indicators align

**Short:**
1. MACD bearish crossover
2. RSI drops below 50

This version was shown to significantly outperform the S&P GSCI commodity benchmark (2010–2019 study).

### Best Timeframe
- Daily: primary (all QuantifiedStrategies backtests use daily bars)

### Best Instruments
- SMH (semiconductor ETF): 73% win rate, 0.88% avg gain, 235 trades
- Commodity futures (MACD+RSI commodity version): verified outperformance vs benchmark

### Community Backtest Statistics (QuantifiedStrategies.com)
| Setup | Instrument | Win Rate | Avg Gain | Notes |
|---|---|---|---|---|
| MACD + RSI + MR filter | SMH | 73% | 0.88%/trade | 235 trades, includes commissions/slippage |
| MACD histogram (12,26,9) | S&P 500 | — | 0.95%/trade | PF 4.22 |
| MACD histogram + RSI(2) | S&P 500 | — | 0.76%/trade | PF 2.45, more trades |

### Known Weaknesses
- Requires both indicators to confirm: reduces trade frequency significantly
- The mean reversion third filter is vague (the exact rule is behind their paywall)
- Less effective in strongly trending bull markets where MACD stays positive for extended periods

### Confluence Upgrades
1. Triple RSI: use RSI(3), RSI(7), RSI(14) — enter only when all three are oversold (< 30). This is the "Triple RSI" strategy from QuantifiedStrategies.
2. Add volume: entry bar shows above-average volume (institutional presence)
3. Add sector ETF confirmation: MACD+RSI on the sector ETF confirms the individual stock signal

---

## 15. Linda Raschke 3-10-16 MACD (Fast MACD)

### Overview
Linda Raschke popularized this MACD variant using much faster settings than the standard 12/26/9. The 3-10-16 MACD detects trend changes 5–10 candles earlier than standard settings. Makes it ideal for intraday and scalping applications where speed matters. Works across 5-minute (scalping) to daily (swing trading) timeframes.

### Settings
- Fast EMA: 3
- Slow EMA: 10
- Signal Line: 16 (SMA preferred over EMA for the signal line)

### Entry Rules
**Long:**
1. 3-10-16 MACD histogram crosses from negative to positive
2. Price above SMA(20) (trend filter)
3. RSI 40–60 (entering early in momentum, not late)
4. Volume above average

**Short:**
1. Histogram crosses negative
2. Price below SMA(20)
3. RSI 40–60

### Exit Rules
**Exit:** First bar where histogram starts declining after a peak (momentum fade). Do NOT wait for histogram to cross zero — that gives back too much gain.

**Stop Loss:** Most recent swing low (longs) or swing high (shorts), 0.5× ATR cushion.

### Best Timeframe
- 5min: scalping
- 15–30min: intraday trading
- Daily: swing trading for early trend detection

### Best Instruments
- All — this is a universal signal enhancement
- Particularly valuable for futures intraday where 5–10 candle earlier detection materially improves R:R

### Community Backtest Statistics
The 3-10-16 MACD as a standalone strategy is typically tested in the same way as standard MACD. The primary advantage is entry timing, not win rate improvement. In combination with the standard 12/26/9:
- Use the 3-10-16 for entries (timing)
- Use the 12/26/9 for trend direction (bias)
- This two-MACD approach is referenced by advanced traders in the TradingView community

### Known Weaknesses
- More signals = more false signals. Higher frequency than standard MACD.
- Requires more active management due to faster signal generation
- The early-entry benefit can turn into a false-early-entry problem in choppy conditions

### Confluence Upgrades
1. Use alongside standard MACD(12,26,9) as the trend bias; 3/10/16 for entry timing
2. Volume filter on the crossover bar
3. ADX > 20 to confirm a trend exists before using the early signal

---

## STRATEGY PERFORMANCE COMPARISON TABLE

| # | Strategy | Type | Win Rate | Profit Factor | Best Timeframe | Best Instrument | ADX Filter | Key Weakness |
|---|---|---|---|---|---|---|---|---|
| 1 | EMA Crossover | Trend | 45–55% | 1.3–2.0 | Daily / 1h | Stocks, Gold | > 18 | Lags, whipsaws in chop |
| 2 | SuperTrend | Trend | 40–67% | ~1.3–1.8 | 1h–Daily | Gold, Futures | > 18 | 40% WR standalone; needs filters |
| 3 | RSI(2) Mean Reversion | MR | 75–91% | 2.3–3.0 | Daily only | SPY, QQQ, stocks | N/A | Daily only; no forex |
| 4 | MACD Momentum | Trend/Mom | 40–50% | 1.5–4.22 | 1h–Daily | Stocks, Gold | > 18 | Lags; fails in chop |
| 5 | BB Mean Reversion | MR | 35–65% | ~1.5–2.0 | 15min–Daily | MES, Stocks | < 22 | Band-walking risk |
| 6 | BB Breakout | Breakout | 45–55% | ~1.5–2.0 | Daily | All | N/A | False breakouts |
| 7 | VWAP Intraday | MR/Trend | 55–65% | ~1.5–2.0 | 5–15min | ES, NQ, Stocks | < 25 | Intraday only |
| 8 | TTM Squeeze | Breakout | 55–65% | ~1.5–2.5 | 1h–Daily | All | Turning up | Direction unknown until fire |
| 9 | ORB | Breakout | 55–60% | ~1.5–2.0 | 15min entry | ES, SPY, NQ | N/A | False breaks, news days |
| 10 | Donchian (Turtle) | Trend | 35–45% | 1.5–2.5 | Daily | Gold, Oil, Futures | > 18 | Low WR; wide stops |
| 11 | Momentum Volume | Breakout | 45–55% | ~1.5–2.0 | 15min–1h | Stocks, ES | > 20 | No retest = higher false rate |
| 12 | NR4/NR7 | Breakout | 48–65% | ~1.4–2.0 | Daily | All | N/A | Low frequency |
| 13 | RSI Pullback | Continuation | 55–65% | ~1.5–2.0 | 1h–Daily | Stocks, Gold | > 20 | RSI never oversold in strong trends |
| 14 | MACD + RSI | MR/Combo | 73% | ~2.45–4.22 | Daily | SMH, Stocks | N/A | Paywall rules; slow |
| 15 | Raschke 3-10-16 | Trend/Early | ~40–52% | ~1.3–1.8 | 5min–Daily | All futures | > 18 | More signals = more noise |

---

## CONFLUENCE FILTER MASTER LIST

The following filters apply across ALL strategies. Each adds incremental edge. Use the confluence checklist from RESEARCH.md (Section 13) to score setups.

### Trend Confirmation Filters
- ADX > 20 or > 25: most universal and impactful filter
- EMA alignment: fast > slow > slowest (e.g., 9 > 21 > 50 > 200)
- Higher-timeframe trend agreement: daily trend aligns with intraday signal

### Momentum Filters
- RSI in appropriate range (not overbought/oversold at entry)
- MACD histogram positive/negative matches direction
- Price above/below VWAP (intraday)

### Volume Filters
- Volume > 1.2–2× vol_ma (scale by strategy aggressiveness)
- RVOL (relative volume vs. same time of prior sessions) > 1.3×
- Volume declining on retracements, increasing on breakouts (accumulation pattern)

### Volatility Filters
- ATR percentile: use breakout strategies only when ATR > 50th percentile
- Use mean-reversion strategies when ATR < 50th percentile
- VIX: avoid intraday mean-reversion strategies when VIX > 25

### Session / Time Filters
- Trade between 9:45–11:30 and 13:00–15:00 ET for US futures
- Tuesday–Thursday: best performance days (QuantifiedStrategies and community consensus)
- Avoid first 15min after open (noise), last 30min before close (position squaring), and 30min around major macro events

### Key Level Filters
- Entry near VWAP, PDH/PDL, weekly highs/lows = higher probability
- Round numbers (price at 4500, 2000, etc.) act as S/R
- Prior major swing highs/lows = institutional S/R levels

---

## PARAMETER OPTIMIZATION GUIDELINES

### How to Avoid Overfitting
1. Use the default / community-standard parameters first (listed in each strategy above)
2. Change only ONE parameter at a time; observe the impact
3. Require a minimum of 100 trades in the backtest for any statistical significance
4. Out-of-sample test: use last 20–30% of available data exclusively for final validation
5. Walk-forward testing: roll 6-month windows, optimize, then test on the next 3 months
6. Profit should not cliff-drop when parameters are adjusted ±10–20% (robustness test)

### ATR Parameter Guidance (applies across strategies)
| ATR Period | Sensitivity | Use Case |
|---|---|---|
| 7 | High | Fast intraday scalping |
| 10 | Balanced | Default — all strategies |
| 14 | Standard | Swing trading, daily bars |
| 20 | Smooth | Position trading, weekly context |

### RSI Period Quick Reference
| Period | Sensitivity | Best Use |
|---|---|---|
| 2–3 | Very high | Mean reversion (Connors-style), daily only |
| 7 | High | Short-term momentum, 1h |
| 14 | Standard | All strategies, default |
| 21 | Smooth | Longer-term trend momentum |

---

## SOURCES

- [TradingView Scripts Library](https://www.tradingview.com/scripts/)
- [QuantifiedStrategies.com — 200+ Free Strategies](https://www.quantifiedstrategies.com/trading-strategies-free/)
- [QuantifiedStrategies RSI 91% Win Rate](https://www.quantifiedstrategies.com/rsi-trading-strategy/)
- [QuantifiedStrategies MACD + RSI 73% Win Rate](https://www.quantifiedstrategies.com/macd-and-rsi-strategy/)
- [QuantifiedStrategies RSI(2) on SPY](https://www.quantifiedstrategies.com/rsi2-on-spy/)
- [Supertrend Indicator Settings — Netpicks](https://www.netpicks.com/supertrend-indicator/)
- [Liberated Stock Trader — 4,052 SuperTrend Trades](https://www.liberatedstocktrader.com/supertrend-indicator/)
- [TTM Squeeze — TrendSpider Learning Center](https://trendspider.com/learning-center/introduction-to-ttm-squeeze/)
- [Bollinger Band Complete Guide 2025 — MindMathMoney](https://www.mindmathmoney.com/articles/master-bollinger-bands-the-complete-trading-guide-2025)
- [VWAP Entry Strategies — LuxAlgo](https://www.luxalgo.com/blog/vwap-entry-strategies-for-day-traders/)
- [ORB Strategy — Edgeful Blog](https://www.edgeful.com/blog/posts/orb-indicator-tradingview)
- [ORB Strategy Explained — FluxCharts](https://www.fluxcharts.com/articles/trading-strategies/common-strategies/opening-range-breakout)
- [ORB Filters and Stops — TradersMasterMind](https://tradersmastermind.com/trading-strategy-opening-range-breakout/)
- [Donchian Channel Breakout — LuxAlgo](https://www.luxalgo.com/blog/donchian-channels-breakout-and-trend-following-strategy/)
- [Donchian Channel Guide — TradingWithRayner](https://www.tradingwithrayner.com/donchian-channel-indicator/)
- [NR4/NR7 Strategy — Elearnmarkets](https://blog.elearnmarkets.com/nr4-and-nr7-trading-strategy-setup/)
- [NR4/NR7 with Breakouts — LuxAlgo TradingView](https://www.tradingview.com/script/sA6AFgk7-NR4-NR7-with-Breakouts-LuxAlgo/)
- [MACD Linda Raschke Settings — MindMathMoney](https://www.mindmathmoney.com/articles/linda-raschke-trading-strategy-macd-indicator-settings-for-trading-stocks-forex-and-crypto)
- [Top 10 Algo Strategies 2025 — LuxAlgo](https://www.luxalgo.com/blog/top-10-algo-trading-strategies-for-2025/)
- [QuantVPS — Top 7 Pine Script Strategies](https://www.quantvps.com/blog/top-7-pine-script-strategies)
- [Indicators 101 — Best TradingView Indicators 2025](https://indicators101.com/best-tradingview-indicators-for-2025-proven-settings-real-examples-and-copy-ready-rules/)
