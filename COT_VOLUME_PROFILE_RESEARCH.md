# COT Report + Volume Profile: Algorithmic Trading Research
> Agent-compiled research with cross-validation against CFTC, academic papers, and institutional sources.
> Completed 2026-03-25.

---

## PART 1: COT REPORT — CRITICAL IMPLEMENTATION NOTES

### Which Report Type to Use

| Instrument | Correct Report | Category of Interest |
|---|---|---|
| ES / MES (S&P 500 futures) | **TFF (Traders in Financial Futures)** | Leveraged Funds (contrarian) |
| GC / MGC (Gold) | **Disaggregated** | Producer/Merchant (directional), Managed Money (contrarian) |
| SIL / SI (Silver) | **Disaggregated** | Same as Gold |
| EUR/USD, currencies | **TFF** | Leveraged Funds |

**CRITICAL:** ES/MES uses the CME S&P 500 Consolidated series (combines ES + MES)

### Download URLs
```
Disaggregated Futures Only:  https://www.cftc.gov/files/dea/history/fut_disagg_txt_{YEAR}.zip
TFF Futures Only:            https://www.cftc.gov/files/dea/history/fut_fin_txt_{YEAR}.zip
COMEX Gold CFTC Code:        088691
```

### COT Index Formula (Larry Williams / Standard)
```
COT Index = 100 × (Current Net - Min over N weeks) / (Max over N weeks - Min over N weeks)
Net Position = Longs - Shorts
```
- **Default lookback N = 156 weeks (3 years)** — Williams' published default
- Signal thresholds: Producer Index > 80 = bullish; < 20 = bearish
- Managed Money Index > 85 = contrarian short; < 25 = contrarian long

### Academic Validation Summary
| Paper | Finding |
|---|---|
| Chen & Maher (2013), J. International Financial Markets | COT has some predictive content for S&P500, **unstable across time** |
| Dreesmann et al. (2023), SSRN | COT-only strategy: 6 markets outperformed in long-only; portfolio-level did not exceed Sharpe benchmark |
| Zhang & Laws (2013), SSRN | Gold/Metals: Granger causality **weak** — returns lead positioning, not reverse. Trading system constructed from signals was profitable vs. naive long. |
| Sanders et al. (2009), Agri. markets | Little Granger causality; traders respond to price, not predict it |

**Consensus:** COT as a weekly BIAS FILTER, not a precise entry trigger. Lag is 3 days (Tuesday close → Friday release). Extremes (Index > 90 or < 10) more reliable than mid-range.

### Python Library
```bash
pip install cot-reports  # github.com/NDelventhal/cot_reports
```
```python
import cot_reports as cot
df = cot.cot_all(cot_report_type='disaggregated_futures_only')
gold = df[df['Market_and_Exchange_Names'].str.contains('GOLD')]
```

---

## PART 2: VOLUME PROFILE — KEY SIGNALS

### Core Concepts
- **POC (Point of Control):** Price with highest traded volume = consensus fair value
- **Value Area (VA):** 70% of volume (based on normal distribution, ±1 std dev convention)
- **VAH/VAL:** Value Area High/Low — NOT "price returns here 80% of the time" (that's [UNVERIFIED])
- **HVN:** High Volume Node = price decelerates, acts as S/R
- **LVN:** Low Volume Node = price accelerates, natural stop zone

### VPOC Migration Signal
- **3+ consecutive sessions of POC migrating higher** = institutional accumulation, bullish bias
- **3+ sessions migrating lower** = distribution, bearish bias
- **Price at highs but VPOC not migrating up** = smart money selling into rally (bearish divergence)
- **Naked VPOC** (prior session POC not revisited) = price magnet — market likely to return

### Session vs. Composite Profile
| Type | Period | Use For |
|---|---|---|
| Session Profile | Single RTH day | Intraday entries; prior session POC/VAH/VAL as next-day reference |
| Composite Profile | Multiple days/weeks | Swing levels; macro HVN/LVN zones |
| Monthly Composite | ~22 days | Long-term institutional reference; monthly POC breaks = major moves |

### Academic Validation
- No peer-reviewed study validates specific "return-to-VA" percentage
- 70% VA construction is a statistical convention, not a predictive claim
- Theoretical foundation (normal distribution model for auction markets) is sound

---

## PART 3: COMBINING COT + VOLUME PROFILE

### Signal Logic
```
LONG SETUP:
  1. COT: Producer Index > 75 OR Managed Money Index < 25 (weekly bias)
  2. Price at or below prior session VAL
  3. Close back above VAL (responsive buying confirmation)
  ENTRY: Bar close | SL: VAL - 1×ATR | TP1: POC | TP2: VAH

SHORT SETUP:
  1. COT: Managed Money Index > 85 (crowded long, contrarian)
  2. Price at or above prior session VAH
  3. Close back below VAH (responsive selling confirmation)
  ENTRY: Bar close | SL: VAH + 1×ATR | TP1: POC | TP2: VAL
```

### Critical Caveats
1. **3-day COT lag** — data from Tuesday, released Friday, applied Mon–Fri next week
2. **COT Index at 90 can stay at 90** for months (Gold 2024–2025 documented example)
3. **"80% return to value area" claim is UNVERIFIED** — no peer-reviewed backing
4. **No peer-reviewed study combines COT + Volume Profile** — this is practitioner-originated; you are the backtester
5. **Futures volume only** — VP only reliable for exchange-reported volume (ES, MES, GC, MGC, CL)

---

## Market Profile (TPO) Additional Signals

| Signal | Description | Predictive Use |
|---|---|---|
| Single Prints | One TPO letter at a level = impulsive move | Market returns to fill; "unfinished business" |
| Poor High | Multiple TPOs bunched at top, no tail | Incomplete auction; likely to extend higher |
| Poor Low | Multiple TPOs bunched at bottom, no tail | Incomplete auction; likely to extend lower |
| Open Drive (OD) | Opens and immediately trends | Trend day; ride direction |
| Open Rejection Reverse (ORR) | Opens outside VA, fails, reverses | Fade open; rotational day |
| Open Auction in Range (OAIR) | Opens inside VA | Low conviction; fade extremes |

**Source pedigree:** Steidlmayer/CBOT (1985), Dalton *Mind Over Markets* (1990). Practitioner-validated, limited peer-reviewed academic backing.

