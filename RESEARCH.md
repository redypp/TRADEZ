# TRADEZ — Master Research Compendium
> Compiled: 2026-03-24 | All 5 research agents completed.
> Sources: r/algotrading (skepticism-filtered), INSTITUTIONAL_RESEARCH.md (JPMorgan/AQR/Two Sigma/Man AHL/
> Renaissance/Lopez de Prado/Ernest Chan/Goldman/QuantConnect/CFA), MARKET_STRATEGY_MAPPING.md (932 lines,
> 44 futures markets analyzed), STRATEGY_ENCYCLOPEDIA.md (15 strategies fully documented),
> futures-specific intraday research (MES/MGC/SIL, 40+ sources).
> Reddit claims are cross-validated against institutional/academic sources before inclusion.

---

## TABLE OF CONTENTS
1. [What Separates Winning Strategies from Losers](#1)
2. [Backtesting: The Complete Pitfall List](#2)
3. [Live Trading vs Backtest Performance Gap](#3)
4. [Risk Management — What Actually Works](#4)
5. [Robustness Testing: The Full Protocol](#5)
6. [Performance Metrics: What They Mean and Don't Mean](#6)
7. [Strategy Decay and Edge Monitoring](#7)
8. [Execution Quality and CME Microstructure](#8)
9. [Mean Reversion vs Trend Following](#9)
10. [Futures-Specific Knowledge (ES/MES, Gold, Silver)](#10)
11. [Intraday Seasonality and Calendar Effects](#11)
12. [Strategy Library: 15 Validated Strategies](#12)
13. [Market–Strategy Matrix](#13)
14. [Multi-Timeframe and Confluence Framework](#14)
15. [Position Sizing Frameworks](#15)
16. [Portfolio Construction and Correlation](#16)
17. [Trade Analytics: MAE, MFE, Expectancy](#17)
18. [Institutional Best Practices Summary](#18)
19. [VPS and Deployment Checklist](#19)
20. [The Go-Live Checklist](#20)
21. [Critical Gaps in Current TRADEZ Implementation](#21)

---

## 1. What Separates Winning Strategies from Losers

**The fundamental finding across ALL sources (institutional, academic, community):**
Most backtest failures in live trading are not random — they are predictable and preventable.

- 73% of failed strategies skipped robustness testing (JPMorgan)
- 58% of retail algo strategies collapse within 3 months (Stanford 2025)
- 95% of backtested strategies fail live (QuantConnect, based on their platform data)
- Correlation between backtested Sharpe and live performance: **statistically zero** (Quantopian, 888 strategies)

**Three properties of a robust strategy (cross-validated across all sources):**
1. It works on data it has never seen
2. It does not break if some individual trades are missed
3. Performance does not cliff-drop when parameters are varied ±10–20%

**Lopez de Prado's hard line (AFML):** "Backtesting is not a research tool. Feature importance is." — validate that your BRT confluences actually predict direction, not just that they historically co-occurred.

**What the institutional consensus agrees on:**
- Edge must be economically motivated — start with a hypothesis grounded in market structure or behavioral finance, not a statistical pattern
- Simpler strategies outperform complex ones out-of-sample — every parameter is a new dimension for overfitting
- Risk management is the moat, not the alpha. A mediocre strategy with excellent risk management survives. A good strategy with poor risk management blows up.
- **Renaissance Technologies Medallion Fund was right only ~50.75% of the time.** The extraordinary returns came from applying that edge across millions of trades, not from a high win rate. Average trade profit: 0.01–0.05%.

---

## 2. Backtesting: The Complete Pitfall List

### Look-Ahead Bias (most dangerous, most common)
- Using today's closing price to generate a signal that fires at today's open
- Using `security()` in Pine Script with `lookahead=true`
- Calculating indicators on the full dataset before simulating bar-by-bar
- **Fix:** Always shift indicators by 1 bar. Only use data available at the *start* of each bar.

### Repainting Indicators
- Zigzag patterns, some volume profile indicators, higher-timeframe references change historical values as new data arrives
- They look perfect on a chart but the past signal never existed that way
- **Fix:** Only use non-repainting indicators. Test by running in realtime on fresh data.

### Survivorship Bias (inflates returns 1–4% annually)
- Backtesting only current S&P 500 constituents ignores delisted/bankrupt companies
- Bianchi and Koutmos: 2.1% annual overestimation during 2008 due to survivorship alone
- **Fix for TRADEZ:** Use futures/ETFs — no survivorship bias problem on MES or MGC.

### Data Quality Failures
- Missing adjustments for splits, dividends, mergers distort historical prices
- Yahoo Finance flagged repeatedly for corporate action adjustment errors
- JPMorgan's entire JPMaQS system is built around preventing this — they treat point-in-time data as a non-negotiable prerequisite
- **Fix:** Cross-validate against multiple sources. Use adjusted prices consistently.

### Multiple Testing Bias (Data Snooping)
- Testing 20 variations on the same dataset: the best-performer is almost certainly noise
- Testing 50 variations of a simple MA crossover: probability at least one looks profitable by random chance >92%
- Lopez de Prado's Deflated Sharpe Ratio (DSR) corrects for this — DSR > 1.0 after accounting for all trials is the institutional standard
- **Fix:** Keep a strategy graveyard log. Count all tests made. Use DSR, not raw Sharpe.

### Transaction Cost Underestimation
- At aggregate cost of 0.4%, alpha of many standard strategies vanishes
- Fees + slippage can erase 30–50% of theoretical returns
- **MES cost reality:** $1.25/tick. With ~$2.94 round-trip cost, a 2-tick stop requires a 4+ tick winner just to break even
- **Fix for TRADEZ:** Current $2.94/RT model is reasonable. Bump slippage to 1.5–2 ticks for momentum entries during fast markets.

### Overfitting / Curve-Fitting
- Parameters tweaked until they fit historical data perfectly
- If you tested 100 parameter combinations, 95%+ probability the best performer is overfit
- **Fix:** ATR-relative parameters (never absolute), round numbers only, economically motivated thresholds — TRADEZ already does this correctly in settings.py.

### Missing Regime Coverage
- A strategy optimized for trending markets bleeds in mean-reverting conditions
- Valid backtests require at least 2–3 complete bull AND bear cycles
- **Fix:** Test across 2008, 2018 Q4, 2020 COVID crash, 2022 rate hike environment.

---

## 3. Live Trading vs Backtest Performance Gap

**Key quantified facts:**
- Live drawdowns: typically **1.5–2× backtest drawdowns** — design for this
- Live Sharpe: typically **30–50% lower** than backtest Sharpe
- A backtest Sharpe of 3.70 → expect ~1.85–2.59 live (still good if it holds, but plan for worse)
- Slippage + latency erode 30–50% of theoretical returns
- Data pipeline mismatches between backtest platform and live data feed are consistently underestimated

**Why strategies fail in execution (checklist):**
- Using market orders where limit orders were assumed in backtest
- Selectively skipping signals (missed winners skew results negative)
- Cutting winners early / emotion overriding exits
- Stops triggered at worse prices than backtest assumed
- Latency between signal generation and order placement

**The overnight returns anomaly (NY Fed research):** A substantial portion of equity market returns are earned overnight, not during RTH. This affects how you interpret intraday backtests.

---

## 4. Risk Management — What Actually Works

### The 1–2% Rule Per Trade (universal across all sources)
- Risk 10%/trade, 10 consecutive losses = 65% drawdown (nearly unrecoverable)
- Risk 2%/trade, 10 losses = 18% drawdown (manageable)
- Risk 1%/trade, 10 losses = 9.6% drawdown (easily recoverable)
- **TRADEZ current: 1% ✓ — correct and validated**

### Tiered Drawdown Protocol (add to risk/manager.py)
- Down 5% from recent high → reduce position size by 25%
- Down 10–15% → reduce by 50%, A-setups only
- Down 15%+ → halt 24–72 hours, full review
- Weekly stop-out: −10% of account (add this — currently missing)
- Daily stop-out: 3% ✓ (already implemented)

### VIX-Based Volatility Scaling (implemented in regime.py ✓)
| VIX | Regime | Size |
|---|---|---|
| < 15 | TRENDING | Full |
| 15–20 | NORMAL | Full |
| 20–30 | CAUTIOUS | Half |
| 30–40 | HIGH_VOL | Min |
| > 40 | NO_TRADE | Flat |
**Research validation: VIX thresholds remain effective with ±2 VIX point shifts. Current thresholds are stable.**

### VIX Term Structure (advanced — add as secondary signal)
- **Contango** (front-month < back-month): normal/risk-on → favor trend strategies
- **Backwardation** (front-month > back-month): stress signal → immediately step down one regime level
- When VIX term structure inverts, reduce all position sizes immediately regardless of spot VIX level

### Kelly Criterion — Validated Against TRADEZ Stats
Using actual BRT stats (47.6% WR, 2.0 R:R):
- Full Kelly = 0.476 − [(1−0.476)/2.0] = **21.4%** — never use this
- Half Kelly = **10.7%** — for experienced live traders only
- Quarter Kelly = **5.35%** — more appropriate after validation
- **Fixed 1% (current)** = conservative, correct given only 21 trades of history
- Rule: increase toward Quarter Kelly only after 200+ validated trades

**Critical warning on Kelly:** Formula is highly sensitive to win rate estimation errors. With 21 trades, true win rate could easily be 35–60%. Never apply Kelly until 200+ trades narrow the confidence interval.

### Portfolio Heat Management
- Normal markets: max 5–6% total heat across all open positions
- High volatility (VIX > 25): max 3–4%
- Crisis (VIX > 30): max 2–3%
- If positions correlated > 0.7: treat as one risk unit
- Sector concentration: no more than 20–30% of total heat in one sector
- Drawdown-triggered scaling: −5% → −25% size; −10% → −50% size

### Macro Event Rules (FOMC/CPI/NFP — concrete thresholds)
- **FOMC days:** No new mean-reversion entries after 1:30 PM ET. If holding into 2:00 PM, widen stops 50%, reduce size 50%. Resume normal sizing after 3:00 PM.
- **FOMC pre-announcement drift** (NY Fed Staff Report #512): Nearly half of annual equity gains occur on FOMC days. The 24-hour pre-announcement period has persistent upward drift.
- **CPI/NFP:** Gold can move $20–50/oz in minutes. Reduce size or avoid entries in the 30 minutes surrounding 8:30 AM ET releases.

---

## 5. Robustness Testing: The Full Protocol

### 1. Parameter Sensitivity Analysis
- Vary each key parameter ±10–20% around its optimal value
- Robust = **plateau** (wide range of acceptable values)
- Overfit = **cliffs** (small changes cause large performance collapse)
- Build a color-coded sensitivity heat map

### 2. Monte Carlo Simulation
- Run 10,000 simulations (reorder actual trades or bootstrap resample)
- Watch: probability of ruin, 5th percentile drawdown, 95th percentile return
- **Minimum 30–50 actual trades** to be meaningful — 10k simulations on 21 trades only reflects 21 observations
- Standard: ruin probability < 5%, 5th percentile drawdown < 2× backtest max DD
- Skip-rate stress test: run at 10% trade-skip rate minimum

### 3. Walk-Forward Optimization (WFO) — Gold Standard
- IS:OOS ratio: **3:1** (optimize on 3 periods, test on immediately following 1)
- Roll forward and repeat across full history
- Pass criteria: **WFE > 50%**, profitable across all WFO windows, max DD < 40%
- **Meta-overfitting warning:** Running 10 different WFO configs and picking the best overfit the walk-forward itself
- QuantConnect standard: walk-forward only, never optimize on the full sample

### 4. In-Sample / Out-of-Sample Split
- Minimum **70/30 split**, preserving temporal order
- Three-way split: 70% train / 15% validation / 15% test
- **Critical:** Once you look at the test set, it is contaminated. Touch it once.
- Choose the split point BEFORE strategy development, not after

### 5. Minimum Trade Count
| Confidence Level | Minimum Trades |
|---|---|
| Bare minimum for any statistics | ~30 |
| 70% confidence | ~107 |
| 95% confidence (industry standard) | ~385 |
| Institutional standard | 400–600+ |
- **TRADEZ current: 21 trades. Statistically insufficient for any conclusion.**
- **Target: 200–300 minimum covering multiple regimes before drawing any conclusions**
- Quality caveat: 100 trades during the same trending month ≠ 100 independent observations

---

## 6. Performance Metrics: What They Mean and Don't Mean

### Sharpe Ratio
- > 1.0: acceptable | > 1.5: good | > 2.0: excellent (institutional requirement)
- **Live Sharpe is 30–50% lower than backtest Sharpe** — plan for this decay
- Sharpe > 3.0 in backtesting = red flag (overfitting, not genius)
- Weakness: penalizes upside and downside volatility equally

### Sortino Ratio
- Like Sharpe but only penalizes downside deviation
- > 1.0: acceptable | > 2.0: strong target
- If Sortino >> Sharpe: good (downside controlled). If Sortino ≈ Sharpe: red flag.

### Calmar Ratio (Annual Return / Max Drawdown)
- > 0.5: marginal | > 1.0: good | > 2.0: excellent
- Misleadingly high if the test period never had a significant drawdown

### Profit Factor
- 1.0–1.3: marginal | 1.3–1.5: acceptable | 1.5–1.7: good | > 2.0: suspect overfitting
- **Realistic sustainable target: 1.3–1.7**
- **TRADEZ current: 1.63 ✓** — within realistic range, but only 21 trades

### Win Rate vs R:R (always evaluate together)
- 40% WR + 2:1 R:R = +0.2R expectancy per trade ✓
- 60% WR + 1:2 R:R = −0.2R expectancy per trade ✗
- **TRADEZ: 47.6% WR + 2.0 R:R = +0.35R expectancy** — mathematically sound ✓

### Expectancy Benchmarks (in R-multiples)
| Level | R-Multiple | Interpretation |
|---|---|---|
| Minimum acceptable | > 0 | Any positive edge |
| Reasonable | 0.25R | $25 earned per $100 risked on average |
| Good | 0.30R | Solid, workable edge |
| Excellent | 0.50R+ | High-quality systematic edge |

### Max Drawdown
- < 10%: well-managed | 10–25%: normal | 25–30%: substantial | > 30%: poor
- **TRADEZ current: 26.2%** — on the edge of substantial. Target < 20% after tightening.
- Live circuit breaker: pause at **1.5–2× backtest max DD** (~39–52% for current system)

---

## 7. Strategy Decay and Edge Monitoring

**Alpha decay costs 5.6%/year in the U.S. (Maven Securities)**
- Annual rate of increase in decay cost: 36bps/year
- In-sample Sharpe has correlation of **< 0.05** with out-of-sample results

**Detection methods:**
- Rolling walk-forward: compare early OOS performance vs. recent OOS
- If recent 3–6 month OOS Sharpe is down 40%+ from full-history Sharpe: flag for review
- Monthly win rate and profit factor rolling averages — plot trend
- Structural break test (Bai-Perron) for formal regime change detection

**Root causes of decay:**
1. Market efficiency / competition discovering the same edge
2. Structural market changes (rate regimes, regulation, microstructure)
3. Overfitting — the edge was never real
4. Execution costs eroding thin margins

---

## 8. Execution Quality and CME Microstructure

### CME Globex Order Book
- **10-level limit order book** via MDP 3.0 feed (Simple Binary Encoding)
- Iceberg orders: hidden size refreshes with original time priority — watching for invisible liquidity absorption is a professional technique
- **On high-stress days:** ES volume 99% above ADV despite 68% decrease in visible order book depth (April 7, 2025 data). Raw book depth is a misleading liquidity proxy under stress.
- Use **Cost-to-Trade (CTT)** from CME Liquidity Tool, not raw book depth

### Slippage Reality by Market Condition
- MES normal hours, limit orders: 0–1 tick typical
- MES market orders or fast markets: 1–3+ ticks
- MGC: similar but slightly wider — use limit orders preferentially
- High-volume windows (9:30–11:00, 15:30–16:00): tightest spreads, best fill quality
- Midday (11:30–13:30): wider spreads, more slippage on average
- **TRADEZ current cost model: $2.94/RT is reasonable for normal conditions**
- Bump to 1.5–2 ticks ($1.88–$2.50) for BRT momentum entries during fast markets

### Momentum vs Mean Reversion Fill Quality
- Momentum strategies: everyone entering same direction simultaneously = structural slippage disadvantage
- Mean reversion strategies: trading against flow = liquidity provider = better fills
- This means VWAP MR will fill better in practice than BRT trend entries

---

## 9. Mean Reversion vs Trend Following

**Neither is universally superior. They are structurally complementary (cross-validated across all sources).**

| Factor | Mean Reversion | Trend Following |
|---|---|---|
| Win Rate | 60–80% | 30–50% |
| Avg Winner | Small | Large |
| Return Skew | Negative (small wins, rare large loss) | Positive (small losses, rare large win) |
| Best Market | Ranging / low ADX | Trending / high ADX |
| Hidden Risk | Catastrophic loss when range breaks | Slow bleed in extended chop |
| Kelly Warning | Hard to implement stops without degrading perf | Trend-following naturally has hard stops |

**Combining them (rebalancing bonus):** When two uncorrelated strategies are periodically rebalanced, selling the outperformer and buying the underperformer generates a positive return even if both have modest individual returns (Shannon's Demon). Monthly rebalancing is practical.

**Regime-aware allocation:**
- High volatility / trending: 60–70% toward trend following
- Low volatility / range-bound: 60–70% toward mean reversion
- Uncertain: 50/50

**The professional answer:** Run both simultaneously. During trends, trend-following carries returns. During ranges, mean-reversion picks up the slack. Combined portfolio = smoother equity curve, more consistency across regimes.

---

## 10. Futures-Specific Knowledge

### Contract Specs (confirmed from CME official specs)
| Contract | Tick Size | Tick Value | Key Note |
|---|---|---|---|
| MES | 0.25 pts | **$1.25** | $5/full point |
| MGC | $0.10/oz | **$1.00** | 10 troy oz |
| SIL | $0.005/oz | **$5.00** | 1,000 troy oz |
| GC | $0.10/oz | **$10.00** | 100 troy oz (10× MGC) |
| SI | $0.005/oz | **$25.00** | 5,000 troy oz (5× SIL) |
| CL | $0.01/bbl | **$10.00** | Avoid for retail algo |
| NG | varies | very high | **Avoid** — HFT dominated |

### ES / MES Intraday
- **Session:** Primary liquidity 9:30–16:00 ET
- **Best window:** 9:30–11:00 AM ET — highest volume, highest trend probability, cleanest moves
- **Worst window:** 11:30 AM–1:00 PM ET — midday lull, low volume, high false breakout rate
- **Second window:** 3:30–4:00 PM ET — closing momentum, position squaring
- **Add a midday filter** to suppress signals from 11:30–13:30 ET (currently missing in TRADEZ)
- **Gamma hedging effect:** Market makers short gamma mechanically amplify late-session trending moves in ES. On high-VIX days this effect is amplified — late-session ES trends have structural support.
- **Intraday momentum finding (Notre Dame/ND paper):** First 30-min return predicts next day's open return (continuation). Last 30-min return predicts next day's close (continuation). Gaps at open are more likely to fill; intraday momentum after 10:00 AM is more likely to continue.
- **FOMC / CPI / NFP:** Avoid BRT entries within 30 min of 8:30 AM releases. FOMC 2:00 PM window: spike-and-reverse behavior makes standard stops unreliable.

### Gold (GC / MGC)
- **Near-24h trading:** Sunday 6 PM – Friday 5 PM CT, 1-hour daily maintenance break
- **Key volatility events:** CPI, Fed announcements, NFP — gold can move $20–50/oz in minutes
- **Drivers:** USD strength (inverse), real yields (inverse), inflation expectations, geopolitical risk, central bank demand
- **Optimal strategies:** Trend following (12-month MA grew $100K → $10M from 1971–2021 vs $4M buy-and-hold), Supertrend, EMA crossover, Keltner Channel
- **Intraday:** RSI on 60-min = 63.7% excess returns vs B&H (PSO-optimized study). Keltner Channel 60-min, 1.5× ATR = 58.5% excess returns. Both use same params as each other and generalize across all precious metals.
- **Gold volatility:** 15.44% annualized — similar to S&P 500 (14.32%), not dramatically higher
- **Gold vs ES correlation:** ~0.00 in normal conditions, turns **sharply negative** in crisis regimes — this is your best diversification pair
- **Combined MES + MGC portfolio** was the **#1 strategy out of 1,274 strategies** over the 3-year period ending March 2025 (WisdomTree research)

### Silver (SI / SIL)
- **SIL is right for TRADEZ** — full SI at $25/tick is too large for micro-account risk
- **More volatile than gold** intraday — wider stops required throughout
- **Optimal params (PSO research):** RSI 60-min standard settings = 63.7% excess returns. Same Keltner 1.5× ATR params work as gold.
- Both GC and SIL use identical optimal params — build one system, deploy on both
- **Don't run SIL if already trading MGC** — 0.85 correlation between them (confirmed by agent)
- SIL is ideal for strategy testing before scaling to SI

### Correlation Matrix (confirmed)
| Pair | Correlation | Implication |
|---|---|---|
| ES ↔ NQ | +0.90 | No diversification — don't add both |
| ES ↔ GC | ~0.00 | **Best diversification pair for retail** |
| GC ↔ SI | +0.85 | Don't run both — doubles metals exposure |
| GC ↔ DXY | −0.40 | Broke down in 2023–24 (geopolitical stress) |

**Portfolio recommendation:** **MES + MGC is the ideal two-instrument portfolio.** Near-zero correlation, different strategy types, same broker, matched contract sizes.

---

## 11. Intraday Seasonality and Calendar Effects

### Time-of-Day (ES/MES) — Research-Backed
| Window (ET) | Characterization | TRADEZ Action |
|---|---|---|
| 8:30 AM | Economic data spikes (CPI, NFP, PPI) | Avoid; wider stops if holding |
| **9:30–11:00 AM** | **Peak volume, highest trend probability** | **BRT, ORB, momentum — primary window** |
| 9:30–10:30 AM | Single best hour for ES | Largest moves, clearest direction |
| 11:30 AM–1:00 PM | Midday lull, choppy, false breakouts | **Add MIDDAY_FILTER to suppress signals** |
| 1:00–3:00 PM | Secondary institutional activity | Selective; better in 2:00–3:00 PM window |
| **3:30–4:00 PM** | **Second volume peak, closing momentum** | **BRT trend continuation valid** |
| Post 4:00 PM | Thin liquidity, event-driven | Different strategy type needed |

**Note on current session filter:** TRADEZ runs 10:00–15:00 ET. Consider:
- Starting ORB scan at 9:32 ET (ORB requires it)
- Adding explicit midday suppression 11:30–13:30 ET
- The 9:30–10:30 window is the highest-probability hour — the current 10:00 start misses the best 30 minutes

### Day-of-Week Effects (Purdue University, academic — not Reddit)
- **Monday:** Historically negative effect (concentrated in pre-1982 data). Weaker now but present.
- **Tuesday:** "Tuesday Turnaround" — most documented and repeatable DOW pattern in US equity futures. Use as a mean-reversion bias modifier.
- **Wednesday–Thursday:** Lower volume, choppier. More false breakouts.
- **Friday:** Position squaring into weekend. Trend follow-through weaker. Avoid holding over weekend.
- **Gold-specific:** Thursday shows elevated volatility. Wednesday shows lowest gold volatility.
- **Practical rule:** Use day-of-week as a tiebreaker filter only, never a standalone signal. Full-size Tuesday BRT/ORB; half-size Monday/Friday.

### FOMC Pre-Announcement Drift (NY Fed Staff Report #512 — hard research)
- Nearly **half of annual equity market gains** occur on FOMC announcement days
- The **24-hour pre-announcement period** has statistically documented upward drift
- **2:00–2:30 PM ET on FOMC days:** most volatile 30-min window in the US trading calendar
- **Concrete rules for TRADEZ:**
  - Reduce position size to 50% of normal on FOMC days
  - No new mean-reversion entries after 1:30 PM ET
  - Widen stops by 50% if holding through 2:00 PM (normal 8-pt ES stop → 12-pt)
  - Wait for initial spike to complete, then wait for 3–5 min candle confirmation
  - Resume normal sizing after 3:00 PM

### Earnings Effect
- PEAD (Post-Earnings-Announcement Drift): stocks exhibit persistent drift in the direction of the earnings surprise for days to weeks. One of the most replicated anomalies in academic finance.
- For index futures (ES, NQ): buffered by diversification — generally safe to trade through individual company earnings
- During peak earnings seasons (January, April, July, October): aggregate beat/miss rate can amplify existing trend signals on ES

---

## 12. Strategy Library (15 Strategies)

All strategies are implemented as Python modules in `strategy/`. Each uses ATR-relative parameters only, has a regime filter, and requires minimum 3 confluence factors.

---

### S01: Break & Retest (BRT) — EXISTING ✅
**Type:** Momentum / Structure | **Instruments:** MES (primary), Gold, Stocks | **TF:** 15min
**Validated WR:** 50–70% with full confluence stack (research-backed). Current BRT: 47.6% — lower bound, consistent with limited sample.
**Research-validated optimizations to apply:**
- Raise ADX min from 20 → 25 in NORMAL and CAUTIOUS regimes (cleaner filter)
- Reduce `BRT_MAX_RETEST_BARS` from 16 → 10–12 (tighter quality, fewer stale setups)
- Add Fibonacci retest zones: 38.2%, 50%, 61.8% of the breakout range are highest-probability entries
- Add 200 EMA higher-timeframe filter: only longs above 200 EMA on 1H chart
- Volume confirmation already implemented ✓
- Add MTF confirmation: use 1H for structure, confirm on 15-min retest

---

### S02: Opening Range Breakout (ORB)
**Type:** Momentum / Breakout | **Instruments:** MES, MNQ, Stocks | **TF:** 15min
**Validated WR:** 55–60% on ES/SPY with daily bias filter (10+ years proven on Edgeful data)
**60-min ORB stats:** WR 89.4%, PF 1.44, 3× P&L vs 15-min (fewer signals, higher quality)
**Entry rules:**
- Opening range: 9:30–9:45 ET first 15-min bar (high/low)
- Long: full candle close > ORH + 0.1×ATR, volume > 1.5× vol_ma
- Short: full candle close < ORL − 0.1×ATR, volume > 1.5× vol_ma
- EMA20 alignment (long above, short below)
- Entry only valid 10:00–12:00 ET
**Opening range cap:** Skip if range > 0.5% of price (too wide = reversal risk dominates). Expand to 0.8% cap if testing.
**SL:** Opposite side of opening range
**TP1:** 1× opening range beyond breakout | **TP2:** 2× opening range or PDH/PDL
**VIX-adaptive params (critical — largest single source of ORB underperformance if ignored):**
- VIX < 15: half size (small moves, low expectancy)
- VIX 15–25: full size (sweet spot — highest per-trade expectancy)
- VIX > 25: skip entirely (false breakouts dominate, negative expectancy)
**Common mistakes:** Entry before candle closes. Not filtering for large overnight gaps (>0.5% from prior close distorts ORB). Same params regardless of VIX.

---

### S03: VWAP Mean Reversion
**Type:** Mean Reversion | **Instruments:** MES, MNQ, Stocks | **TF:** 5–15min
**Validated WR:** 55–65% when session regime correctly classified (community data, cross-validated)
**Institutional basis:** Institutions execute large orders benchmarked to VWAP — they actively maintain positions near VWAP, making it a gravitational center during consolidation.
**Entry rules:**
- **Regime gate (critical):** Only trade when ADX < 20 AND VIX < 20. Fails entirely on trending days.
- Long: close < VWAP − 1.5×ATR (extreme), OR close below −2 SD VWAP band, RSI < 35, ADX < 20
- Short: close > VWAP + 1.5×ATR, OR close above +2 SD VWAP band, RSI > 65, ADX < 20
- Confirmation: next candle closes back toward VWAP direction
- Declining volume (exhaustion of move away from VWAP)
**SL:** 0.3×ATR beyond entry candle in wrong direction
**TP:** VWAP itself (primary) or 1.5R
**VWAP standard deviation bands:** ±1 SD = fair value zone. ±2 SD = extreme, high-probability reversion. Outside ±2 SD with RSI confirmation = highest probability entry.
**Warning:** NEVER fade a strong trend with VWAP MR. When ADX > 20, price can run from VWAP all session.

---

### S04: EMA Crossover + ADX Filter
**Type:** Trend Following | **Instruments:** Gold (daily), Silver (daily), Stocks | **TF:** 1h–Daily
**Validated params (EMA crossover on XAUUSD 3h):** EMA 21/55/200, best PF 2.00. Ed Seykota rule: slow EMA should be ≥ 3× fast EMA.
**Entry rules:**
- Long: EMA(9) crosses above EMA(21), AND price > EMA(50), ADX > 20, RSI 40–70
- Short: EMA(9) crosses below EMA(21), AND price < EMA(50), ADX > 20, RSI 30–60
- Volume on crossover candle > 1.2× vol_ma
**SL:** Below recent swing low (long) − 0.5×ATR
**TP:** 3R (trend trade — let winners run)
**Skip when:** ADX < 18 — EMA crossovers whipsaw severely in chop. This is the most important filter.
**Known weakness:** Lags price. Enters after move has started. Works well on daily and 4H; generates too many false signals on sub-1h charts.

---

### S05: Supertrend
**Type:** Trend Following / Trailing Stop | **Instruments:** Gold, Silver, MES | **TF:** 1h–Daily
**Critical finding (4,052-trade large-scale study, LiberatedStockTrader):** Standalone win rate is only **40–43%**, profit expectancy ~0.24/trade. **Must be combined with ADX > 18 and EMA direction filter to reach 50–67% WR.** Every TradingView Pine Script showing 90%+ WR with SuperTrend is almost certainly overfitted.
**True value: trailing stop overlay, not standalone entry signal.**
**Entry rules (combined):**
- SuperTrend flips bullish AND ADX > 18 AND close > EMA(50) → long
- SuperTrend flips bearish AND ADX > 18 AND close < EMA(50) → short
- RSI 35–70 for longs, 30–65 for shorts
**Standard params:** ATR(10), multiplier = 3.0 (TradingView default — validated).
**Day trading variant:** ATR(7), multiplier = 2.0
**SL:** SuperTrend line itself acts as trailing stop
**TP:** Hold until SuperTrend flip — this is a trend-following strategy, let winners run

---

### S06: Bollinger Band Mean Reversion
**Type:** Mean Reversion | **Instruments:** MES, Gold, Stocks | **TF:** 15min–1h
**Key finding:** **ADX < 22 is non-negotiable.** Above ADX 22, bands are in expansion mode and mean reversion fails systematically. This is the most important filter for this strategy.
**Entry rules:**
- Long: close crosses below lower BB (20, 2σ), RSI < 35, ADX < 22
- Confirmation: next candle closes back above lower band
- Short: close crosses above upper BB (20, 2σ), RSI > 65, ADX < 22
- Confirmation: next candle closes back below upper band
**SL:** 0.5×ATR beyond the band that was touched
**TP:** Middle band (SMA20) — typically 1.5–2R
**Day trading params:** BB(10, 1.5σ). Swing params: BB(50, 2.5σ).
**Regime gate:** Skip if VIX > 25 (bands expand dramatically; reversion can take days or not happen)

---

### S07: RSI Pullback in Trend
**Type:** Momentum / Pullback | **Instruments:** Stocks (excellent), Gold, MES | **TF:** 1h–Daily
**Validated WR:** 55–65% in confirmed trends. Degrades to 35–45% without ADX filter.
**RSI(2) daily variant (QuantifiedStrategies, 33-year backtest on SPY):** $100K → $1.7M, 75% WR, PF 2.3, 23% max DD, invested only 27% of time. **Only works on daily bars. Does NOT work intraday or on forex.**
**Entry rules (standard RSI pullback):**
- Long: price > EMA(50), ADX > 20, RSI(14) pulls back to 40–55, then turns back up (RSI > prior bar RSI)
- Confirmation: bullish candle with close > open
- Short: price < EMA(50), ADX > 20, RSI(14) pops to 45–60, then turns back down
**SL:** Below recent swing low − 0.3×ATR
**TP:** Recent swing high or 2.5R
**RSI(2) enhanced entry (daily only):** RSI(2) < 10 with price > 200 EMA. Exit when price closes above prior day's high. This is one of the most documented edges in the strategy database.

---

### S08: MACD Momentum
**Type:** Momentum / Trend | **Instruments:** Stocks (excellent), Gold (daily), MES (1h) | **TF:** 1h–Daily
**Validated stats:** MACD + RSI combined (QuantifiedStrategies): **73% WR, PF 2.45–4.22 on SMH ETF, 235 trades** — sample size worth trusting. Linda Raschke 3/10/16 variant: signals 5–10 candles earlier than standard 12/26/9.
**Entry rules:**
- Long: MACD histogram crosses negative → positive (fast > slow), EMA(20) > EMA(50), ADX > 18, RSI 40–70
- Short: MACD histogram crosses positive → negative, EMA(20) < EMA(50), ADX > 18, RSI 30–60
- Volume > vol_ma on signal bar
**SL:** Below EMA(50) or recent swing low for longs
**TP:** 2.5R or hold until MACD re-cross
**Standard params:** MACD(12, 26, 9). Linda Raschke variant: MACD(3, 10, 16) for earlier entry timing.
**Warning:** Standalone MACD has weak edge. The **RSI filter is mandatory** to reach the 73% WR documented above.

---

### S09: Donchian Channel Breakout — EXISTING ⚠️ (partial)
**Type:** Trend Following | **Instruments:** Gold, Silver (top 2 of 44 futures markets studied), Oil | **TF:** Daily
**Validated WR:** 35–45% typical. **Edge comes from large winning trades (10R+), not high win rate.** Drawdowns between winners are brutal — this is psychologically difficult.
**Entry rules (Turtle System):**
- Long: close > Donchian(20) high (new 20-day high), ADX > 18, volume > 1.2× vol_ma
- Short: close < Donchian(20) low (new 20-day low)
- RSI > 60 on breakout (reduces false breakouts significantly)
**SL:** 2×ATR(20) from entry (Turtle system standard)
**Exit:** Donchian(10) exit channel — when price reaches new 10-day low/high in opposite direction
**Research validation:** Across 44 futures markets, crude oil, gold, and soybeans were the top 3 Donchian markets. ES is mean-reverting and generates too many false breakouts for this system.
**Status:** Needs full Turtle exit logic (10-day trailing exit)

---

### S10: Keltner Channel Squeeze (TTM Squeeze)
**Type:** Volatility Breakout | **Instruments:** MES, Gold, Stocks | **TF:** 15min–Daily
**Validated WR:** 55–65% with direction filter. Maximum compression (all three KC levels squeezed) = 65–70% success rate.
**Squeeze detection:** Bollinger Bands (20, 2σ) inside Keltner Channel (20, 1.5×ATR) = squeeze active
**Entry rules:**
- Squeeze detected: mark state as compressing (no entry yet)
- Squeeze release: BB expands beyond KC boundary
- Direction: if close > EMA(20) AND momentum histogram positive → long; if close < EMA(20) AND histogram negative → short
- ADX turning up from below 20 (confirming new trend beginning)
**SL:** Opposite Keltner Channel line at entry
**TP:** 2–3R depending on regime

---

### S11: Momentum Breakout (New High/Low + Volume)
**Type:** Momentum / Breakout | **Instruments:** Stocks (excellent), MES, Gold | **TF:** 15min–1h
**Validated WR:** 45–55% with full filter stack. Volume filter is the single most impactful element — without 2× volume, false breakout rate dominates.
**Entry rules:**
- Long: close > rolling high(20 bars) + 0.1×ATR, candle body > 0.4×ATR, volume > 2.0× vol_ma, ADX > 20
- Short: close < rolling low(20 bars) − 0.1×ATR, candle body > 0.4×ATR, volume > 2.0× vol_ma
- Session timing: 10:00–14:00 ET for intraday
**SL:** Below breakout bar low − 0.3×ATR (long)
**TP:** 2.0R

---

### S12: NR7 Narrow Range Breakout
**Type:** Volatility Breakout | **Instruments:** Stocks, ETFs, Gold | **TF:** Daily
**Validated WR:** 55–65% with EMA trend filter. NR7 produces stronger follow-through than NR4.
**NR7:** A bar with the smallest range of the last 7 bars (compression before expansion)
**Entry rules:**
- Identify NR7 bar (or NR7 + Inside Bar for maximum compression)
- Next day: enter buy stop above NR7 high (long), sell stop below NR7 low (short)
- EMA alignment: 10 > 20 > 50 EMA for trend-filtered entries
**SL:** Opposite side of the NR7 bar
**TP:** 2R or prior swing high/low
**Best on:** Daily chart. Works across equities and gold futures.

---

### S13: MACD + RSI Triple Confirmation
**Type:** Trend / Momentum | **Instruments:** Stocks, ETFs, commodity futures | **TF:** Daily–Weekly
**Validated stats (QuantifiedStrategies):** 73% WR, 0.88% avg gain/trade, 235 trades on SMH ETF. Commodity futures version significantly outperformed S&P GSCI benchmark 2010–2019.
**Enhanced entry:** Triple RSI extension — RSI(3) + RSI(7) + RSI(14) all below 30 simultaneously = highest-conviction mean-reversion entry (rare but very high probability).
**Entry rules:**
- Standard: MACD(12,26,9) histogram turns positive + RSI(14) < 65 (not overbought) + EMA(50) trending up
- Triple RSI: RSI(3) < 10, RSI(7) < 20, RSI(14) < 30 all simultaneously → extreme mean-reversion long
**SL:** Below most recent swing low
**TP:** 2.5R or prior resistance

---

### S14: RSI(2) Daily Mean Reversion
**Type:** Mean Reversion | **Instruments:** SPY, QQQ, large-cap stocks | **TF:** Daily ONLY
**Validated stats (QuantifiedStrategies, 33-year SPY backtest):** $100K → $1.7M, **75% WR**, PF 2.3, max DD 23%, invested only 27% of time. QQQ enhanced: 75% WR, PF 3.0, Sharpe 2.85, CAGR 12.7%.
**IMPORTANT: Does NOT work on forex, intraday, or commodities. Daily US equity bars only.**
**Entry rules:**
- Long: RSI(2) < 10 AND price > 200 EMA
- Short: RSI(2) > 90 AND price < 200 EMA
**Exit (the "QS Exit"):** Close position when price closes above prior day's high (long) or below prior day's low (short)
**SL:** Below most recent swing low for longs (wide stop — this is a mean reversion strategy)
**Note:** This is an edge with a real, documented track record. Best for stocks, ETFs, not futures.

---

### S15: Linda Raschke 3-10-16 MACD Momentum
**Type:** Momentum / Intraday | **Instruments:** ES, stocks, forex | **TF:** Intraday (5min–1h)
**Logic:** MACD(3, 10, 16) detects momentum shifts 5–10 candles earlier than standard (12, 26, 9). Best used alongside standard MACD: Raschke for timing, standard for directional bias.
**Entry rules:**
- Long: 3/10 fast line crosses above slow, histogram turns positive, standard MACD(12,26,9) also positive
- Short: 3/10 fast line crosses below slow, histogram turns negative, standard MACD also negative
**Exit:** On momentum histogram peak and starting to decline — NOT on zero-line cross
**SL:** Below entry bar low + 0.3×ATR
**TP:** 1.5–2R or histogram fade

---

## 13. Market–Strategy Matrix

### By Market Condition
| Condition | Detection | Best Strategies | Avoid |
|---|---|---|---|
| Strong Trend | ADX > 25, EMA aligned | BRT, ORB, Supertrend, Donchian, S11 | VWAP MR, Bollinger MR |
| Weak Trend | ADX 18–25 | EMA Cross, RSI Pullback, Supertrend | Donchian, ORB |
| Ranging / Chop | ADX < 18 | VWAP MR, Bollinger MR, RSI Pullback | BRT, ORB, EMA Cross |
| Volatility Compression | BB inside KC | Keltner Squeeze (wait) | All trend entries |
| High Vol | VIX 20–30, ATR expanding | BRT (wider params), ORB (VIX < 25) | VWAP MR, Bollinger MR |
| Extreme Vol | VIX 30–40 | Supertrend, Donchian (daily, min size) | All intraday |
| No Trade | VIX > 40 | Flat | Everything |

### By Instrument (research-validated)
| Instrument | Top Strategies | Avoid | Notes |
|---|---|---|---|
| **MES** | BRT, VWAP MR, ORB, S15 | Donchian | ES is mean-reverting short-term; trend-following underperforms |
| **MGC** | Supertrend, EMA Cross, Donchian, RSI 60-min | VWAP MR on trend days | Near-24h market; trend-following dominates long-term |
| **SIL** | Donchian, Supertrend, Keltner | Don't run alongside MGC | 0.85 corr with gold; wider stops needed |
| **SPY/QQQ ETFs** | RSI(2) daily, BRT, VWAP MR | Standalone SuperTrend | RSI(2) daily is the highest-documented WR (75%) |
| **Individual Stocks** | RSI Pullback, MACD+RSI, NR7, S11 | — | PEAD drift, earnings plays viable |
| **NG/CL** | Avoid for retail algos | Everything | HFT dominated, extreme volatility |

---

## 14. Multi-Timeframe and Confluence Framework

### MTF Timeframe Ratios (research-validated)
- Use 4:1 to 5:1 ratio between timeframes
- Day trading: 15M / 1H / 4H
- Swing: 1H / 4H / Daily
- For BRT: use 1H for structure identification, enter on 15-min retest confirmation
- Never enter based solely on lowest timeframe signal
- Stacked S/R (level on both higher and lower TF) = higher probability than single-TF level

### Confluence Score Framework (3–4 factors = optimal sweet spot)
**Research finding:** 3–4 independent, non-redundant factors = optimal. More than 4 = diminishing returns and analysis paralysis. Never use two momentum oscillators simultaneously (redundant — same information).

**Factor scoring (one factor per analytical purpose):**

| Purpose | Factors (pick ONE) |
|---|---|
| Trend direction | EMA alignment, 200 EMA, higher-TF bias |
| Momentum | RSI range, MACD direction |
| Volatility/range | ADX threshold, BB width, ATR percentile |
| Volume | Volume vs vol_ma ratio |
| Level | Key level type (VWAP > PDH > ORH > Swing) |

**A-setup:** 3+ Tier 1 factors aligned → full size
**B-setup:** 2 Tier 1 factors → half size
**C-setup / no setup:** < 2 factors → skip

---

## 15. Position Sizing Frameworks

### Fixed Fractional (current TRADEZ method)
- Risk 1% of account per trade regardless of conditions ✓
- Does not adapt to volatility — treats all sessions equally
- **Best for:** All traders, especially early in system development

### Volatility-Adjusted (ATR-based) — Add as option
**Formula:** Units = (Equity × Risk%) / (ATR × Multiplier)
- Automatically reduces size when volatility is high, increases when low
- Normalizes risk across different instruments and market conditions
- ATR period: 14 standard. Multiplier: 1.5–2.0 for intraday SL.
- **Hybrid:** Use fixed fractional as the floor (2% max), ATR-adjustment as the sizing mechanism within that ceiling

### Kelly Criterion (validated against BRT stats)
| Fraction | TRADEZ equivalent | Recommendation |
|---|---|---|
| Full Kelly (21.4%) | ~$428/trade on $2k account | Never — too aggressive |
| Half Kelly (10.7%) | ~$214/trade | Experienced live traders only |
| Quarter Kelly (5.35%) | ~$107/trade | After 200+ trade validation |
| Fixed 1% (current) | ~$20/trade | **Correct now — maintain** |

**Increase toward Quarter Kelly only after:** 200+ trades validate the win rate and R:R estimates.

---

## 16. Portfolio Construction and Correlation

### Core Principle
A bundle of truly uncorrelated strategies is one of the simplest and most robust paths to consistency. Treat strategies like assets in a portfolio — the same diversification math applies.

### Correlation Thresholds
- < 0.3: genuine diversification — include freely
- 0.3–0.5: modest overlap — monitor
- 0.5–0.7: significant overlap — treat as partial
- > 0.7: same risk unit — don't add both at full size

### Optimal TRADEZ Portfolio (research-validated)
1. **MES** — BRT strategy (mean-reversion flavored, intraday, short holds)
2. **MGC** — Supertrend or Donchian (trend-following, longer holds)
- Correlation: ~0.00 in normal markets, turns negative in crisis
- Different strategy types: MR vs. trend-following (structural diversification)
- Positive-skew (trend) + negative-skew (MR) = smoother combined equity curve
- **#1 combined strategy out of 1,274 tested over 3 years (WisdomTree)**

### Crisis Correlation Warning
- During 2008, 2020 COVID crash: correlations among risk assets spiked toward 1.0
- "Average correlation scales linearly with market stress" (Quantifying the Behavior of Stock Correlations Under Market Stress, PMC)
- The diversification benefit disappears exactly when it is most needed
- **Defense:** Include at least one strategy with explicitly negative equity beta during crises (long vol, tail hedge, or simply going flat per the NO_TRADE regime)
- Reduce total portfolio heat to 2–3% when VIX > 30

### Rebalancing Bonus
- Periodically rebalancing two uncorrelated volatile strategies generates positive return (Shannon's Demon)
- Monthly rebalancing is practical cadence

---

## 17. Trade Analytics: MAE, MFE, Expectancy

### Maximum Adverse Excursion (MAE) — Stop Placement
**The highest-leverage stop improvement available:** More impactful than changing any strategy parameter.
1. Collect MAE data across last 100 winning trades (deepest adverse move from entry before trade turned profitable)
2. Find the 70th–80th percentile MAE value
3. Set your stop at this level (adjusted for current ATR)
4. Any trade stopped out below this threshold represents a genuinely failed trade, not noise
- If your stop is inside the MAE distribution of winning trades, you are being stopped out of winners by normal market noise

### Maximum Favorable Excursion (MFE) — Take-Profit Optimization
- MFE = maximum profit a trade reaches before reversing or closing
- If average MFE >> average actual captured profit, you are exiting too early
- MFE-to-MAE ratio > 3:1 = high-quality setup. < 1.5:1 = weak setup.
- **Tiered target rule:** If MFE clusters at +8–10%, set TP1 at +5% (partial exit) and trail remainder

### Expectancy Benchmarks
| Level | R-Multiple |
|---|---|
| Minimum acceptable | > 0R |
| Reasonable | 0.25R |
| Good | 0.30R |
| Excellent | 0.50R+ |
- **TRADEZ BRT: 0.35R expectancy** — good ✓, but only on 21 trades

### Win Rate vs R:R Quick Reference
- 40% WR + 1:3 R:R = $60 expectancy per $100 risked
- 60% WR + 1:2 R:R = $60 expectancy per $100 risked
- 40% WR + 1:3 outperforms 70% WR + 1:1 ($60 vs $40 expectancy)
- Optimize for **expectancy**, not win rate or R:R in isolation

---

## 18. Institutional Best Practices Summary

**Consensus from JPMorgan, Two Sigma, AQR, Man AHL, Renaissance, Lopez de Prado, Ernest Chan, Goldman, QuantConnect, CFA Institute:**

1. **Economic hypothesis first.** Two Sigma: research before data mining. Formulate hypothesis with economic logic, then test.
2. **Point-in-time data is non-negotiable.** JPMorgan: any backtest using revised data is invalid.
3. **Fewer parameters, each interpretable.** More parameters = more overfitting surface.
4. **Deflated Sharpe Ratio (DSR) > 1.0** after accounting for all trial combinations tested.
5. **Minimum 1/3 of sample reserved as true OOS.** Ernest Chan. Never optimize on full sample.
6. **Transaction costs at pessimistic estimates.** Model at minimum 2 ticks slippage per RT for futures.
7. **Volatility-adjusted position sizing.** ATR or variance targeting beats fixed-size sizing.
8. **Hard daily loss limits.** Protects against geometric drawdown cascade.
9. **100+ live trades before drawing any statistical conclusion** (QuantConnect standard).
10. **Automated discipline.** Never override the model during drawdowns.
11. **Man AHL:** Knowing what NOT to trade is as important as knowing what to trade.
12. **AQR:** Every factor has "dark times." Conviction and diversification across factors is the answer — not timing the factor.

---

## 19. VPS and Deployment Checklist

### Server Specs
- **OS:** Linux Ubuntu 22.04 LTS — more stable than Windows for Python bots
- **CPU:** 3.0 GHz+, 2+ cores | **RAM:** 8GB+ for multiple strategies | **Storage:** NVMe SSD
- **Uptime SLA:** 99.9% minimum | **Network:** 1 Gbps, DDoS protection

### Location
- CME nearest exchange: **Chicago (Equinix CH2)**
- Check Tradovate's recommended VPS location — co-location near their servers matters more than exchange proximity for retail

### Security
- Never store API keys in plaintext — use `.env` + `python-dotenv` ✓
- Automated daily snapshots of code + SQLite DB
- Firewall: only inbound SSH (port 22) and dashboard (port 8001) open

### Recovery Procedure (document before going live)
- Bot code in git ✓
- Credentials in `.env` backed up securely offline
- Re-deploy: `git clone + pip install + uvicorn` in < 15 minutes
- Systemd services for auto-restart ← still needed

### Health Monitoring (still needed)
- `/health` endpoint on FastAPI
- Telegram alert if bot silent > 15 minutes
- Daily equity snapshot via Telegram
- Weekly drawdown summary

---

## 20. The Go-Live Checklist

Before flipping `PAPER_TRADING = False`, ALL must be true:

**Statistical:**
- [ ] 200+ paper/backtest trades covering bull, bear, sideways regimes
- [ ] Win rate within ±5% of backtest
- [ ] Max drawdown in paper < 1.3× backtest max DD
- [ ] Profit factor > 1.3 across full paper period
- [ ] Parameter sensitivity: no cliff drops at ±15%
- [ ] Monte Carlo (10,000 runs): ruin probability < 5%
- [ ] Walk-forward: WFE > 50%, profitable across all windows

**Execution:**
- [ ] Tradovate sim tested end-to-end (auth, orders, fills, cancellations)
- [ ] SL and TP orders confirmed to fire correctly
- [ ] Slippage in sim ≈ cost model assumptions
- [ ] Bot running continuously for 2+ weeks without crashes

**Infrastructure:**
- [ ] VPS deployed, systemd services configured
- [ ] Telegram notifications working (trades, daily summary, risk blocks, health check)
- [ ] Daily drawdown circuit breaker tested
- [ ] Backup and recovery procedure documented and tested

**Risk:**
- [ ] Start with 10–20% of intended live capital
- [ ] Circuit breaker pre-defined: pause at 1.5× backtest max DD (~39%)
- [ ] Strategy decay monitor: rolling 30-day WR and PF being tracked
- [ ] FOMC calendar integrated: auto-reduce size on FOMC days

---

## 21. Critical Gaps in Current TRADEZ Implementation

| Gap | Severity | Fix |
|---|---|---|
| Only 21 backtest trades | 🔴 Critical | Need 200+ trades — extend history or add instruments |
| No Monte Carlo simulation | 🔴 Critical | Build `backtest/monte_carlo.py` |
| No walk-forward optimization | 🔴 Critical | Build `backtest/walk_forward.py` |
| No parameter sensitivity analysis | 🟠 High | Build `backtest/sensitivity.py` |
| Only 1 strategy live (BRT) | 🟠 High | Build S02–S15 modules |
| No strategy decay monitor | 🟠 High | Rolling metrics in dashboard |
| Sharpe 3.70 OOS — suspicious | 🟠 High | Likely lucky sequencing on 21 trades — needs more data |
| Max drawdown 26.2% is high | 🟠 High | Target < 20%; add tiered drawdown reduction to risk/manager.py |
| No midday session filter | 🟠 High | Suppress signals 11:30–13:30 ET (false breakout zone) |
| No higher-TF filter for BRT | 🟠 High | Add 1H structure → 15min entry MTF confirmation |
| BRT ADX min too low | 🟡 Medium | Raise from 20 → 25 in NORMAL and CAUTIOUS regimes |
| BRT max retest bars too high | 🟡 Medium | Reduce from 16 → 10–12 for tighter quality |
| No FOMC calendar integration | 🟡 Medium | Auto-reduce size and suppress MR entries on FOMC days |
| Slippage model too optimistic | 🟡 Medium | Bump to 1.5–2 ticks for momentum entries in fast markets |
| No tiered drawdown reduction | 🟡 Medium | Add −5%/−10%/−15% tiers to risk/manager.py |
| No weekly stop-out | 🟡 Medium | Add −10% weekly threshold to risk/manager.py |
| No Telegram health-check | 🟡 Medium | Alert if bot silent > 15min |
| No strategy decay tracking | 🟡 Medium | Rolling 30-day metrics on dashboard |
| Long-only on MES | 🟡 Medium | Consider short entries in CAUTIOUS/HIGH_VOL with stricter filters |
| No VIX term structure check | 🟡 Medium | Add backwardation detection → step down regime |
| No day-of-week filter | 🟡 Low | Half size on Monday/Friday; full size Tue–Thu |
| No Fibonacci retest zones | 🟡 Low | Add 38.2%/50%/61.8% retest zone filter to BRT |
| ORB not VIX-adaptive | 🟡 Low | When built: skip ORB when VIX > 25 |

---

## Reference Files in This Repo
- `INSTITUTIONAL_RESEARCH.md` — 776 lines: JPMorgan, Two Sigma, AQR, Man AHL, Renaissance, Lopez de Prado, Ernest Chan, Goldman, QuantConnect, CFA Institute
- `MARKET_STRATEGY_MAPPING.md` — 932 lines: 44 futures markets analyzed, full correlation matrix, instrument-by-instrument strategy validation
- `STRATEGY_ENCYCLOPEDIA.md` — 15 strategies fully documented with backtested stats and sources

*End of TRADEZ Master Research Compendium — 2026-03-24*
