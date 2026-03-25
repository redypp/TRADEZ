# TRADEZ — Strategy-to-Market Mapping Reference
> Compiled: 2026-03-24 | Comprehensive algorithmic trading reference for all instruments and strategy combinations.
> Sources: CME Group, QuantifiedStrategies, NinjaTrader, Edgeful, MetroTrade, FuturesHive, QuantVPS, Barchart, WisdomTree, World Gold Council, SSRN, and CFTC research.

---

## TABLE OF CONTENTS

1. [Instrument Profiles — Quick Reference Table](#1-instrument-profiles)
2. [Equity Index Futures (ES/MES, NQ/MNQ, YM/MYM)](#2-equity-index-futures)
3. [Metals Futures (GC/MGC, SI/SIL, HG, PL)](#3-metals-futures)
4. [Energy Futures (CL, NG)](#4-energy-futures)
5. [Individual Stocks (Large Cap, Small Cap, Growth vs Value)](#5-individual-stocks)
6. [ETFs (SPY, QQQ, GLD, SLV, USO, TLT)](#6-etfs)
7. [Strategy × Market Combination Matrix](#7-strategy-market-combination-matrix)
8. [Head-to-Head Strategy Comparisons](#8-head-to-head-strategy-comparisons)
9. [Correlation Matrix and Diversification](#9-correlation-matrix)
10. [Multi-Asset Portfolio Construction for Retail Algos](#10-multi-asset-portfolio-construction)
11. [Key Driver Events Calendar](#11-key-driver-events-calendar)
12. [Implementation Recommendations for TRADEZ](#12-implementation-recommendations)

---

## 1. Instrument Profiles

### Master Reference Table

| Instrument | Symbol | Exchange | Contract Value | Tick Value | ATR % of Price | Mean Rev. Tendency | Trend Following Suitability | Best Time (ET) | Key Event |
|---|---|---|---|---|---|---|---|---|---|
| E-mini S&P 500 | ES | CME | $50/pt | $12.50/tick | ~0.5–0.8% | HIGH | MODERATE | 9:30–11:30 AM | FOMC, CPI |
| Micro E-mini S&P | MES | CME | $5/pt | $1.25/tick | ~0.5–0.8% | HIGH | MODERATE | 9:30–11:30 AM | FOMC, CPI |
| E-mini Nasdaq | NQ | CME | $20/pt | $5.00/tick | ~0.9–1.4% | LOW-MED | HIGH | 9:30–11:30 AM | Tech earnings, FOMC |
| Micro E-mini NQ | MNQ | CME | $2/pt | $0.50/tick | ~0.9–1.4% | LOW-MED | HIGH | 9:30–11:30 AM | Tech earnings |
| E-mini Dow | YM | CBOT | $5/pt | $5.00/tick | ~0.4–0.7% | HIGH | MODERATE | 9:30–11:30 AM | FOMC, econ data |
| Micro E-mini Dow | MYM | CBOT | $0.50/pt | $0.50/tick | ~0.4–0.7% | HIGH | MODERATE | 9:30–11:30 AM | FOMC, econ data |
| Gold Futures | GC | COMEX | 100 oz / $100/pt | $10.00/tick | ~0.7–1.2% | LOW-MED | HIGH | 8:20 AM–1:30 PM | CPI, FOMC, geopolitics |
| Micro Gold | MGC | COMEX | 10 oz / $10/pt | $1.00/tick | ~0.7–1.2% | LOW-MED | HIGH | 8:20 AM–1:30 PM | CPI, FOMC |
| Silver Futures | SI | COMEX | 5,000 oz / $50/pt | $25.00/tick | ~1.5–2.5% | LOW | VERY HIGH | 8:00 AM–12:00 PM | CPI, industrial data |
| Micro Silver | SIL | COMEX | 1,000 oz / $5/pt | $5.00/tick | ~1.5–2.5% | LOW | VERY HIGH | 8:00 AM–12:00 PM | CPI, industrial data |
| Copper Futures | HG | COMEX | 25,000 lbs | $12.50/tick | ~1.0–1.8% | LOW | HIGH | 8:00 AM–2:00 PM | China PMI, infrastructure data |
| Platinum Futures | PL | NYMEX | 50 oz | $5.00/tick | ~1.0–1.5% | LOW-MED | HIGH | 8:00 AM–1:00 PM | Auto industry, ETF flows |
| Crude Oil WTI | CL | NYMEX | 1,000 bbl / $10/tick | $10.00/tick | ~1.5–2.5% | LOW | HIGH | 9:00 AM–2:30 PM | EIA Inventory (Wed) |
| Natural Gas | NG | NYMEX | 10,000 mmBtu | $10.00/tick | ~3.0–6.0% | VERY LOW | VERY HIGH | 8:00 AM–12:00 PM | EIA Storage (Thu) |
| SPY ETF | SPY | NYSE | ~$550/share | $0.01 | ~0.5–0.8% | HIGH | MODERATE | 9:30–11:30 AM | FOMC, CPI |
| QQQ ETF | QQQ | NASDAQ | ~$470/share | $0.01 | ~0.8–1.2% | MODERATE | HIGH | 9:30–11:30 AM | Tech earnings |
| GLD ETF | GLD | NYSE | ~$280/share | $0.01 | ~0.7–1.2% | LOW-MED | HIGH | 8:20 AM–1:30 PM | CPI, FOMC |
| SLV ETF | SLV | NYSE | ~$28/share | $0.01 | ~1.5–2.5% | LOW | VERY HIGH | 8:00 AM–12:00 PM | CPI |
| USO ETF | NYSE | NYSE | ~$70/share | $0.01 | ~1.5–2.5% | LOW | HIGH | 9:00 AM–2:30 PM | EIA Inventory |
| TLT ETF | NYSE | NASDAQ | ~$90/share | $0.01 | ~0.8–1.2% | MODERATE | MODERATE | 8:00–10:00 AM | FOMC, Treasury auctions |
| AAPL | NASDAQ | — | varies | $0.01 | ~1.0–1.8% | HIGH | MODERATE | 9:30–11:00 AM | Earnings, product events |
| MSFT | NASDAQ | — | varies | $0.01 | ~0.8–1.3% | HIGH | MODERATE | 9:30–11:00 AM | Earnings, Azure data |
| TSLA | NASDAQ | — | varies | $0.01 | ~2.5–4.5% | LOW-MED | HIGH | 9:30–11:00 AM | Deliveries, Elon news |

**ATR% interpretation:** Percentage of current price that the average true range represents on a daily basis.
**Mean Rev. Tendency:** How strongly the instrument mean-reverts in range-bound conditions (HIGH = strong mean-reversion tendency).
**Trend Following Suitability:** How well the instrument sustains directional trends long enough for trend-following strategies.

---

## 2. Equity Index Futures

### 2.1 ES / MES (S&P 500)

**Contract specs:**
- ES: $50 per point, $12.50 per 0.25-tick
- MES: $5 per point, $1.25 per 0.25-tick (1/10th of ES)
- Margin: ~$13,800 (ES), ~$1,380 (MES) as of 2025
- Daily traded volume: ~2 million contracts (ES)

**Volatility profile:**
- Typical daily range: 30–50 points, equating to $1,500–$2,500 per ES contract
- ATR% of price: approximately 0.5–0.8% on a daily basis
- Intraday volatility surges at 9:30–10:00 AM ET and 3:00–3:30 PM ET
- Pre-lunch consolidation (11:30 AM–1:00 PM) is the choppiest, lowest-conviction window

**Mean reversion vs. trend following:**
- Short-to-medium term: MEAN REVERTING. ES returns to equilibrium after deviations more reliably than commodities.
- Long-term (months): Upward trending with structural bull bias, but punctuated by sharp reversals.
- This dual nature means the strategy used must match the timeframe. Intraday: favor mean reversion. Swing/position: use trend with strong regime filter.

**Best strategies for ES/MES:**
1. VWAP Mean Reversion (5–15 min) — exploits institutional VWAP execution patterns; strongest documented edge
2. Opening Range Breakout (15–30 min) — best with VIX 15–25, align with prevailing trend
3. Break & Retest (15 min) — currently active in TRADEZ; validated for structure-based momentum
4. Bollinger Band Mean Reversion (15 min–1h) — suited to ES's range-bound intraday character
5. EMA Crossover + ADX (1h) — use only in clearly trending sessions (ADX > 25)

**Avoid for ES:**
- Donchian Breakout on intraday (too many false breakouts in mean-reverting market)
- Pure trend following without regime filter on timeframes under 4 hours

**Key drivers:**
- FOMC decisions and statements (highest impact)
- CPI / PPI inflation prints
- Non-farm Payrolls (NFP) — first Friday of each month, 8:30 AM ET
- Earnings from S&P 500 mega-caps (AAPL, MSFT, NVDA)
- VIX level: Strategy regime filter is critical. Use VIX bands to adjust all parameters.

**Algo-specific notes:**
- ES has the deepest order book of any futures market — slippage is minimal
- MES is ideal for retail algo testing with real market microstructure
- Roll quarterly (March, June, September, December); roll 7 days before third Friday

---

### 2.2 NQ / MNQ (Nasdaq 100)

**Contract specs:**
- NQ: $20 per point, $5.00 per 0.25-tick
- MNQ: $2 per point, $0.50 per 0.25-tick
- Margin: ~$21,000 (NQ), ~$2,100 (MNQ) as of 2025
- Daily traded volume: ~600,000 contracts (NQ)

**Volatility profile:**
- Typical daily range: 100–200+ points; $2,000–$4,000 per NQ contract
- ATR% of price: approximately 0.9–1.4% daily — nearly double ES
- On February 7, 2025, MNQ alone moved a 410-point range in a single session
- NQ overshoots support/resistance by 10–20 points before snapping back — important for stop placement
- Higher overnight volatility due to tech earnings and news flow

**Mean reversion vs. trend following:**
- NQ is MORE trend-prone than ES due to momentum-driven tech composition
- Extended unidirectional moves of 30–50 points without meaningful retracement are common
- Tech-driven momentum creates better breakout and trend-following conditions than ES
- However, reversals are violent — trend strategies need wider stops (2–3x ATR minimum)

**Best strategies for NQ/MNQ:**
1. Momentum Breakout (15 min–1h) — exploits NQ's directional bias
2. EMA Crossover + ADX (1h) — captures multi-hour trends well
3. Supertrend (1h) — ATR-based trailing stop suits NQ's volatile trend structure
4. Opening Range Breakout (15 min) — NQ's morning volatility surge is strong
5. MACD Momentum (1h–4h) — medium-term trend confirmation

**Avoid for NQ:**
- VWAP Mean Reversion — NQ trends away from VWAP too aggressively in momentum sessions
- Bollinger Band MR on small timeframes — false reversals are frequent

**Key drivers:**
- Tech sector earnings (AAPL, MSFT, NVDA, META, AMZN, GOOGL)
- FOMC (same as ES but amplified response)
- AI/semiconductor news
- CPI/PPI (rate-sensitive for growth tech valuations)

**Algo-specific notes:**
- NQ is the preferred market for prop firm challenges due to range and liquidity
- Requires 1.5–2x wider stops vs. ES strategies — never directly copy ES parameters to NQ
- ATR-relative parameter scaling is mandatory

---

### 2.3 YM / MYM (Dow Jones 30)

**Contract specs:**
- YM: $5 per point, $5.00 per tick (1-point minimum move)
- MYM: $0.50 per point, $0.50 per tick
- Tracks price-weighted DJIA (30 mega-caps, more defensive)
- Volume: lower than ES and NQ

**Volatility profile:**
- Typical daily range: 200–400 Dow points (~$1,000–$2,000 per YM)
- ATR% of price: approximately 0.4–0.7% — LOWEST of the equity index trio
- Price-weighting means high-priced stocks (UNH, GS, AAPL) have outsized influence
- More defensive sector exposure (industrials, financials, healthcare) than NQ

**Mean reversion vs. trend following:**
- Similar to ES but slightly less momentum-prone
- Industrial/financial composition means more sensitivity to yield curve and bond markets
- Lower volatility makes it the most "stable" equity index for mean-reversion algos

**Best strategies for YM/MYM:**
1. VWAP Mean Reversion — same logic as ES, supported by lower ATR%
2. Break & Retest — works on key DJIA round numbers (historical significance)
3. EMA Crossover + ADX — for trending sessions

**Key drivers:**
- Same as ES but with higher weighting on Boeing (BA), Goldman Sachs (GS), UnitedHealth (UNH)
- Industrial production data, ISM Manufacturing
- Financial sector earnings

**Algo-specific notes:**
- MYM is the least commonly used micro contract — ES/MES typically preferred for algo testing
- Price-weighting creates occasional divergences from SPY/ES that can be exploited

---

## 3. Metals Futures

### 3.1 GC / MGC (Gold)

**Contract specs:**
- GC: 100 troy oz, $100 per $1/oz move, $10.00 per $0.10 tick
- MGC: 10 troy oz, $10 per $1/oz move, $1.00 per $0.10 tick
- Current price range: ~$2,600–$3,200/oz (March 2026)
- Margin: GC ~$8,000–$12,000 (varies with volatility); MGC ~$800–$1,200

**Volatility profile:**
- Typical daily range: $15–$25/oz; $1,500–$2,500 per GC contract
- ATR% of price: approximately 0.7–1.2% daily
- During geopolitical stress or Fed surprises: range expands to $40–$80/oz
- Near-24-hour trading (Sunday evening through Friday afternoon ET)
- Highest activity: 8:20 AM–1:30 PM ET (US session, COMEX pit hours)
- Secondary spike: London open (3:00–5:00 AM ET)

**Mean reversion vs. trend following:**
- TREND FOLLOWING IS SUPERIOR for gold. This is the most consistently validated finding:
  - Backtested 1971–2021: $100K grew to $10M with 12-month MA system vs. $4M buy-and-hold
  - Gold's macro-driven, multi-year trends (inflation regimes, geopolitical cycles) make it ideal for trend systems
  - The 250-day moving average provides excellent trend definition for position-sized entries
- Mean reversion DOES work intraday: 1–2% extensions from VWAP create reliable reversion setups
  - Anchored VWAP + 2-SD bands reversed gold 5 consecutive times before a genuine breakout
  - VWAP mean reversion on 5-min/15-min is legitimate — but only in non-trending sessions
- Key distinction: Use trend following on daily/weekly timeframes, mean reversion intraday

**Best strategies for GC/MGC:**
1. Donchian Channel Breakout (Daily) — gold is the canonical Donchian market; long moves reward asymmetry
2. EMA Crossover + ADX (1h–Daily) — captures intermediate trends; add 50/200 MA for higher conviction
3. Supertrend (1h–Daily) — ATR-based trailing handles gold's volatile trend structure
4. Break & Retest (15 min) — key structural levels (previous highs, round numbers at $100 intervals) hold well
5. VWAP Mean Reversion (5–15 min) — intraday sessions only; regime-filter required
6. Bollinger Band Mean Reversion (1h) — valid in consolidation phases; high win rate but small edge

**Avoid for gold:**
- High-frequency scalping on 1-min — algorithmic activity (HFT is 24% of gold volume) creates unpredictable noise
- Mean reversion on multi-day timeframes during macro trend periods — will get trapped

**Key drivers:**
1. CPI / PCE inflation data — most powerful driver; gold accelerates on high prints
2. FOMC rate decisions and Powell statements — real interest rates are gold's primary driver
3. DXY (US Dollar Index) — gold inversely correlated ~-0.40 with DXY
4. Geopolitical risk events (war, sanctions, banking crises)
5. Central bank buying (structural demand floor)
6. ETF flows (GLD/IAU inflows/outflows)
7. CFTC Commitment of Traders (CoT) — watch commercial vs. speculative positioning

**Algo-specific notes:**
- ATR 10-day above $30 → reduce position size
- Stop placement: 1.5–2x ATR for trend entries; 1–1.5x ATR for intraday mean reversion
- Contract roll: Monthly expiration; major rolls occur Feb, Apr, Jun, Aug, Oct, Dec
- MGC is the ideal vehicle for TRADEZ to add gold exposure (matches MES risk profile)
- VWAP resets daily at COMEX open (7:20 AM CT / 8:20 AM ET)

---

### 3.2 SI / SIL (Silver)

**Contract specs:**
- SI (Full): 5,000 oz, $50 per $0.01/oz move, minimum tick $25.00
- SIL (Micro): 1,000 oz, $10 per $0.01/oz move, minimum tick $5.00
- Current price range: ~$28–$35/oz (March 2026)

**Volatility profile:**
- Typical daily range: ATR% approximately 1.5–2.5% — highest among metals
- Silver is the most volatile of the four metals listed here
- Silver's smaller market cap (vs. gold) amplifies moves — industrial demand + monetary demand
- YTD: SLV ETF returned +101.70% over 12 months to March 2026 (vs. GLD +47.24%)

**Mean reversion vs. trend following:**
- Similar to gold: trend following works well on higher timeframes, but silver trends more violently
- Mean reversion intraday is viable but requires wider tolerances due to silver's volatility
- Silver has both monetary (follows gold) and industrial (follows copper/economy) demand — this creates two distinct behavioral regimes

**Best strategies for SI/SIL:**
1. Donchian Channel Breakout (Daily/Weekly) — silver's large moves reward asymmetric trend systems
2. EMA Crossover + ADX (Daily) — captures major trends; must use wider ATR stops than gold
3. Gold-Silver Ratio Mean Reversion (multi-day pairs trade) — historically strong cointegrated pair
   - Ratio > 80: buy silver, sell gold (silver historically undervalued)
   - Ratio < 50: buy gold, sell silver
   - ML-filtered version (Gradient Boosting + SVM regime detection) significantly outperforms static approach
4. Supertrend (1h–Daily) — handles volatile trend structure

**Avoid for silver:**
- Tight stop strategies — silver will stop out almost any intraday system with normal stops
- VWAP mean reversion without very wide tolerance bands

**Key drivers:**
- Gold price direction (primary correlation ~+0.85 with gold)
- Industrial demand: manufacturing PMI, EV battery demand, solar panel growth
- CPI/inflation data (monetary demand channel, same as gold)
- Gold-Silver ratio position (> 80 historically bullish for silver outperformance)

**Algo-specific notes:**
- SIL margin is lower but volatility in P&L terms is very high — size at 50% of comparable gold position
- Silver "meme trade" risk (retail-driven squeezes) conflicts with systematic models — size conservatively
- Academic research (SSRN 2025) confirms ML-enhanced gold-silver pair trading outperforms static statistical arbitrage

---

### 3.3 HG (Copper)

**Contract specs:**
- Full contract: 25,000 lbs, $12.50 per $0.0005/lb tick
- Current price: ~$4.00–$5.00/lb
- No CME micro contract; nearest alternative is global copper ETF exposure

**Volatility profile:**
- Typical ATR%: approximately 1.0–1.8% daily
- Copper had the highest buy-and-hold return (47.75%) from Jan 2020 to Sep 2021 among metals studied
- Strongly driven by China economic activity (China = ~50% of global copper demand)

**Mean reversion vs. trend following:**
- Primarily a trend-following market, driven by economic cycles
- RSI-based algo systems were BEATEN by buy-and-hold for copper — meaning momentum/breakout outperforms oscillator-based approaches
- Copper's macro cycle dependence means multi-week and multi-month trends are the primary opportunity

**Best strategies for HG:**
1. Donchian Channel Breakout (Weekly/Monthly) — multi-month cycles respond well
2. EMA Crossover (Daily) — 50/200 MA crossover captures major macro trend shifts
3. Fundamental momentum — trade in direction of China PMI trend

**Key drivers:**
- China PMI (manufacturing), GDP data
- Infrastructure spending bills (US, EU, China)
- EV adoption rate and battery technology
- USD strength (like gold, inversely correlated)
- Chile/Peru mining production data

**Algo-specific notes:**
- Copper does NOT have a liquid micro contract — retail algos should access via HG itself or ETFs (CPER, COPX)
- Lower HFT participation than gold — more accessible for medium-frequency algos
- RSI and Keltner Channel algorithms underperformed buy-and-hold for copper in 2020–2021 research

---

### 3.4 PL (Platinum)

**Contract specs:**
- Full contract: 50 oz, $5.00 per $0.10/oz tick
- Current price: ~$950–$1,100/oz

**Volatility profile:**
- ATR%: approximately 1.0–1.5% daily
- Less liquid than gold or silver — wider spreads during off-hours

**Mean reversion vs. trend following:**
- RSI system delivered 22.4% excess returns over buy-and-hold (2020–2021 research)
- Keltner Channel (ATR-based, 60-min bars, 1.5x ATR multiplier): outperformed by 64.72%
- Both long and short algo trades profitable — platinum trends in both directions

**Best strategies for PL:**
1. Keltner Channel Squeeze (1h, 1.5x ATR) — validated by academic research for platinum
2. RSI Pullback in Trend (Daily) — 22.4% excess return documented
3. EMA Crossover + ADX (Daily)

**Key drivers:**
- Automotive industry (catalytic converters — palladium substitute)
- ETF investment demand (platinum ETFs)
- South Africa mining supply disruptions
- Hydrogen fuel cell technology demand

**Algo-specific notes:**
- Lower liquidity means higher slippage — model at 2–3 ticks per round-trip
- Palladium (PA) has similar characteristics and even higher algo returns documented (+326% excess return for RSI system) but extreme volatility

---

## 4. Energy Futures

### 4.1 CL (Crude Oil WTI)

**Contract specs:**
- Full contract: 1,000 barrels, $10.00 per $0.01/bbl tick
- Micro MCL: 100 barrels, $1.00 per $0.01/bbl tick
- Intraday margin: ~$1,625 (CL), ~$165 (MCL)
- Average daily volume: nearly 1.2 million contracts — among the most liquid futures globally
- Trading hours: Sunday–Friday 6:00 PM–5:00 PM ET (1-hour break 5–6 PM)

**Volatility profile:**
- Typical daily range: $1.50–$3.00/bbl; $1,500–$3,000 per CL contract
- ATR%: approximately 1.5–2.5% daily — comparable to silver, significantly higher than ES
- V-shaped reversals are common (not rounded tops/bottoms)
- "Stop-hunting" sweeps above resistance or below support before sharp reversals are a defining feature
- EIA Inventory report causes $1.00+ moves in seconds — extreme event-driven volatility

**Mean reversion vs. trend following:**
- COMPLEX: CL trends on multi-week timeframes (supply cycles, OPEC policy) but is highly mean-reverting intraday
- On 5-minute timeframes, VWAP mean reversion and fade-the-spike work well
- On daily/weekly: Donchian breakout and EMA trend systems produce positive expectancy
- The V-shape reversal character means trend-following algorithms must use wider initial stops

**Best strategies for CL:**
1. Donchian Channel Breakout (Daily) — crude oil is cited as one of the top 3 Donchian markets across 44 tested
2. EMA(9/21) + VWAP (intraday) — combined trend/VWAP confirmation
3. VWAP Mean Reversion (5 min) — fade extreme intraday extensions; best on non-EIA days
4. Supertrend (1h) — ATR-based trailing handles CL's volatile trend/reversal character

**Avoid for CL:**
- Any position held through EIA Inventory report without specific event strategy
- Tight mean-reversion stops — CL's stop hunts will trigger them before the real move

**Key drivers:**
1. EIA Crude Oil Inventory Report — Wednesday 9:30 AM CDT (highest impact weekly event)
2. OPEC+ production decisions and quota announcements
3. Geopolitical events (Middle East, Russia/Ukraine)
4. US Rig Count (Friday 1:00 PM ET, Baker Hughes)
5. USD Index direction (commodity currency relationship)
6. Seasonal demand patterns (summer driving season, winter heating)

**Algo-specific notes:**
- Mandatory rule: be flat 5 minutes before EIA release; do not re-enter until 5 minutes after
- Contract rolls occur monthly; watch for liquidity migration 2–3 days before expiration
- MCL is excellent for testing CL strategies at 1/10th risk
- 72% of CL trades by large participants use algorithms — very competitive market

---

### 4.2 NG (Natural Gas)

**Contract specs:**
- Full contract: 10,000 MMBtu, $10.00 per $0.001/MMBtu tick
- Trading hours: Sunday–Friday 6:00 PM–5:00 PM ET
- Highly seasonal contract — summer/winter demand cycles are structural

**Volatility profile:**
- ATR%: approximately 3.0–6.0% daily — the MOST VOLATILE major futures contract
- Annualized volatility often exceeds 50–70%
- Weather-driven spikes can be 10–20% in a single day
- A significant amount of trading activity occurs in the first second of every minute (TWAP algorithm signature)
- Natural gas is notoriously difficult for retail algo traders due to extreme volatility and news sensitivity

**Mean reversion vs. trend following:**
- Highly seasonal trending behavior (cold snaps, summer heat waves create trend runs)
- Temperature forecast cointegration with prices is strong (academic research confirmed)
- Mean reversion strategies are DANGEROUS in NG due to its tendency toward extreme continuation
- Primarily a fundamental/macro-driven market — pure technicals are weaker here than other markets

**Best strategies for NG:**
1. Seasonal/Fundamental position trading (multi-week) — storage deficit/surplus cycles
2. Donchian Breakout (Daily) — captures major supply/demand trend shifts
3. Supertrend (Daily) — wide ATR multiplier required (2.5–3.0x)

**Avoid for NG:**
- Intraday mean reversion — NG's "gap and go" character destroys fade strategies
- Any strategy without specific EIA Storage Report management
- High-frequency scalping — HFT competition is extreme

**Key drivers:**
1. EIA Natural Gas Storage Report — Thursday 10:30 AM ET (most important weekly event)
2. Weather forecasts — temperature deviations from seasonal norms
3. LNG export capacity and demand
4. Hurricane season (Gulf production disruptions)
5. Winter heating demand / summer cooling demand

**Algo-specific notes:**
- Be flat before EIA Storage Report; avoid trading first 87 seconds after release
- 3–5 day forecasting horizon (using weather models) outperforms pure technical approaches
- NG is NOT recommended for beginner algo traders — ES/MES or MGC first

---

## 5. Individual Stocks

### 5.1 Large Cap: AAPL, MSFT, TSLA

**AAPL (Apple)**
- ATR%: approximately 1.0–1.8% daily
- Mean reversion tendency: HIGH — large-cap, high analyst coverage, institutional bid supports price
- Best strategies: VWAP mean reversion (5–15 min), Bollinger Band MR, RSI Pullback in Trend
- Key events: Earnings (quarterly), product launch events (September iPhone), App Store regulatory news
- Algo notes: AAPL's deep liquidity and tight spreads make it ideal for mean reversion; avoid trend strategies around earnings without specific event logic

**MSFT (Microsoft)**
- ATR%: approximately 0.8–1.3% daily — most stable of the three
- Mean reversion tendency: HIGH — most stable large-cap; Azure cloud growth provides steady fundamental bid
- Best strategies: Moving average mean reversion (MA20), VWAP MR, EMA crossover (1h)
- Key events: Earnings (quarterly), Azure cloud ARR updates, AI/Copilot product announcements
- Algo notes: MSFT is the most "institutional" of the three — mean reversion is the dominant short-term alpha source

**TSLA (Tesla)**
- ATR%: approximately 2.5–4.5% daily — extremely volatile for a large-cap
- Mean reversion tendency: LOW-MODERATE — momentum and narrative-driven; can trend for weeks
- Best strategies: Supertrend (1h–Daily), EMA Crossover + ADX, Momentum Breakout
- Key events: Delivery/production reports (quarterly), Elon Musk tweets/announcements, Cybertruck/energy product events
- Algo notes: TSLA behaves more like a volatile commodity than a stable large-cap; trend-following with wide ATR stops outperforms mean reversion

**General large-cap algo notes:**
- ATR-based trailing stops: Day traders use 5–10 period ATR with 1.5–2.0x multiplier; swing traders use 14–21 period ATR with 2.0–2.5x multiplier
- Survivorship bias is SEVERE for individual stocks — backtesting only current S&P 500 members overstates returns 1–4% annually
- Always use adjusted prices to account for splits, dividends

### 5.2 Small Cap

- Higher ATR% (2–6% daily is common)
- Lower liquidity — slippage is significantly higher; model 3–5 ticks per round-trip minimum
- Mean reversion is WEAKER — thin order book means deviations persist longer
- Trend following and momentum work BETTER than in large cap
- Survivorship bias is catastrophic for small-cap backtests — use point-in-time constituent data
- Best strategies: Momentum Breakout, Donchian (multi-day), Opening Range Breakout on "in-play" names
- NOT recommended for retail systematic algos without institutional-grade data infrastructure

### 5.3 Growth vs. Value

**Growth stocks (high P/E, tech/biotech):**
- Higher ATR%, stronger momentum character — trend following / momentum breakout
- More sensitive to interest rate changes (duration effect on discounted cash flows)
- Higher overnight gap risk

**Value stocks (low P/E, energy/financials/utilities):**
- Lower ATR%, stronger mean reversion — VWAP MR, Bollinger Band MR
- More correlated with commodity prices, yield curve
- Better for position-sizing strategies using fundamental screens

---

## 6. ETFs

### 6.1 SPY (SPDR S&P 500 ETF)

- Tracks: S&P 500 index
- Volume: highest of any ETF; deepest liquidity in equity markets
- ATR%: ~0.5–0.8% daily (identical to ES/MES)
- Best strategies: VWAP Mean Reversion (4h edge documented), ETF arbitrage vs. underlying
- ORB strategy: Weakened on SPY due to strategy crowding; VIX 15–25 is the sweet spot window for ORB
- VWAP mean reversion edge on SPY: 4-hour timeframe shows strongest documented edge (4x stronger than 30-min)
- Key distinction: Mean reversion on 30-min and 15-min shows near-zero edge; do not use short-interval VWAP MR without testing
- Compared to ES futures: SPY adds management expense ratio (0.0945%) and no leverage; ES futures are preferred for institutional algo traders

### 6.2 QQQ (Invesco Nasdaq 100 ETF)

- Tracks: Nasdaq 100 (same index as NQ)
- ATR%: ~0.8–1.2% daily
- Momentum character more pronounced than SPY — trend following performs better here
- Trend following during 2020–2021 bull run: captured substantial gains; 2022 rate-hike environment: gave back profits in choppy conditions
- Use QQQ vs. SPY divergence for intermarket signals (when QQQ leads ES, broad risk-on conditions)

### 6.3 GLD (SPDR Gold Trust)

- Tracks: Physical gold price (1/10th oz per share)
- Expense ratio: 0.40%
- ATR%: ~0.7–1.2% daily (identical to GC futures)
- GLD vs. GC: Use GC futures for leverage and precise execution; use GLD for simpler exposure without margin management
- 12-month return (to March 2026): +47.24%
- Correlation with TLT: ~+0.25 (weak positive — both safe havens); with DXY: ~-0.40
- Best strategies: Same as GC — trend following on daily, VWAP MR intraday
- Calendar anomaly strategies on GLD: NOT validated — no consistent seasonal alpha documented

### 6.4 SLV (iShares Silver Trust)

- Tracks: Physical silver price
- Expense ratio: 0.50%
- ATR%: ~1.5–2.5% daily (same as SI futures)
- 12-month return (to March 2026): +101.70% (vs. GLD +47.24%) — silver dramatically outperformed gold
- YTD return (March 2026): -4.50% — reversal/consolidation after massive run
- Highest beta precious metals ETF — behaves like a leveraged gold position with industrial overlay
- Best for: Trend following during metals bull markets; paired with GLD for spread/ratio strategies
- Gold-Silver ratio mean reversion using GLD-SLV pair: well-documented cointegrated pair with ML-enhanced edge

### 6.5 USO (United States Oil Fund)

- Tracks: WTI crude oil futures (front-month)
- Warning: USO suffers significant contango roll costs when the oil market is in contango — this erodes long-term performance vs. CL futures
- ATR%: ~1.5–2.5% daily
- Use for: Basic directional crude oil exposure; Bayesian/correlation signal systems
- Prefer CL futures for active trading; use USO for simpler exposure without futures expertise
- Key consideration: USO/CL basis can diverge during roll periods

### 6.6 TLT (iShares 20+ Year Treasury Bond ETF)

- Tracks: Long-duration US Treasuries (20+ year maturity)
- ATR%: ~0.8–1.2% daily
- Correlation with ES (equities): ~-0.28 (traditional negative correlation — classic 60/40 portfolio logic)
- Correlation with GLD: ~+0.25 (both safe havens during stress)
- Rate sensitivity: When FOMC raises rates → bond prices fall → TLT falls; reverse with cuts
- Since November 2024: >$5.6 billion in TLT OUTFLOWS vs. $68 billion into short-term Treasury ETFs — regime shift away from long duration
- Calendar anomaly TLT strategy backtest (2010–2025): FAILED — returned -49.31% vs. buy-and-hold +48.8%. Critical warning: calendar patterns in TLT do not survive real-world implementation.
- Best use in algo portfolio: TLT as a regime signal (TLT rising = risk-off → reduce equity exposure); NOT as a standalone mean-reversion target
- Best strategies: Use as hedge signal, not as primary trading instrument

---

## 7. Strategy × Market Combination Matrix

This is the core reference table. Each cell rates the strategy-instrument combination:
- **A** = Excellent fit, documented positive expectancy
- **B** = Good fit, works with proper filters
- **C** = Marginal fit, requires significant customization
- **D** = Poor fit, avoid or use only with strong regime filter
- **X** = Not applicable / strongly avoid

| Strategy | MES/ES | MNQ/NQ | MYM/YM | GC/MGC | SI/SIL | HG | CL | NG | SPY/QQQ | GLD/SLV | AAPL | MSFT | TSLA |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Break & Retest (BRT) | **A** | B | B | B | C | C | B | D | B | B | B | B | B |
| Opening Range Breakout | B | B | C | C | D | D | B | D | C | D | B | B | B |
| VWAP Mean Reversion | **A** | C | A | B | D | D | B | X | **A** | C | A | A | C |
| EMA Crossover + ADX | C | B | C | **A** | **A** | **A** | B | B | C | **A** | C | C | B |
| Supertrend (ATR Trailing) | C | B | C | **A** | A | B | B | B | C | **A** | C | C | **A** |
| Bollinger Band MR | **A** | C | A | C | D | D | C | X | **A** | C | A | A | C |
| RSI Pullback in Trend | B | B | B | **A** | B | B | B | C | B | **A** | B | B | B |
| MACD Momentum | C | B | C | B | B | B | B | C | C | B | B | B | B |
| Donchian Breakout | C | C | C | **A** | **A** | **A** | **A** | A | D | **A** | D | D | C |
| Keltner Squeeze | B | B | B | B | B | **A** | B | C | B | B | B | B | B |
| Momentum Breakout | C | **A** | C | B | B | C | B | D | C | C | B | B | **A** |
| Gold-Silver Ratio MR | — | — | — | A | A | — | — | — | — | **A** | — | — | — |

**Key ratings explained:**
- BRT (A on MES): Core TRADEZ strategy, validated for MES 15-min structure
- VWAP MR (A on MES/SPY): Institutional execution creates persistent mean-reversion
- Donchian (A on GC, SI, CL): Commodities are the canonical Donchian markets; crude oil and gold cited explicitly
- EMA + ADX (A on GC, SI): Metals trend for months; ADX filter prevents whipsaw in range
- VWAP MR (X on NG): Natural gas's extreme volatility makes VWAP fade strategies dangerous

---

## 8. Head-to-Head Strategy Comparisons

### 8.1 Trend Following: Gold (GC) vs. S&P 500 (ES)

**Verdict: Gold wins decisively for trend following.**

| Factor | Gold (GC) | ES (S&P 500) |
|---|---|---|
| Trending behavior | Strong multi-year macro trends | Short-term mean-reverting; long-term bull bias |
| 12-month MA backtest (1971–2021) | $100K → $10M | Positive Sharpe but lower absolute return |
| Trend driver clarity | Inflation, geopolitics, real rates | Earnings, Fed, economic cycle |
| Drawdown avoidance | Excellent — MA gets you out of peaks | Moderate — crashes are fast |
| Win rate | Can be < 50% (asymmetric wins) | Similar low win rate |
| False signals | Moderate | HIGH (more choppy reversals) |
| TRADEZ recommendation | Use Donchian/EMA on MGC Daily | Use BRT/VWAP MR on MES Intraday |

**Why gold trends better:** Gold has no yield, no earnings — it is driven purely by macro regime changes which unfold over months. The S&P 500 has corporate earnings providing a mean-reverting fundamental anchor. Gold's long-term trends are larger, cleaner, and more sustained.

**Practical implication for TRADEZ:** Adding MGC with a daily Donchian or EMA trend system creates genuine diversification — the strategy type (trend-following) AND the market regime driver (inflation/geopolitics) are both different from MES BRT.

---

### 8.2 Mean Reversion: Metals vs. Equities

**Verdict: Equities win for intraday mean reversion; metals win for cross-instrument mean reversion (pair trades).**

| Factor | Metals (GC/SI) | Equities (ES/SPY) |
|---|---|---|
| Intraday VWAP MR | Works (B rating) — session-specific | Excellent (A rating) — strongest documented edge |
| Multi-day mean reversion | WEAK — metals can trend for months | MODERATE — earnings provide fundamental anchor |
| Cross-instrument MR | EXCELLENT — gold-silver ratio pair, 10-year cointegration | Moderate — pairs trading works but more crowded |
| ML-enhanced pair MR | Gold-Silver outperforms static arbitrage (SSRN 2025) | Many pairs; more competitive/crowded |
| VIX regime impact | Less sensitive | Directly impacted — VIX > 20 breaks MR logic |

---

### 8.3 Breakout Strategies: Commodities vs. Equities

**Verdict: Commodities are better breakout markets; equity indices are better mean-reversion markets.**

Research testing 125 parameter combinations across 44 futures markets found:
- Best breakout markets: Crude Oil (CL), Gold (GC), Soybeans
- Equity indices (ES, NQ): tend to mean-revert on shorter timeframes → more false breakouts

| Factor | Commodity Futures (GC, CL, SI) | Equity Index Futures (ES, NQ) |
|---|---|---|
| Breakout suitability | HIGH — trend-prone markets | LOW-MODERATE — mean-reverting tendencies |
| Typical win rate | 20–40% (asymmetric payoff) | 30–45% (with more false breakouts) |
| After breakout behavior | Sustained trend (days to weeks) | Often reversal within hours |
| Best timeframe | Swing/Position (daily) | Intraday (15 min–1h ORB only) |
| Correlation to equities | Low-to-negative (diversification benefit) | N/A — IS the equity market |

**For ORB specifically:** ORB on futures (ES, NQ) has weakened as the strategy has become crowded. Research shows ORB performance on popular index futures is "much less relevant now than it used to be." ORB on individual stocks (especially "in-play" names with specific catalysts) remains stronger — stocks have life of their own, indices are just averages.

---

### 8.4 VWAP Mean Reversion: Does It Work on Gold Futures?

**Verdict: YES — but only in non-trending, range-bound intraday sessions.**

- Extensions of 1–2% from VWAP on intraday gold timeframes often precede reversion moves
- Anchored VWAP + 2-SD bands reversed gold 5 consecutive times before a genuine breakout in documented backtests
- WORKS BEST: Quiet sessions, no major macro news scheduled
- FAILS: During strong CPI/FOMC-driven trend days, or during geopolitical spikes
- VWAP resets daily at COMEX open (8:20 AM ET) — intraday VWAP is the relevant anchor
- Strategy rating: B (good, with regime filter). NOT A-grade because gold trends more than ES — VWAP will be directionally wrong more often

**Implementation recommendation:** Add a "VWAP fade only if ADX < 20" filter. Above ADX 20, switch to trend mode (avoid mean reversion entirely on gold).

---

### 8.5 Opening Range Breakout: Stocks vs. Futures

| Factor | Individual Stocks | Futures (ES/NQ) |
|---|---|---|
| Session definition | Fixed 9:30 AM ET (clean) | Near-24hr; anchor to 9:30 or 8:00 AM |
| Preferred timeframe | 5–15 min | 15–30 min |
| Liquidity surge | At the bell — very predictable | Yes, but more distributed |
| ORB edge | Stronger on "in-play" stocks | Weakened on popular contracts |
| Strategy viability | Strong with catalyst filter | Requires VIX 15–25 + trend alignment |
| VIX regime sensitivity | Less direct | Very direct (VIX > 25 destroys ORB) |
| Crowding | Less crowded on individual names | Very crowded on ES, NQ |

**Practical recommendation:** ORB is most viable on:
1. Individual stocks with specific daily catalysts (earnings pre-market, news events)
2. Commodity futures (CL, GC) where liquidity patterns follow stock market hours but the instrument is less crowded
3. ES/MES only when VIX is 15–25 and ORB aligns with prevailing trend direction — take longs only in uptrend

---

## 9. Correlation Matrix

### Instrument Correlation Matrix (Approximate, March 2026)

| | ES/MES | NQ/MNQ | GC/MGC | SI/SIL | CL | NG | TLT | DXY |
|---|---|---|---|---|---|---|---|---|
| **ES/MES** | 1.00 | +0.90 | ~0.00 | +0.10 | +0.20 | +0.05 | -0.28 | Mixed |
| **NQ/MNQ** | +0.90 | 1.00 | -0.05 | +0.08 | +0.15 | +0.02 | -0.30 | -0.10 |
| **GC/MGC** | ~0.00 | -0.05 | 1.00 | +0.85 | +0.15 | -0.05 | +0.25 | -0.40 |
| **SI/SIL** | +0.10 | +0.08 | +0.85 | 1.00 | +0.20 | -0.02 | +0.15 | -0.35 |
| **CL** | +0.20 | +0.15 | +0.15 | +0.20 | 1.00 | +0.10 | -0.10 | -0.20 |
| **NG** | +0.05 | +0.02 | -0.05 | -0.02 | +0.10 | 1.00 | +0.05 | -0.05 |
| **TLT** | -0.28 | -0.30 | +0.25 | +0.15 | -0.10 | +0.05 | 1.00 | -0.35 |
| **DXY** | Mixed | -0.10 | -0.40 | -0.35 | -0.20 | -0.05 | -0.35 | 1.00 |

**Critical correlation notes:**

1. **ES ↔ NQ = +0.90**: Near-perfect correlation. Trading both simultaneously provides almost NO diversification. Choose one.

2. **GC ↔ ES = ~0.00**: Gold and S&P 500 have near-zero correlation — this is the strongest diversification pair available. Running BRT on MES + trend system on MGC is genuine diversification.

3. **GC ↔ SI = +0.85**: Gold and silver move together. Running both simultaneously roughly doubles metals exposure but does NOT meaningfully diversify.

4. **GC ↔ DXY = -0.40**: Dollar strength hurts gold. IMPORTANT CAVEAT: In 2023–2024, both rose simultaneously due to geopolitical stress — this historical correlation broke down. Monitor in real-time.

5. **TLT ↔ ES = -0.28**: Traditional equity/bond inverse relationship. WARNING: This relationship has been breaking down since 2022 rising rate environment. Do not rely on TLT as an equity hedge unconditionally.

6. **NG ↔ everything = near-zero**: Natural gas has the lowest correlation to other instruments — it is a genuine diversifier but its extreme volatility makes position sizing difficult.

### Diversification Priority Ranking for TRADEZ

Best diversification pairs (lowest correlation + manageable volatility):
1. **MES + MGC** — ~0.00 correlation, different strategy types, manageable contract sizes ← Priority #1
2. **MES + CL (MCL)** — ~0.20 correlation, oil adds commodity regime exposure
3. **MGC + TLT** — ~+0.25 correlation but different strategy types (trend vs. rate signal)
4. **Avoid: MES + MNQ** — ~0.90 correlation; almost no diversification benefit

---

## 10. Multi-Asset Portfolio Construction for Retail Algos

### The Core Problem

Most retail algos run on a single instrument (typically ES/MES or NQ/MNQ) with a single strategy. This is not portfolio construction — it is single-instrument speculation. The result is:
- Full exposure to equity regime changes
- No protection against equity market crashes (the worst drawdown events)
- Strategy correlation to itself over time leads to clustered losses

### Retail Multi-Asset Framework (Capital-Efficient)

**Step 1: Select 2–3 non-correlated markets**
- Primary: MES/ES (equity index mean reversion / BRT)
- Secondary: MGC (gold trend following — ~0.00 correlation to ES)
- Optional tertiary: MCL (crude oil — adds commodity exposure, ~0.20 corr with ES)

**Step 2: Use different strategy TYPES per market**
- MES: Mean reversion / structural (BRT, VWAP MR) — exploits institutional order flow
- MGC: Trend following (EMA + ADX, Donchian daily) — exploits macro regime changes
- MCL: Trend/breakout (EMA, Donchian, event-driven) — exploits supply cycle patterns
- Why this matters: Even if markets have low correlation, running the SAME strategy type on both creates regime correlation — both trend strategies lose in choppy periods simultaneously

**Step 3: Allocate risk equally across strategies, not capital**
- Risk 0.5% per trade per strategy (not 1% per strategy if running 2 simultaneously)
- Target: No more than 1.5–2% total daily risk across all strategies combined
- Use ATR-based position sizing: Position Size = (Account × Risk%) / (ATR × Dollar per Point)

**Step 4: Implement cross-strategy drawdown rules**
- If combined portfolio drawdown reaches 3% in a day: halt ALL strategies
- If combined portfolio drawdown reaches 8% in a month: reduce to minimum size
- If combined portfolio drawdown reaches 15%: halt until investigation and revalidation

### Capital Requirements (Approximate, March 2026)

| Configuration | Min. Account | Recommended Account |
|---|---|---|
| MES only (1 strategy) | $2,500 | $5,000–$10,000 |
| MES + MGC (2 strategies) | $5,000 | $10,000–$20,000 |
| MES + MGC + MCL (3 strategies) | $7,500 | $20,000–$40,000 |

### What Institutions Know That Retail Ignores

- CTAs (managed futures funds) trade 50–100 markets simultaneously — diversification IS the strategy
- The CTA risk premium comes from providing liquidity and accepting adverse regime periods — it requires significant capital depth and psychological staying power
- For retail: 2–3 non-correlated markets with different strategy types is the practical ceiling
- More complexity without validation is overfitting in disguise — do not add a third market until the first two have 200+ validated trades each

---

## 11. Key Driver Events Calendar

### Weekly Schedule

| Day | Time (ET) | Event | Most Affected Instruments |
|---|---|---|---|
| Monday | Various | European/Asian open positioning | GC/SI, CL |
| Tuesday | 10:00 AM | ISM Manufacturing PMI | ES, YM, HG |
| Wednesday | 8:30 AM | MBA Mortgage Applications | TLT |
| Wednesday | 9:30 AM CDT | **EIA Crude Oil Inventories** | **CL, MCL, USO** |
| Wednesday | 2:00 PM | FOMC Minutes (when applicable) | ES, GC, TLT |
| Thursday | 8:30 AM | Initial Jobless Claims | ES, MES |
| Thursday | 10:30 AM | **EIA Natural Gas Storage** | **NG** |
| Friday | 8:30 AM | NFP (first Friday of month) | ES, GC, DXY, TLT |
| Friday | 1:00 PM | Baker Hughes Rig Count | CL |

### Monthly/Quarterly Schedule

| Frequency | Event | Most Affected |
|---|---|---|
| Monthly (1st week) | Non-Farm Payrolls + Unemployment | ES, GC, TLT, DXY |
| Monthly (2nd week) | CPI / PPI inflation data | **GC, ES, TLT, DXY** |
| Monthly (4th week) | PCE Price Index | GC, ES |
| Monthly | FOMC Meeting (8x per year) | **ALL instruments** |
| Quarterly | Earnings season (Jan, Apr, Jul, Oct) | ES, NQ, individual stocks |
| As needed | OPEC+ Production Meetings | **CL, MCL, USO** |
| As needed | Fed Chair testimony (Humphrey-Hawkins) | GC, TLT, ES |

### Volatility Impact by Event (Estimated ATR Expansion)

| Event | ES | GC | CL | NG |
|---|---|---|---|---|
| FOMC Rate Decision | 2–4x ATR | 2–3x ATR | 1.5x ATR | 1x ATR |
| CPI Print (surprise) | 2–3x ATR | 3–5x ATR | 1.5x ATR | 1x ATR |
| NFP (miss/beat) | 2–3x ATR | 1.5–2x ATR | 1.5x ATR | 1x ATR |
| EIA Inventory (surprise) | 1x ATR | 1x ATR | 3–5x ATR | 1x ATR |
| EIA NG Storage (surprise) | 1x ATR | 1x ATR | 1x ATR | 5–10x ATR |
| OPEC Decision | 1.5x ATR | 1x ATR | 3–5x ATR | 1.5x ATR |
| Geopolitical shock | 2–4x ATR | 3–6x ATR | 3–6x ATR | 2x ATR |

**Algo rule:** On any day with a scheduled 2x+ ATR expansion event for your trading instrument, either:
1. Use reduced position size (50%)
2. Widen stops by 1.5–2x
3. Be flat 5 minutes before the event and 5 minutes after, then re-assess

---

## 12. Implementation Recommendations for TRADEZ

### Current State Assessment

TRADEZ currently runs:
- MES, BRT strategy, 15-min timeframe
- VIX-based regime adaptive parameters
- 1% risk per trade, 3% daily stop-out

This is a solid single-instrument foundation. The logical expansion path based on this research:

### Phase 1: Deepen MES Strategy Suite (Current — Next 3 Months)

Complete S02–S06 strategies already in the strategy library for MES:
- S02 (ORB): Add VIX filter (15–25 only), trend alignment requirement (longs only in uptrend)
- S03 (VWAP MR): Keep strict — only when ADX < 20 and no major news within 60 minutes
- S04 (EMA Crossover): Use on 1h MES; ADX > 25 required
- S06 (Bollinger MR): Valid for MES; use VIX < 20 filter

Target: 200+ total MES trades across all strategies before moving to Phase 2.

### Phase 2: Add MGC (Micro Gold) — High Priority

**Why MGC is the ideal second instrument:**
- Near-zero correlation with MES (~0.00) — genuine diversification
- MGC contract size ($10/point, $1/tick) matches MES risk profile perfectly
- Same broker (Tradovate) — no additional infrastructure needed
- Different primary strategy type: trend following (vs. MES mean reversion) — avoids regime correlation

**MGC strategy to implement first:**
- EMA(50) + EMA(200) + ADX trend following (Daily timeframe)
- Entry: both MAs aligned, ADX > 20, pullback to EMA50
- Stop: 1.5x ATR below entry (long) / above entry (short)
- Target: 2.5–3x ATR (trend strategies need wider targets)
- Regime filter: Only trade in direction of weekly trend; pause during ±2 week windows around FOMC

**Expected characteristics:**
- Lower trade frequency (3–8 trades/month on daily timeframe)
- Lower win rate (35–45% typical for trend following)
- Higher average win vs. average loss (2.5–4x R ratio)
- Low correlation to MES P&L — will lose during same periods MES wins and vice versa (this is the goal)

### Phase 3: Assess CL/MCL Addition (6–12 Months)

Only after MGC is validated with 200+ trades. MCL would add:
- Commodity cycle exposure (OPEC, EIA-driven)
- ~0.20 correlation with ES (low but not zero)
- Donchian or EMA trend system on Daily

### What NOT to Add

- **MNQ/NQ**: 0.90 correlation with MES — no diversification benefit
- **SI/SIL**: 0.85 correlation with GC — adds volatility without diversification if you already have MGC
- **NG**: Too volatile, too news-driven for systematic approach at retail scale
- **Individual stocks**: Survivorship bias in backtesting makes validation unreliable without professional data infrastructure
- **TLT**: Correlation assumptions have broken down since 2022; use only as a regime signal, not a tradeable instrument

### Risk Budget Allocation (When Running MES + MGC)

| Account Size | MES Risk/Trade | MGC Risk/Trade | Max Daily Loss | Notes |
|---|---|---|---|---|
| $5,000 | 0.5% ($25) | 0.5% ($25) | $150 (3%) | Minimum viable multi-strategy |
| $10,000 | 0.75% ($75) | 0.75% ($75) | $300 (3%) | Recommended starting point |
| $20,000 | 1.0% ($200) | 1.0% ($200) | $600 (3%) | Comfortable with proper cushion |
| $50,000+ | 1.0% ($500) | 1.0% ($500) | $1,500 (3%) | Full strategy deployment |

### ATR-Based Position Sizing Formula (Universal)

```
Contracts = (Account_Value × Risk_Percent) / (ATR_Value × Dollar_Per_Point)

Example (MGC, Daily ATR = $15, $10/point, 1% risk on $10,000 account):
Contracts = (10,000 × 0.01) / (15 × 10) = 100 / 150 = 0.67 → round to 1 contract
```

This formula automatically scales position size:
- Low ATR period: more contracts (volatility-scaled exposure)
- High ATR period: fewer contracts (automatic risk reduction)

---

## Sources and Further Reading

- [ES vs NQ Futures Comparison — Edgeful Blog](https://www.edgeful.com/blog/posts/es-vs-nq-futures-comparison)
- [Micro E-mini Futures Guide 2025 — FuturesHive](https://www.futureshive.com/blog/micro-emini-futures-mes-mnq-guide-2025)
- [Gold Moving Average Strategy Backtest — QuantifiedStrategies](https://www.quantifiedstrategies.com/gold-moving-average-strategy/)
- [Gold Futures Trading Strategies — NinjaTrader](https://ninjatrader.com/futures/blogs/gold-futures-trading-strategies-for-volatile-markets/)
- [Micro Gold Futures Guide — MetroTrade](https://www.metrotrade.com/guide-to-micro-gold-futures/)
- [Silver Futures Trading — NinjaTrader](https://ninjatrader.com/futures/blogs/how-to-trade-silver-futures/)
- [Crude Oil Trading Strategies (Backtested) — QuantifiedStrategies](https://www.quantifiedstrategies.com/crude-oil-trading-strategies/)
- [Natural Gas Trading Strategy — QuantifiedStrategies](https://www.quantifiedstrategies.com/natural-gas-trading-strategy/)
- [Opening Range Breakout Strategy — QuantifiedStrategies](https://www.quantifiedstrategies.com/opening-range-breakout-strategy/)
- [VWAP Strategy Guide — ChartSwatcher](https://chartswatcher.com/pages/blog/a-practical-guide-to-vwap-strategy-trading)
- [Using VWAP for Gold Trading — TradersPost](https://blog.traderspost.io/article/using-vwap-for-gold-trading-strategies)
- [Best Commodity Breakout Strategy — Peak Trading Research](https://peaktradingresearch.com/trader-education-blog/best-commodity-breakout-strategy-how-to-trade-breakouts)
- [Gold-Silver Pair Trading ML Paper — SSRN 2025](https://papers.ssrn.com/sol3/Delivery.cfm/5710242.pdf?abstractid=5710242&mirid=1)
- [Gold-Silver Price Volatility Powering Quant Funds — CNBC Feb 2026](https://www.cnbc.com/2026/02/09/gold-silver-price-volatility-quant-trading-algorithm-hedge-fund.html)
- [Intraday Precious Metals Algo Trading — ScienceDirect](https://www.sciencedirect.com/science/article/abs/pii/S0960077921010304)
- [Gold Correlation Data — World Gold Council](https://www.gold.org/goldhub/data/gold-correlation)
- [Asset Class Correlations — Portfolio Visualizer](https://www.portfoliovisualizer.com/asset-correlations)
- [WisdomTree Correlation Monitor — Nov 2025](https://www.wisdomtree.com/-/media/us-media-files/documents/resource-library/monitors/correlation-monitor.pdf)
- [S&P 500 / Gold Dual Trend Indices — S&P Global](https://www.spglobal.com/spdji/en/documents/brochure/brochure-sp-500-gold-futures-dual-trend-indices.pdf)
- [TLT Calendar Anomaly Backtest — Deepnote](https://deepnote.com/explore/tlt-month-based-algorithmic-trading-strategy-exploiting-calendar-anomalies-in-treasury-bond-etfs)
- [Most Popular Futures to Trade — MyFundedFutures](https://myfundedfutures.com/blog/most-popular-futures-to-trade-liquidity-margin-volatility-breakdown)
- [Multi-Asset Portfolio Approach 2026 — KraneShares](https://kraneshares.com/the-total-portfolio-approach-in-2026-construction-risk-and-the-role-of-kmlm/)
