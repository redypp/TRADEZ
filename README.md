# TRADEZ

Crypto futures trend-following trading bot built in Python.

## Strategy
- EMA 20/50 crossover with ADX trend strength filter
- ATR-based stop loss and take profit
- 1-2% account risk per trade

## Stack
- `ccxt` — exchange connectivity
- `pandas-ta` — technical indicators
- `APScheduler` — candle-based scheduling
- `python-telegram-bot` — alerts

## Structure
```
TRADEZ/
├── config/         # API keys, strategy params
├── data/           # Historical + live OHLCV data
├── strategy/       # Indicators and signal logic
├── execution/      # Order management
├── risk/           # Position sizing, drawdown limits
├── monitor/        # Logging and Telegram alerts
└── backtest/       # Backtesting scripts
```

## Setup
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # fill in your API keys
```

## Status
- [ ] Phase 1: Foundation
- [ ] Phase 2: Strategy + Backtesting
- [ ] Phase 3: Execution + Risk
- [ ] Phase 4: Live deployment
