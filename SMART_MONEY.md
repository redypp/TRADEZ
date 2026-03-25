# SMART MONEY & MARKET MICROSTRUCTURE
## Research synthesis for TRADEZ strategy architecture

**Compiled:** 2026-03-25 | **Sources:** 3 research agents covering SMC/ICT, market microstructure, and COT/Volume Profile
**Methodology:** All retail-only claims flagged [UNVERIFIED]. Cross-validated against academic papers, CFTC data, and institutional sources.

---

## 1. THE COMPETITIVE LANDSCAPE — WHO CONTROLS PRICE

### 1.1 The Four Tiers (ES/MES specific)

| Tier | Who | What they do | Your edge vs. them |
|------|-----|-------------|-------------------|
| 1 | **HFT market makers** (Citadel, Jane Street) | Dominate bid-ask spread, 40% of US volume; 10-50ns latency | Do NOT compete on speed. They are a liquidity service. |
| 2 | **HFT latency arb** | Exploit stale quotes, 50% of futures volume | No meaningful competition possible. Avoid strategies requiring fast execution. |
| 3 | **Institutions** (VWAP/TWAP algos) | Slice large orders over time; VWAP benchmarking creates predictable volume patterns | Exploit predictable flow: VWAP time patterns, session volume shapes |
| 4 | **Retail** | Price-takers. CFTC 2024: 95% of accounts < $20K. Median margin $3,840 | Work WITH institutional flows, not against them |

**Key finding:** CFTC 2024 study documents that retail futures traders systematically enter long after price rises and short after price falls — fighting the trend. This is the primary behavioral edge to avoid.

**Where retail can win:**
- Latency doesn't matter for setups on 15min-1h timeframes
- Pattern recognition in order-driven markets
- Exploiting mean-reversion at institutional anchors (VWAP, POC, PDH/PDL)
- Following commercial hedger positioning via COT for direction bias

---

### 1.2 What Actually Moves Price

**Order Flow Imbalance (OFI) — the most academically validated short-term signal:**
- Cont, Kukanov & Stoikov (2014): OFI explains **65% of short-term midpoint price changes** in S&P 500 instruments
- Effect is strongest in large-tick instruments like ES/MES
- Edge decays rapidly beyond 2-5 minutes (HFTs extract most of it faster)
- Practical use: confirms direction before/after entry, not as primary signal

**Liquidity vacuums:**
- Thin order book areas = price moves fast through them, not because of force but lack of resistance
- CME April 2025: 99% above-average volume + 68% below-average book depth = fast sweep through thin area
- Volume Profile "single prints" and gaps represent these — high probability of return visits

**Stop-loss cascades (Osler 2005, SciTech 2024):**
- Stop clusters at obvious levels ARE real and DO create self-reinforcing cascades
- Agents that can identify stop structure can profit from triggering it
- **This is the core mechanism behind PDH/PDL sweeps and the BRT strategy**
- Whether it's deliberate "hunting" or emergent market behavior — the outcome for you is identical

**Institutions need your stop orders:**
- Almgren-Chriss execution model: large orders optimally seek max counterparty depth
- Your stop at a technical level = sell market order when triggered = institutional buy fill
- This is why stops at obvious levels get taken out before the anticipated move

---

## 2. SMART MONEY CONCEPTS (SMC) — WHAT'S ACTUALLY VALIDATED

### 2.1 Validation Table

| SMC Concept | Academic Status | Source | Algorithmic Use |
|-------------|----------------|--------|-----------------|
| Session opens (London 2-5am, NY 7-10am ET) have higher vol | **VALIDATED** | NBER w12413, ScienceDirect 2009 | Use as session filter — necessary but not sufficient |
| Stop-loss clusters create price cascades | **VALIDATED** | Osler 2005, SciTech 2024 | Core BRT/PDH/PDL sweep mechanism |
| Institutions seek liquidity to fill large orders | **VALIDATED** | Almgren-Chriss, Osler 2005 | Level selection: PDH/PDL, equal H/L |
| PDH/PDL sweep → reversal tendency | **VALIDATED** | ResearchGate 2024 EUR/USD study | Sweeps occur ~14.3% of days; predictable reversal |
| HFT withdraws during volatility (amplifies moves) | **VALIDATED** | BIS 955, O'Hara JFE 2015 | Avoid trading during spikes unless well-positioned |
| Options MM delta hedging → directional pressure | **VALIDATED** | ScienceDirect 2015 | SPX gamma environment = macro filter |
| FVGs filled > 60% of time | **INVERTED — WRONG** | Edgeful: >60% REMAIN UNFILLED | Use as S/R zones, NOT fill targets |
| OTE (0.62-0.79 Fib) has predictive power | **UNVERIFIED** | ScienceDirect 2021: no edge vs. random | Skip — no institutional backing |
| Order blocks as ICT defines them — statistical edge | **UNVERIFIED** | No peer-reviewed study | Use as zone filter only |
| Kill zone specific timing windows → superior win rates | **UNVERIFIED** | No peer-reviewed study | Use session filter only (validated) |
| Market Maker Model (accumulate/manipulate/distribute) as repeating pattern | **UNVERIFIED** | Mechanism valid; pattern unverified | Don't rely on specific pattern |
| Wyckoff spring/upthrust | **PARTIALLY** | Practitioner lit, limited peer review | Strong conceptually; validate before live |
| SMC outperforms traditional TA | **UNVERIFIED** | No comparative peer-reviewed study | Don't make this assumption |

**Critical SMC insight:** The most defensible piece is the **session timing** (intraday seasonality — NBER validated) and the **liquidity pool sweep dynamic** (Osler 2005 validated). The specific ICT pattern labels (OB, FVG, OTE) are retail constructs built on top of these validated mechanisms.

### 2.2 Fair Value Gaps — The Most Important Correction

**CRITICAL:** The retail narrative says FVGs are "magnets" that price must fill. This is **statistically incorrect.**

From Edgeful analysis of real futures data (YM):
> **FVGs remain UNFILLED more than 60% of the time.**

Correct use:
- FVG = a zone of previous price imbalance → use as support/resistance (price may react there)
- The 0.5 midpoint level (gap midpoint) is more commonly reached than a full fill
- FVG + Order Block overlap = highest confluence configuration (still [RETAIL CLAIM] on specific probability)
- Trade FROM the FVG edge as a zone, not TO the FVG as a fill target

### 2.3 Order Blocks — Algorithmic Detection

**Python library:** `smtlab/smartmoneyconcepts` or `joshyattridge/smart-money-concepts`

```python
pip install smartmoneyconcepts

import smartmoneyconcepts as smc

fvg_data  = smc.fvg(ohlc)                           # FVG detection
ob_data   = smc.ob(ohlc)                             # Order block detection
liq_data  = smc.liquidity(ohlc, range_percent=0.01)  # Equal H/L within 1%
```

**Valid OB requires:**
1. Last candle opposite to the subsequent impulse direction
2. Following displacement breaks a recent swing high/low (Break of Structure)
3. Volume on displacement significantly above average (institutional confirmation)
4. Zone is "active" until price closes through it (one-time use)
5. Becomes a BREAKER BLOCK when price closes beyond the far edge (flipped role)

---

## 3. COT REPORT — PROGRAMMATIC IMPLEMENTATION

### 3.1 What to Use for Each Market

| Market | COT Report Type | CFTC Code |
|--------|----------------|-----------|
| **Gold (MGC/GC)** | Disaggregated Futures Only | `088691` (COMEX 100oz) |
| **Silver (SIL/SI)** | Disaggregated Futures Only | `084691` (COMEX) |
| **MES/ES (S&P500)** | Traders in Financial Futures (TFF) | CME S&P 500 Consolidated |
| **Crude Oil (MCL/CL)** | Disaggregated Futures Only | `067651` (NYMEX WTI) |

**Publication:** Tuesday positions, Friday 3:30pm ET release → **3-day lag**. Not for short-term entries; use as weekly directional bias.

### 3.2 COT Index Formula

```
COT Index = 100 × (Current Net Position − Min(N)) / (Max(N) − Min(N))
```

- **N = 156 weeks (3 years)** — Larry Williams default; practitioner consensus
- Net Position = Longs − Shorts for the category
- Signal: Index > 80 = Commercials bullish; Index < 20 = Commercials bearish
- For Managed Money (speculative): **use as contrarian** (MM > 80 = crowded long = late-cycle)

### 3.3 Download Code

```python
import pandas as pd, numpy as np, requests, zipfile, io

GOLD_CODE = "088691"
LOOKBACK_WEEKS = 156

def download_cot_disaggregated(year: int) -> pd.DataFrame:
    url = f"https://www.cftc.gov/files/dea/history/fut_disagg_txt_{year}.zip"
    r = requests.get(url, timeout=30); r.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        return pd.read_csv(io.BytesIO(z.read(z.namelist()[0])), low_memory=False)

def build_gold_cot_index(years: list, lookback: int = LOOKBACK_WEEKS) -> pd.DataFrame:
    raw = pd.concat([download_cot_disaggregated(y) for y in years], ignore_index=True)
    gold = raw[raw['CFTC_Commodity_Code'] == GOLD_CODE].copy()
    gold['Report_Date'] = pd.to_datetime(gold['Report_Date_as_YYYY-MM-DD'])
    gold = gold.sort_values('Report_Date').reset_index(drop=True)

    gold['prod_net'] = gold['Prod_Merc_Positions_Long_ALL'] - gold['Prod_Merc_Positions_Short_ALL']
    gold['mm_net']   = gold['M_Money_Positions_Long_ALL']   - gold['M_Money_Positions_Short_ALL']

    def cot_index(s, n):
        return 100 * (s - s.rolling(n).min()) / (s.rolling(n).max() - s.rolling(n).min() + 1e-9)

    gold['prod_index'] = cot_index(gold['prod_net'], lookback)
    gold['mm_index']   = cot_index(gold['mm_net'],   lookback)
    gold['mm_zscore']  = (gold['mm_net'] - gold['mm_net'].rolling(lookback).mean()) / gold['mm_net'].rolling(lookback).std()

    return gold[['Report_Date', 'prod_net', 'mm_net', 'prod_index', 'mm_index', 'mm_zscore']]

# pip install cot-reports  (alternative simpler library)
```

### 3.4 Academic Consensus on COT Predictive Power

| Market | Edge | Caveats |
|--------|------|---------|
| Gold / Precious metals | Moderate | Zhang & Laws 2013: "highly profitable vs naïve long" but Granger causality weak |
| S&P 500 (ES/MES) | Weak | Chen & Maher 2013: correlation present but unstable across time |
| Agricultural | Very weak | Sanders, Irwin & Merrin 2009: little Granger causality |
| General | Filter only | Best as directional weekly bias; extremes (> 90 / < 10) most reliable |

**Bottom line:** Use COT as a **weekly bias filter** (not entry timing) for MGC trades. For MES, COT has weaker edge — regime filter via VIX is more reliable.

---

## 4. VOLUME PROFILE — INSTITUTIONAL LEVELS

### 4.1 Core Concepts

| Level | Definition | Practical Use |
|-------|-----------|--------------|
| **POC (Point of Control)** | Price with most volume in the period | Fair value anchor; S/R from both sides |
| **VAH (Value Area High)** | Upper bound of 70% volume zone | Resistance; short fade above here |
| **VAL (Value Area Low)** | Lower bound of 70% volume zone | Support; long bounce below here |
| **Single Prints / Gaps** | Price moved through with minimal volume | High probability return visit (thin area) |

**The 70% rule:** The VA contains 70% of volume because price in a normal distribution falls within ±1 SD ~68% of the time. The "price returns to VA 80% of the time" is a [RETAIL CLAIM - UNVERIFIED] — no peer-reviewed study establishes this number. Treat VAH/VAL as reaction zones, not guaranteed magnets.

### 4.2 Python Volume Profile Calculation

```python
def calculate_volume_profile(df: pd.DataFrame, n_bins: int = 50) -> dict:
    """
    Calculate Volume Profile from OHLCV data.
    Returns POC, VAH, VAL, and full profile dict.
    """
    price_min = df['low'].min()
    price_max = df['high'].max()
    bins = np.linspace(price_min, price_max, n_bins + 1)

    volume_at_price = np.zeros(n_bins)
    for _, row in df.iterrows():
        # Distribute bar volume uniformly across its price range
        low_idx  = np.searchsorted(bins, row['low'],  side='left')
        high_idx = np.searchsorted(bins, row['high'], side='right')
        low_idx  = max(0, min(low_idx,  n_bins - 1))
        high_idx = max(0, min(high_idx, n_bins - 1))
        if high_idx > low_idx:
            volume_at_price[low_idx:high_idx] += row['volume'] / max(1, high_idx - low_idx)
        else:
            volume_at_price[low_idx] += row['volume']

    bin_mids = (bins[:-1] + bins[1:]) / 2
    poc_idx = np.argmax(volume_at_price)
    poc = float(bin_mids[poc_idx])

    # Value Area: 70% of total volume
    total_vol = volume_at_price.sum()
    target = total_vol * 0.70

    sorted_idx = np.argsort(volume_at_price)[::-1]
    accumulated = 0.0
    va_indices = []
    for idx in sorted_idx:
        accumulated += volume_at_price[idx]
        va_indices.append(idx)
        if accumulated >= target:
            break

    va_prices = [bin_mids[i] for i in va_indices]
    vah = float(max(va_prices))
    val = float(min(va_prices))

    return {
        'poc': poc, 'vah': vah, 'val': val,
        'profile': dict(zip(bin_mids.tolist(), volume_at_price.tolist())),
    }
```

### 4.3 VPOC Migration

A VPOC that migrates to a new price level signals that the market's assessment of fair value has shifted:
- **VPOC moving higher** (in an uptrend) = institutional agreement that higher prices represent new fair value — trend confirmation
- **VPOC moving lower** (in a downtrend) = same logic, bearish
- **VPOC staying fixed despite price ranging** = strong balance; fade-the-range conditions
- **Price far from VPOC** = imbalance; mean-reversion opportunity back to VPOC

---

## 5. IMPLICATIONS FOR STRATEGY ARCHITECTURE

### 5.1 Layer Framework — How to Integrate

```
Layer 1 — MACRO CONTEXT (weekly, do NOT change intraday)
  ├── VIX regime (TRENDING/NORMAL/CAUTIOUS/HIGH_VOL/NO_TRADE)
  ├── COT weekly bias: Prod Index > 80 = long MGC bias; MM zscore < -1.5 = contrarian long MGC
  └── DXY / yield trend direction

Layer 2 — INSTITUTIONAL LEVELS (daily, set before session)
  ├── Previous Day High/Low (PDH/PDL) — stop cluster zones
  ├── VWAP (resets at 9:30 AM ET)
  ├── Volume Profile: POC, VAH, VAL (prior session)
  └── FVG zones from prior session (use as S/R, NOT fill targets)

Layer 3 — SMC CONTEXT (per bar)
  ├── Are we above/below VWAP? (institutional fair value bias)
  ├── Active OB zones on HTF that price is approaching?
  ├── Recent liquidity sweep? (PDH/PDL swept → reversal setup active)
  └── In kill zone? (London 7-10am ET, NY open 9:30-11am ET)

Layer 4 — ENTRY TRIGGER (signal generation)
  ├── BRT: Break + Retest of institutional level (primary)
  ├── VWAP MR: Deviation > 1.5σ + reversal candle (when ADX < 30)
  ├── RSI(2): Extreme oversold + price above SMA200 (daily stocks)
  └── Donchian: 20-day breakout (MGC trend following, daily)
```

### 5.2 BRT + SMC Enhancement Roadmap

The BRT strategy is already working with institutional levels (VWAP, PDH/PDL). The SMC research suggests two enhancements:

**Enhancement 1 — Liquidity sweep filter (HIGH PRIORITY):**
Before entering a BRT long after price breaks above a level:
- Check: did price first sweep BELOW the nearest liquidity pool (equal lows, PDL)?
- If YES → buy-side liquidity was collected → BRT long signal has higher probability
- If NO → price might not have collected sufficient fuel for the move

**Enhancement 2 — FVG confluence (MEDIUM PRIORITY):**
- If a BRT retest zone also contains an open FVG → higher confluence
- Use `smc.fvg(ohlc)` to detect; check for FVG within BRT_LEVEL_TOLERANCE × ATR

**Enhancement 3 — Kill zone timing (LOW PRIORITY — partially implemented):**
- Already have BRT_SESSION_START_HOUR (10 AM) and BRT_SESSION_END_HOUR (3 PM)
- Could tighten to NY Open (9:45-11:30 AM) and early afternoon (1:00-2:30 PM) kill zones
- Validate empirically first — session timing filter is already quite conservative

### 5.3 MGC Strategy: COT + Donchian

For MGC (Micro Gold):
1. **COT macro filter (weekly):** Producer Index > 80 = bias long. MM Index < 20 = confirming.
2. **Volume Profile levels (daily):** POC as entry target; VAH/VAL as reaction zones.
3. **Donchian breakout (existing):** 20-day high/low breakout as entry signal.
4. **Exit:** Donchian 10-day trailing channel OR COT reversal (Prod Index crossing back below 70).

This combines the institutionally-grounded COT signal (weekly bias) with the backtested Donchian entry timing — neither alone is optimal, together they address COT's timing weakness.

---

## 6. CRITICAL GAPS & NEXT STEPS

| Priority | Gap | Action |
|----------|-----|--------|
| 🔴 Critical | No COT module in strategy pipeline | Build `strategy/cot_filter.py` |
| 🔴 Critical | Volume Profile not computed from data | Build `strategy/volume_profile.py` |
| 🔴 Critical | BRT doesn't check for liquidity sweep confirmation | Add to `break_retest.py` |
| 🟡 Medium | OB detection not integrated | Add `smtlab/smartmoneyconcepts` integration |
| 🟡 Medium | FVG confluence not used in BRT | Add FVG zone check |
| 🟡 Medium | Kill zone not specifically targeting London open | Extend session filter |
| 🟢 Low | Wyckoff spring/upthrust detection | Later — lower priority than above |
| 🟢 Low | Spoofing/DOM data analysis | Requires Level 2 data feed |

---

## Sources

- NBER Working Paper w12413 (Ito & Hashimoto): Intraday seasonality in FX
- Cont, Kukanov & Stoikov (2014): Order flow imbalance and price changes
- Osler (2005): Stop-loss orders create cascades in currency markets
- BIS Working Paper 955: HFT arms race and liquidity withdrawal
- BIS Working Paper 1290: Latency arbitrage
- O'Hara (2015, JFE): High-frequency market microstructure
- CFTC (2024): Retail Traders in Futures Markets
- ScienceDirect 2021: Fibonacci no edge vs. random zones
- ResearchGate 2024: EUR/USD PDH/PDL liquidity pool study
- SciTech 2024: Agent-based stop-loss cascade model
- Zhang & Laws (2013, SSRN): COT as precious metal predictor
- Dreesmann et al. (2023): COT as trading signal — inconsistent across markets
- Edgeful: FVG fill statistics (>60% unfilled)
- Park & Irwin (2007, SSRN): Comprehensive TA profitability review
- CME Group (2025): April volatility episode — volume vs. book depth
- joshyattridge/smart-money-concepts (GitHub)
- smtlab/smartmoneyconcepts (GitHub)
- NDelventhal/cot_reports (GitHub)
