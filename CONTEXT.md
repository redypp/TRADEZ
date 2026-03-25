# TRADEZ — Project Context
> Paste this file at the start of any new Claude chat to restore full context instantly.
> Last updated: 2026-03-25

---

## What This Is

An automated CME micro-futures trading bot and strategy research platform.

- **Primary broker:** Tradovate (futures, commission-based, sim account available)
- **Scheduler:** APScheduler — runs every hour at :02, Mon–Fri, 10:00–15:00 ET
- **Dashboard:** FastAPI + vanilla JS — tabs: Live | Strategies | Methods | Strategy Lab
- **Notifications:** Telegram (trade alerts, risk blocks, daily summary)
- **Data:** yfinance for OHLCV + fundamentals (VIX, 10Y yield, DXY)
- **DB:** SQLite via trade_log.py (trades, equity curve, events feed)
- **Full research:** See `RESEARCH.md` for the complete strategy validation framework

---

## Repo Structure

```
TRADEZ/
├── scheduler.py              ← production bot entry point
├── config/settings.py        ← all strategy + broker params
├── strategy/
│   ├── break_retest.py       ← S01: BRT signal engine (MES, 15-min) ✅
│   ├── orb.py                ← S02: Opening Range Breakout
│   ├── vwap_mr.py            ← S03: VWAP Mean Reversion
│   ├── ema_crossover.py      ← S04: EMA Crossover + ADX filter
│   ├── supertrend.py         ← S05: Supertrend (ATR-based trailing)
│   ├── bollinger_mr.py       ← S06: Bollinger Band Mean Reversion
│   ├── rsi_pullback.py       ← S07: RSI Pullback in Trend
│   ├── macd_momentum.py      ← S08: MACD Momentum
│   ├── donchian.py           ← S09: Donchian Channel Breakout ✅ (partial)
│   ├── keltner_squeeze.py    ← S10: Keltner Channel Squeeze
│   ├── momentum_breakout.py  ← S11: Momentum Breakout (volume)
│   ├── rsi2_daily.py         ← S07: RSI(2) Daily mean reversion (stocks) ✅
│   ├── vwap_reversion.py     ← VWAP Mean Reversion (MES/ES, 5min) ✅
│   ├── cot_filter.py         ← COT Report weekly bias filter (MGC/MES) ✅
│   ├── volume_profile.py     ← POC/VAH/VAL session profile ✅
│   ├── regime.py             ← VIX-based adaptive parameter engine ✅
│   └── indicators.py         ← EMA, ADX, RSI, ATR, VWAP ✅
├── execution/
│   ├── base.py               ← BrokerBase ABC — abstract broker interface ✅
│   ├── alpaca.py             ← Alpaca Markets connector (stocks/ETFs) ✅
│   ├── router.py             ← ExecutionRouter — instrument → broker mapping ✅
│   ├── tradovate.py          ← Tradovate REST API connector (functional)
│   └── orders.py             ← legacy IBKR bracket orders (deprecated)
├── risk/manager.py           ← multi-broker position sizing, portfolio heat ✅
├── data/
│   ├── fetcher.py            ← yfinance OHLCV
│   ├── fundamentals.py       ← live VIX, yields, DXY
│   └── trade_log.py          ← SQLite logging (trades, events, equity)
├── monitor/alerts.py         ← Telegram notifications
├── backtest/
│   ├── engine.py             ← vectorized backtest engine ✅
│   ├── report.py             ← metrics + reporting ✅
│   ├── run.py                ← CLI runner ✅
│   ├── monte_carlo.py        ← Monte Carlo simulation (10,000 runs) ✅
│   ├── walk_forward.py       ← Walk-forward optimization (WFE gate) ✅
│   └── sensitivity.py        ← Parameter sensitivity sweep (±15% gate) ✅
├── web/
│   ├── api.py                ← FastAPI backend + WebSocket /ws
│   └── static/               ← index.html, style.css, app.js
│       └── strategy_lab.*    ← Strategy Lab tab (backtest + forward test UI)
├── backtest/                 ← vectorized engine + reports
├── tradingview/              ← Pine Script strategies (.pine files)
└── RESEARCH.md               ← Master research compendium (READ THIS)
```

---

## Strategy Library (11 Strategies)

| ID | Name | Type | Best Instruments | Timeframe | Status |
|---|---|---|---|---|---|
| S01 | Break & Retest (BRT) | Momentum/Structure | MES, Gold, Stocks | 15min | ✅ Live |
| S02 | Opening Range Breakout (ORB) | Momentum/Breakout | MES, Stocks | 15min–1h | 🔨 Build |
| S03 | VWAP Mean Reversion | Mean Reversion | MES, Stocks | 5–15min | 🔨 Build |
| S04 | EMA Crossover + ADX | Trend Following | Gold, Silver, Stocks | 1h–Daily | 🔨 Build |
| S05 | Supertrend | Trend/Trailing | Gold, Silver, MES | 1h–Daily | 🔨 Build |
| S06 | Bollinger Band MR | Mean Reversion | MES, Gold, Stocks | 15min–1h | 🔨 Build |
| S07 | RSI Pullback in Trend | Momentum/Pullback | Stocks, Gold, MES | 1h–Daily | 🔨 Build |
| S08 | MACD Momentum | Momentum/Trend | Stocks, Gold | 1h–Daily | 🔨 Build |
| S09 | Donchian Breakout | Trend/Breakout | Gold, Silver, Oil | Daily | ⚠️ Partial |
| S10 | Keltner Squeeze | Volatility Breakout | MES, Gold, Stocks | 1h–Daily | 🔨 Build |
| S11 | Momentum Breakout | Momentum/Volume | Stocks, MES, Gold | 15min–1h | 🔨 Build |

Full strategy details (logic, entry/exit rules, confluence, SL/TP) in `RESEARCH.md § 11`.

---

## Market–Strategy Matrix (Quick Reference)

| Market Condition | Use | Avoid |
|---|---|---|
| Strong Trend (ADX > 25) | BRT, ORB, Supertrend, Donchian, Momentum Breakout | VWAP MR, Bollinger MR |
| Weak Trend (ADX 18–25) | EMA Cross, RSI Pullback, Supertrend | Donchian, ORB |
| Ranging / Chop (ADX < 18) | VWAP MR, Bollinger MR, RSI Pullback | BRT, ORB, EMA Cross |
| Volatility Compression | Keltner Squeeze (wait for release) | All trend strategies |
| High Vol (VIX 20–30) | BRT (wider params), ORB | VWAP MR, Bollinger MR |
| Extreme (VIX 30–40) | Supertrend, Donchian (daily, min size) | All intraday |
| No Trade (VIX > 40) | Flat | Everything |

---

## Active Strategy: Break & Retest (BRT) on MES

**Instrument:** MES (Micro E-mini S&P 500, $5/pt)
**Timeframe:** 15-minute candles

### State Machine
```
NEUTRAL → (break detected) → WATCHING_LONG or WATCHING_SHORT
         → (retest confirmed) → ENTRY
         → (timeout / max bars) → back to NEUTRAL
```

### Level Priority (checked in order)
1. VWAP — intraday, resets daily
2. PDH / PDL — previous day high/low
3. ORH / ORL — opening range (9:30–10:00 ET)
4. SWING — rolling 20-bar high/low

### Break Detection (all 3 required)
- Close crosses level ± `BRT_BREAK_BUFFER × ATR`
- Volume > `BRT_VOLUME_THRESHOLD × vol_ma(20)`
- Break candle body > `BRT_BREAK_BODY_MIN × ATR`

### Retest Entry (all 6 required)
- Price in `[level ± tolerance × ATR]`
- Bullish/bearish candle direction
- Close clearly above/below broken level
- EMA20 alignment
- ADX > `adx_min` (regime-adaptive)
- RSI in range (35–75 long, 25–65 short)

### SL / TP
- SL: `min(candle_low, level) − sl_buffer × ATR` (long)
- TP: `entry + (entry − SL) × tp_rr`

---

## Market Regimes (regime.py)

| Regime    | VIX      | ADX min | SL buffer | TP   | Retest bars | Size  |
|-----------|----------|---------|-----------|------|-------------|-------|
| TRENDING  | < 15     | 25      | 0.25×ATR  | 2.5R | 14          | Full  |
| NORMAL    | 15–20    | 20      | 0.30×ATR  | 2.0R | 16          | Full  |
| CAUTIOUS  | 20–30    | 25      | 0.40×ATR  | 1.5R | 10          | Half  |
| HIGH_VOL  | 30–40    | 30      | 0.50×ATR  | 2.0R | 8           | Min   |
| NO_TRADE  | > 40     | —       | —         | —    | —           | None  |

---

## Key Config Values (config/settings.py)

```python
PAPER_TRADING        = True         # flip to False for live
SYMBOLS              = ["MES"]
BRT_TIMEFRAME        = 15           # 15-min candles
BRT_ADX_MIN          = 20
BRT_TP_RR            = 2.0
BRT_SL_BUFFER        = 0.30
BRT_MAX_RETEST_BARS  = 16
RISK_PER_TRADE       = 0.01         # 1% per trade
MAX_DAILY_DRAWDOWN   = 0.03         # 3% daily stop-out
BRT_POINT_VALUE      = 5.00         # MES $5/pt
BRT_COST_PER_RT      = 2.94         # commission + slippage
```

---

## Backtest Results (2026-03-25)

### BRT — Break & Retest (MES, out-of-sample)
- **Period:** Oct 2023 – Mar 2026 | Train: Oct 2023–Jan 2025 | OOS: Jan 2025–Mar 2026
- **In-sample:** 36% WR, Sharpe 1.98 | **Out-of-sample:** 44% WR, Sharpe 3.70 (no decay)
- **⚠️ Caveat:** yfinance 15-min data capped at 60 days — full historical run done separately

### RSI(2) Daily — SPY
- **Period:** 5y (~1,255 daily bars) | **Trades:** 39 | **WR:** 64.1% | **PF:** 1.61
- **Max drawdown:** 0.9% | **Capital:** $3,000 → $3,071 (+2.4%)
- **Monte Carlo (bootstrap, 10k sims):** 0% ruin | 91.4% profit probability | p95 DD 2.3%
- **Verdict:** ✅ PASSES all Monte Carlo gates — statistically robust (note: only 39 trades)

### VWAP MR — MES (5-min, 60 days)
- **Trades:** 72 | **WR:** 45.8% | **PF:** 1.01 | **Sharpe:** 0.10 — essentially break-even
- **Monte Carlo (bootstrap):** 51% profit probability — fails PROFIT PROB gate
- **Verdict:** ⚠️ NEEDS TUNING — regime mismatch (trending 60d window hurts MR strategy)
- **ADX sensitivity sweep (2026-03-25):** ADX_MAX < 18 = 54% WR, 1.94 PF; ADX_MAX 30 = 45.8% WR
  - Tighter ADX filter dramatically improves VWAP MR — only trade when ADX < 18 (true ranging days)
  - Current `VWAP_MR_ADX_MAX = 30` is too loose for the current trending regime
  - Do NOT tune this on 60 days of data — needs 500+ trades for calibration

---

## Broker: Tradovate

- `execution/tradovate.py` — REST + WebSocket API connector
- Sim account = paper trading (identical to live)
- Credentials stored in `.env` (see `.env.example`)

```
TRADOVATE_USERNAME=
TRADOVATE_PASSWORD=
TRADOVATE_APP_ID=
TRADOVATE_CID=
TRADOVATE_SEC=
TELEGRAM_TOKEN=
TELEGRAM_CHAT_ID=
PAPER_TRADING=true
```

---

## Dashboard

```bash
uvicorn web.api:app --port 8001 --reload
# open http://localhost:8001
```

- **Live tab** — regime banner, bot state, P&L, indicators, levels, equity chart, trade log
- **Strategies tab** — all 5 regime cards with params, active regime highlighted
- **Methods tab** — state machine diagram, break/retest/SL/TP criteria, session rules
- **Strategy Lab tab** — select strategy, instrument, timeframe → run backtest → see metrics → compare
- WebSocket `/ws` pushes full data bundle every 5s

---

## Research Summary (key findings from RESEARCH.md)

**Non-negotiable before going live:**
1. 200+ trades covering bull, bear, sideways regimes
2. Monte Carlo (10,000 runs) — ruin probability < 5%
3. Walk-forward optimization — WFE > 50%
4. Parameter sensitivity — no cliff drops at ±15%
5. Live circuit breaker at 1.5× backtest max drawdown

**Performance reality check:**
- Live Sharpe = backtest Sharpe × 0.5–0.7 (30–50% decay is normal)
- Live max drawdown = backtest max drawdown × 1.5–2.0
- Profit factor 1.3–1.7 is realistic and sustainable

**Risk rules that work:**
- 1% risk per trade (never more than 2%) ✓
- 3% daily stop-out ✓
- Add tiered reduction: −5% → reduce size 25%; −10% → reduce 50%; −15% → halt
- Half-Kelly or Quarter-Kelly only (never full Kelly)

---

## Current Status (Mar 2026)

### ✅ Completed
- [x] BRT strategy fully coded and backtested (MES, 15-min)
- [x] Regime-adaptive parameter engine (VIX-gated, 5 regimes)
- [x] Web dashboard: Live | Strategies | Methods | **Strategy Lab** (4 tabs)
- [x] Strategy Lab: run any strategy + Monte Carlo from the browser
- [x] Trade logging, equity curve, events feed (SQLite)
- [x] RESEARCH.md + INSTITUTIONAL_RESEARCH.md + MARKET_STRATEGY_MAPPING.md
- [x] STRATEGY_ENCYCLOPEDIA.md (15 strategies with backtested stats)
- [x] SMART_MONEY.md — SMC/ICT validation, market microstructure, COT/VP framework
- [x] SMC_INSTITUTIONAL_RESEARCH.md — ICT/Wyckoff/COT/kill zones deep reference
- [x] COMPETITIVE_LANDSCAPE.md — HFT reality, VSA thresholds, microstructure, retail edge
- [x] Multi-broker execution layer: BrokerBase, AlpacaBroker, ExecutionRouter
- [x] TradovateBroker class (execution/tradovate_broker.py) — proper BrokerBase impl
- [x] Risk manager upgraded: portfolio heat, multi-broker equity, point values table
- [x] Monte Carlo simulation module (bootstrap + shuffle, 10k runs, ruin gate)
- [x] Walk-forward optimization module (WFE > 50% gate)
- [x] Parameter sensitivity sweep (±15% cliff detection)
- [x] Strategy modules: BRT ✅ | ORB ✅ | Donchian ✅ | RSI(2) Daily ✅ | VWAP MR ✅
- [x] COT filter module (Gold/Silver via Disaggregated, S&P via TFF)
- [x] Volume Profile module (POC, VAH, VAL, session profiles)
- [x] settings.py: Alpaca credentials, PORTFOLIO_HEAT_MAX, MAX_TRADE_RISK, Tradovate fees
- [x] **BRT SMC enhancements (2026-03-25):**
  - Liquidity sweep detection: `liquidity_sweep` flag on every entry (wick below level, close above)
  - VSA close-position filter: retest close must be in correct half of bar range (`BRT_VSA_CLOSE_POSITION = True`)
  - VSA no-demand volume filter: retest bar volume >= `BRT_VSA_MIN_VOLUME_RATIO × vol_ma` (toggle: off by default)
  - Equal Highs/Lows (EQH/EQL) liquidity pool detection: `strategy/smc_levels.py`
  - Fair Value Gap (FVG) detection with mitigation tracking: bullish + bearish zones
  - BRT level priority extended to 11 types: VWAP→PDH/PDL→ORH/ORL→VP_POC/VAH/VAL→EQH/EQL→FVG→SWING
  - NY lunch avoidance: no entries 12:00–14:00 ET (`BRT_LUNCH_START_HOUR/END_HOUR`)
  - VPOC migration signal (`vpoc_trend()`) wired to dashboard
  - All new SMC levels persisted to SQLite bot_state, displayed on dashboard
  - Dashboard regime bar shows VPOC migration direction (↑↓→)
- [x] **Backtest runner (2026-03-25):**
  - RSI(2) and VWAP_MR added to `backtest/run.py` with `--strategy` CLI flag
  - `backtest_rsi2(symbol="SPY")` function for stock strategy
  - Both strategies wired to existing `_run_generic()` engine
  - RSI(2) on SPY: ✅ PASSES Monte Carlo (64.1% WR, 1.61 PF, 0% ruin, 91.4% profit prob)
  - VWAP MR on MES: ⚠️ needs tuning (regime mismatch — see Backtest Results above)

### 🔨 In Progress / Next Up
- [ ] Tradovate connector — wire up and run end-to-end paper trade test
- [ ] Paper trade BRT forward: target 50+ trades (gather sweep/non-sweep win rate split)
- [ ] VWAP MR needs 500+ trades for proper calibration (60d yfinance limit prevents this)
- [ ] VPS setup (DigitalOcean/Vultr, Ubuntu 22.04)
- [ ] Systemd services (scheduler + dashboard auto-start)
- [ ] Telegram notifications — needs bot token
- [ ] After 50+ paper trades: enable `BRT_REQUIRE_SWEEP = True` if sweep trades outperform

---

## Smart Money Architecture (see SMART_MONEY.md)

**4-layer entry framework:**
```
Layer 1: COT macro bias (weekly) → LONG / SHORT / NEUTRAL
Layer 2: Institutional levels (daily) → POC, VAH, VAL, PDH/PDL, FVG zones
Layer 3: SMC context (per bar) → above/below VWAP, active OBs, liquidity sweeps
Layer 4: Entry trigger → BRT signal, VWAP MR deviation, RSI(2) oversold
```

**Key validated facts:**
- FVGs are NOT fill magnets — >60% remain unfilled (use as S/R zones)
- Stop-loss cascades at obvious levels are REAL (Osler 2005, SciTech 2024)
- Session timing (London/NY opens) IS statistically validated (NBER w12413)
- OTE Fibonacci (0.62-0.79) has NO peer-reviewed backing
- COT is a weekly bias filter only; best in gold/silver, weak in equity index

---

## Two-Broker Architecture (see execution/)

| Instrument | Broker | Router Key |
|---|---|---|
| MES, ES, MGC, GC, SIL, SI, MCL, CL | Tradovate | `"tradovate"` |
| SPY, QQQ, IWM, GLD, SLV, AAPL, NVDA | Alpaca | `"alpaca"` |

```python
from execution.router import router  # singleton
router.connect_all()
router.place_bracket_order("MES", qty=1, sl_price=5000.0, tp_price=5020.0, direction=1)
router.place_bracket_order("SPY", qty=10, sl_price=498.0, tp_price=502.0, direction=1)
state = router.get_portfolio()  # unified equity + positions across all brokers
```

---

## Next Priorities

1. Wire up Tradovate connector + paper trade forward test (50+ BRT trades)
2. Backtest RSI(2) Daily on SPY + run Monte Carlo → live if passes gates
3. Backtest VWAP MR on MES + run Monte Carlo → live if passes gates
4. Add COT + Volume Profile as filters to Donchian strategy on MGC
5. VPS deployment + systemd services
6. Run multi-strategy paper trading: target 200+ trades across strategies
