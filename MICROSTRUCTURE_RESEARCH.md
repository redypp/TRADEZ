# Market Microstructure & Competitive Landscape Research
> Agent-compiled research with cross-validation against CFTC, BIS, Federal Reserve, SSRN, and peer-reviewed journals.
> Completed 2026-03-25.

---

## Section 1: Who Controls Price

### Market Makers
- Profit from bid-ask spread capture, delta hedging (options MMs), and exchange rebates
- Citadel Securities + Jane Street ≈ 40% of U.S. market-making activity
- HFTs have largely replaced exchange specialists (Hagströmer & Nordén, 2013)
- Co-located sub-millisecond response; retail is 5–7 orders of magnitude slower

### HFT Volume & Strategies
- ~50% of all U.S. equity/futures volume is HFT
- **Latency arbitrage:** NASDAQ NBBO calculated by HFTs 1.5ms ahead of public SIP feed; ~$5B/year across equities
- **Electronic market making:** Posts both sides; **withdraws liquidity during volatility spikes** (self-reinforcing crashes)
- **Stat arb:** Exploits ES↔SPY, index component correlations
- DAX futures: orders modified within 1ms rose from 11% (2019) → 17% (2024) — arms race accelerating

### Institutions
- VWAP algos: slice orders proportionally to volume; larger near open/close
- TWAP: equal slices with ±10–20% randomization to prevent front-running
- Iceberg orders: only 10% of size visible (100-lot iceberg shows 10 contracts)
- **Implication: visible order book understates true demand/supply at levels**

### Retail Structural Disadvantages (CFTC 2024, 36,538 accounts)
- Median futures account: $3,840 margin; 95% of accounts < $20k
- Latency gap: 50–500ms retail vs. 10–50ns HFT — structurally insurmountable
- Documented behavioral failure: contrarian entry (buy after fall, sell after rise) driven by price anchoring
- Excessive leverage = single strongest predictor of worst outcomes (t-stat: 28.263)

---

## Section 2: How Price Actually Moves

### Auction Market Theory (AMT) — Institutionally Validated
- Originated: Peter Steidlmayer at CBOT, 1985 (exchange-published)
- **Value Area:** 68–70% of day's volume; price spends 70–80% of time inside
- **POC (Point of Control):** Highest-volume price = clearest fair value
- **Initial Balance (IB):** First-hour range (9:30–10:30 ET); rest of day measured against it
- **Implication:** VWAP, PDH/PDL, ORH/ORL in BRT are institutionally recognized AMT reference levels

### Order Flow Imbalance (OFI) — Most Academically Validated Short-Term Edge
- **Cont, Kukanov & Stoikov (2014):** OFI explains up to **65% of midpoint change variation** in S&P 500
- **Gould & Bonart (2016):** Queue imbalance correctly predicts direction of next midpoint move (statistically significant)
- **NBER w30366 (2022):** Bid-ask imbalance is the **top-ranked predictor** of future short-term returns; signal over 0.1 second window
- **Federal Reserve (2025):** OFI amplifies moves during low-liquidity conditions in Treasury markets
- **Ceiling:** Edge is sub-minute. Decays rapidly beyond 1–2 minutes. HFTs exploit at nanosecond speed.
- **Implementation note:** Requires Level 2 / streaming tick data — NOT available from yfinance OHLCV

### Stop Hunting: Deliberate vs. Emergent
- Stop-loss orders cluster predictably at swing highs/lows, round numbers, prior session extremes
- Institutions need large liquidity pools to fill their own orders without adverse price movement
- Academic consensus: **whether deliberate or emergent, the outcome for retail is the same**
- Osler (2005): stop-loss order cascades documented in currency markets
- **Practical rule:** Place stops at levels that *invalidate the trade thesis*, not at obvious chart features

### Liquidity Vacuums
- CME (April 2025): ES volume was 99% above average while order book depth fell 68% — high volume ≠ deep liquidity
- Fed research: volatility spikes increase liquidity demand while MMs withdraw supply → fast moves through thin areas
- **BRT system alignment:** Volume threshold on break candle already filters for genuine participation

---

## Section 3: Volume Spread Analysis (VSA)

### Key Bullish VSA Signals (Wyckoff/Tom Williams)
| Signal | Volume | Spread | Close Position | Implication |
|--------|--------|--------|----------------|-------------|
| Selling Climax | Very High | Wide, down | Upper half | Supply exhaustion |
| No Supply | Low | Narrow | Upper half | Professionals not selling |
| Test | Low | Any | Upper half | Confirms absence of supply |
| Spring | High → Low | Wide wick below support | Recovers | Stop-hunt confirmation |

### Key Bearish VSA Signals
| Signal | Volume | Spread | Close Position | Implication |
|--------|--------|--------|----------------|-------------|
| Buying Climax | Very High | Wide, up | Lower half | Demand exhaustion |
| Upthrust | High | Breaks above, closes below | Lower half | Supply overwhelming demand |
| No Demand | Low | Narrow | Lower half | Professionals not buying |

### Python Detection Thresholds (from research)
```python
# Vol/spread ratios (relative to 20-bar moving averages)
no_demand_long  = spread < spread_ma * 0.7 and volume < vol_ma * 0.7 and close_pos < 0.4 and close < open
no_supply_short = spread < spread_ma * 0.7 and volume < vol_ma * 0.7 and close_pos > 0.6 and close > open
selling_climax  = volume > vol_ma * 2.0 and spread > spread_ma * 1.5 and close_pos > 0.6
upthrust        = high > prior_high and close < prior_high and volume > vol_ma * 1.2
```

### Academic Validation
- **No formal peer-reviewed validation for VSA specifically**
- Validated by adjacent literature: OFI research (effort vs. result principle), AMT (volume at extremes)
- Curriculum at Golden Gate University (practitioner institution)
- **Implementation caveat:** VSA requires structural context — same bar means different things at different locations

---

## Section 4: Tape Reading for Algos

### Bid-Ask Imbalance (Most Validated)
- NBER w30366: top predictor of short-term returns; strongest at 0.1 second resolution
- Cont et al. 2014: 65% of midpoint change explained
- **Practical threshold (practitioner-derived):** 60%+ imbalance ratio is directional; needs absolute size filter
- **Ceiling:** Edge degrades rapidly; HFTs exploit at nanosecond speed

### Cumulative Delta Divergence
- Tracks running (buy market orders − sell market orders)
- Divergence: price makes new low, delta makes higher low = buyers absorbing selling
- [UNVERIFIED] in peer-reviewed literature as standalone signal
- Underlying mechanism validated: Cont et al., Gould & Bonart
- **Requires:** Streaming tick data (not OHLCV)

---

## Section 5: Where Retail Traders Lose Money

### Academic Evidence (Brazil, Taiwan Studies)
- **97% of traders who persisted 300+ days in Brazil futures lost money**
- **Less than 1% of day traders earn meaningful persistent returns** (Taiwan TAIFEX, 15-year study)
- Barber, Lee, Liu & Odean (2009): less than 1% of day traders predictably earn positive abnormal returns net of fees

### What Distinguishes Winners (CFTC 2024)
| Factor | Winners | Losers |
|--------|---------|--------|
| Leverage | Lower initial margin relative to account | Higher (key predictor of worst outcomes) |
| Timing | Efficient entry/exit | Enter/exit late |
| Response to loss | Reassess and reduce | Continue same frequency |

### MES Transaction Costs — All-In Round Turn
| Component | Round Turn |
|-----------|------------|
| Broker commission | $0.18–$1.00 |
| CME exchange fee | $0.54–$0.70 |
| NFA fee | $0.04 |
| Slippage (market orders) | $0.00–$2.50 |
| **Total (limit orders)** | **~$0.76–$1.74** |
| **Total (market orders)** | **~$1.01–$4.24** |

**BRT config $2.94/RT** = reasonable mid-range. At 47.6% win rate, 2:1 R:R, minimum gross edge needed = 0.59 pts = 2.4 ticks per trade.

---

## Key Implications for BRT/MES

### Validated ✅
1. VWAP/PDH/PDL/ORH/ORL as key levels — institutionally recognized AMT reference levels
2. Volume confirmation on break candle — VSA + OFI backed
3. ADX filter + regime-adaptive params — addresses ranging market failure mode (price in VA 70–80% of time)
4. 1% risk / 3% daily stop-out — directly addresses CFTC finding on leverage as top loss predictor
5. ATR-based stop placement — reduces stop-hunt exposure vs. exact level stops

### Risks Flagged ⚠️
1. 21 trades statistically insufficient (200–300 required) — already flagged
2. No order flow/Level 2 data — highest-leverage microstructure upgrade available; requires Tradovate WebSocket
3. No formal VSA confirmation on retest candle volume (currently only close position checked)
4. Stop placement near well-known institutional levels — ATR buffer helps but risk remains
5. yfinance latency — 15-min bars avoid OFI ceiling, but any sub-minute signals require streaming data

