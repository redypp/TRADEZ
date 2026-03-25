# TRADEZ — Project Context

> Paste this file at the start of any new Claude chat to restore full context instantly.
> Last updated: 2026-03-24

---

## What This Is

An automated CME micro-futures trading bot focused on **MES (Micro E-mini S&P 500)**.

- **Strategy:** Break & Retest (BRT) on 15-minute bars
- **Broker:** Tradovate (futures, commission-based, sim account available)
- **Scheduler:** APScheduler — runs every hour at :02, Mon–Fri, 10:00–15:00 ET
- **Dashboard:** FastAPI + vanilla JS — 3 tabs: Live | Strategies | Methods
- **Notifications:** Telegram (trade alerts, risk blocks, daily summary)
- **Data:** yfinance for OHLCV + fundamentals (VIX, 10Y yield, DXY)
- **DB:** SQLite via trade_log.py (trades, equity curve, events feed)

---

## Repo Structure

```
TRADEZ/
├── scheduler.py          ← production bot entry point
├── config/settings.py    ← all strategy + broker params
├── strategy/
│   ├── break_retest.py   ← primary BRT signal engine (MES, 15-min)
│   ├── regime.py         ← VIX-based adaptive parameter engine
│   ├── donchian.py       ← Donchian breakout (MGC, MNQ)
│   └── indicators.py     ← EMA, ADX, RSI, ATR, VWAP
├── execution/
│   ├── tradovate.py      ← Tradovate API connector
│   └── orders.py         ← bracket order construction
├── risk/manager.py       ← position sizing, drawdown checks
├── data/
│   ├── fetcher.py        ← yfinance OHLCV
│   ├── fundamentals.py   ← live VIX, yields, DXY
│   └── trade_log.py      ← SQLite logging (trades, events, equity)
├── monitor/alerts.py     ← Telegram notifications
├── web/
│   ├── api.py            ← FastAPI backend + WebSocket /ws
│   └── static/           ← index.html, style.css, app.js
├── backtest/             ← vectorized engine + reports
└── tradingview/          ← Pine Script strategies (.pine files)
```

---

## Strategy: Break & Retest (BRT)

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
- EMA20 alignment (close > EMA20 for long)
- ADX > `adx_min` (regime-adaptive)
- RSI in range (35–75 long, 25–65 short)

### SL / TP
- SL: `min(candle_low, level) − sl_buffer × ATR` (long)
- TP: `entry + (entry − SL) × tp_rr`

---

## Market Regimes (regime.py)

Regime adapts ALL BRT parameters live based on VIX:

| Regime    | VIX      | ADX min | SL buffer | TP   | Retest bars | Size  |
|-----------|----------|---------|-----------|------|-------------|-------|
| TRENDING  | < 15     | 20      | 0.25×ATR  | 2.5R | 16          | Full  |
| NORMAL    | 15–20    | 20      | 0.30×ATR  | 2.0R | 14          | Full  |
| CAUTIOUS  | 20–30    | 22      | 0.40×ATR  | 2.0R | 10          | Half  |
| HIGH_VOL  | 30–40    | 25      | 0.50×ATR  | 1.5R | 8           | Min   |
| NO_TRADE  | > 40     | —       | —         | —    | —           | None  |

---

## Key Config Values (config/settings.py)

```python
PAPER_TRADING        = True         # flip to False for live
SYMBOLS              = ["MES"]      # MES = BRT, MGC/MNQ = Donchian
BRT_TIMEFRAME        = 15           # 15-min candles
BRT_ADX_MIN          = 20
BRT_TP_RR            = 2.0
BRT_SL_BUFFER        = 0.30
BRT_MAX_RETEST_BARS  = 14
RISK_PER_TRADE       = 0.01         # 1% per trade
MAX_DAILY_DRAWDOWN   = 0.03         # 3% daily stop-out
BRT_POINT_VALUE      = 5.00         # MES $5/pt
BRT_COST_PER_RT      = 2.94         # commission + slippage
```

---

## Backtest Results (out-of-sample)

- **Period:** Sep 2025 – Mar 2026
- **P&L:** +$738.12 (+36.91%) on ~$2k capital
- **Total trades:** 21 | **Win rate:** 47.6% | **Profit factor:** 1.63
- **Max drawdown:** 26.2%
- **Out-of-sample Sharpe:** 3.70 (exceeds in-sample 1.98 — no decay)

---

## Broker: Tradovate

- Replacing original IBKR integration
- `execution/tradovate.py` — REST + WebSocket API connector
- Sim account = paper trading (identical to live)
- Credentials stored in `.env` (see `.env.example`)

Required `.env` vars:
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
- WebSocket `/ws` pushes full data bundle every 5s
- REST fallback at `/api/all`

---

## Current Status (Mar 2026)

- [x] BRT strategy fully coded and backtested
- [x] Regime-adaptive parameter engine live
- [x] Web dashboard (3-tab, WebSocket live updates)
- [x] Trade logging, equity curve, events feed
- [ ] Tradovate connector — needs wiring up and testing
- [ ] VPS setup (DigitalOcean/Vultr, Ubuntu 22.04)
- [ ] Systemd services (scheduler + dashboard auto-start)
- [ ] Telegram notifications — needs bot token
- [ ] Paper trade forward test (target: 50+ trades before live)

**Current branch:** `feature/brt-mes-live-risk`

---

## Next Priorities

1. Wire up Tradovate API connector (auth, market data, order placement)
2. Test end-to-end in sim account
3. VPS deployment + systemd services
4. Run paper trading for 4–6 weeks, track metrics vs backtest
5. Go live when paper metrics hold within 20% of backtest
