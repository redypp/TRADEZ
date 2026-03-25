# Smart Money Concepts — Advanced Research Report
> Agent-compiled research with academic source validation. Completed 2026-03-25.
> All claims rated VALIDATED or [RETAIL CLAIM - UNVERIFIED].

---

## Validated vs. Unverified Claims

| Claim | Verdict | Best Source |
|-------|---------|-------------|
| Session opens (London, NY) have higher volatility/volume | ✅ VALIDATED | NBER w12413, ScienceDirect 2009 |
| Stop-loss clusters create price cascades | ✅ VALIDATED | Osler 2005, SciTech 2024 |
| Institutions seek liquidity zones to fill large orders | ✅ VALIDATED | Almgren-Chriss, Osler 2005 |
| HFT withdraws liquidity during volatility (amplifies moves) | ✅ VALIDATED | BIS 955, O'Hara JFE 2015 |
| Options MM delta hedging creates directional pressure | ✅ VALIDATED | ScienceDirect 2015, GammaEdge |
| Spoofing/layering is real and documented | ✅ VALIDATED | CFTC, arXiv 2024 |
| Intraday seasonality is statistically significant | ✅ VALIDATED | NBER, multiple papers |
| PDH/PDL sweep → reversal tendency (~14.3% of days) | ✅ VALIDATED | ResearchGate EUR/USD 2024 |
| FVGs are filled >60% of the time | ❌ INVERTED — >60% UNFILLED | Edgeful.com data |
| OTE (0.62–0.79 Fib) has predictive power | ❌ UNVERIFIED | ScienceDirect 2021 finds no edge |
| Order blocks as defined by ICT have statistical edge | ❌ UNVERIFIED | No peer-reviewed studies |
| Kill zone specific windows produce superior win rates | ❌ UNVERIFIED | No peer-reviewed study |
| SMC outperforms traditional TA | ❌ UNVERIFIED | No comparative study |
| Market Maker accumulate/manipulate/distribute pattern | ⚠️ MECHANISM VALID, PATTERN UNVERIFIED | Mechanism: options gamma lit |
| Wyckoff spring/upthrust as high-probability setup | ⚠️ PARTIALLY VERIFIED | Practitioner literature |

---

## Section 1: SMC — Algorithmic Detection

### Order Blocks
- Last opposing candle before impulsive BOS move
- `smtlab/smartmoneyconcepts`: `smc.ob(ohlc)` — returns zone boundaries, volume, strength %
- `joshyattridge/smart-money-concepts` — also includes BOS/CHoCH, EQH/EQL detection
- **Invalidation (breaker conversion):** price closes beyond far edge → zone flips role
- ⚠️ No peer-reviewed validation for OB-specific edge

### Fair Value Gaps (FVGs)
- Three-candle rule: candle[i-1].high < candle[i+1].low (bullish FVG)
- **KEY FINDING: >60% of FVGs NEVER fill** (Edgeful, YM futures data)
- Correct use: treat as S/R zones, NOT fill targets
- 0.5 midpoint more commonly reached than full fill
- OB + FVG overlap = highest-probability zone by practitioners
- `smc.fvg(ohlc)` — deterministic, fully backtestable

### Equal Highs/Lows (EQH/EQL) — Liquidity Pools
- EQH: 2+ swing highs within N-ATR of each other → dense stop cluster above (buy-side liquidity)
- EQL: 2+ swing lows within N-ATR → sell-side liquidity
- PDH/PDL sweep events: ~14.3% of EUR/USD trading days (ResearchGate 2024)
- **Reversal tendency after sweep is statistically validated** (Osler 2005 + ResearchGate 2024)
- `joshyattridge/smart-money-concepts`: includes EQH/EQL detection with `range_percent` param

### Breaker Blocks
- Failed OB that closed through its far edge → flipped role (S becomes R, vice versa)
- Analogous to classical S/R flip — has indirect academic backing
- State-tracking required: active OB → breaker → possibly back to OB if breaker fails

---

## Section 2: ICT — Validated Components

### Kill Zones (ET times)
| Zone | Time | Academic Basis |
|------|------|----------------|
| Asian | 7 PM – 10 PM | Consolidation; range-building |
| London Open | 2 AM – 5 AM | Sweeps Asian range; sets daily bias |
| NY Open | 7 AM – 10 AM | Highest volume; London/NY overlap |
| London Close | 10 AM – 12 PM | Institutional position squaring |

- NBER w12413 validates session opens as structurally higher volatility/volume
- NY lunch (12–1 PM ET) as dead zone: validated by intraday seasonality literature
- Specific window win-rate claims: ❌ UNVERIFIED

### OTE (Optimal Trade Entry) — 0.62–0.79 Fibonacci
- ScienceDirect 2021: Fibonacci zones statistically indistinguishable from non-Fibonacci zones
- ❌ The specific 0.62–0.79 claim has no independent peer-reviewed validation
- May work as stop-placement logic (tight risk at 100% level), not because Fibonacci is predictive

---

## Section 3: How Institutions Actually Move Price

### Market Maker Mechanics
- MMs are delta-neutral, not directional — their hedging creates secondary flows
- **Options gamma amplification:** In negative-gamma environment, delta hedges amplify existing moves
- Jane Street + Citadel Securities: $30.2B in 2024 derivatives trading revenue (~3× comparable hedge funds)
- "There's little evidence that MMs systematically hunt stop levels" — GammaEdge
- But: stop-loss cascade dynamics are real (Osler 2005, SciTech 2024)

### HFT and Stop Cascades
- SciTech 2024 (agent-based model): agent identifying stop-order structure can profit from triggering cascades
- Over 1/3 of limit orders cancelled within 2 seconds (Hasbrouck & Saar 2009) — HFT fleeting orders
- O'Hara JFE 2015: "HFT strategies maximize against market design, other HFTs, and other traders"

### Why Price Gravitates to Liquidity (Most Validated SMC Mechanism)
1. Institutional order size requires counterparty → retail stop clusters provide fills (Osler 2005)
2. Almgren-Chriss execution model: large orders seek levels of maximum counterparty depth
3. Self-fulfilling: as SMC adoption grows, equal highs/lows become more predictable → potential crowding decay

---

## Section 4: Python Libraries

| Library | GitHub | Key Features |
|---------|--------|-------------|
| `smtlab/smartmoneyconcepts` | github.com/smtlab/smartmoneyconcepts | FVG, OB, H/L, Liquidity, `range_percent` |
| `joshyattridge/smart-money-concepts` | github.com/joshyattridge/smart-money-concepts | FVG, OB, EQH/EQL, BOS/CHoCH |
| `starckyang/smc_quant` | github.com/starckyang/smc_quant | Full algo + backtesting.py integration |

```python
import smartmoneyconcepts as smc
fvg_data = smc.fvg(ohlc)           # FVG detection
ob_data  = smc.ob(ohlc)            # Order block detection  
liq_data = smc.liquidity(ohlc, range_percent=0.01)  # Equal H/L within 1%
```

---

## Key Takeaways for TRADEZ

1. **Kill zones = necessary filter** (not signal). London/NY opens validated by intraday seasonality lit.
2. **FVGs = S/R zones only.** >60% never fill. Add as levels, not targets.
3. **Liquidity sweep is the most validated SMC concept.** Already implemented (liquidity_sweep flag).
4. **EQH/EQL as levels.** Direct academic backing for stop-cluster dynamics at equal highs/lows.
5. **No SMC concept has standalone peer-reviewed validation.** Build on the validated mechanisms (liquidity dynamics, stop cascades, intraday seasonality).
6. **For rigorous backtesting:** `smtlab/smartmoneyconcepts` + `backtesting.py` + walk-forward + post-2022 OOS test.
