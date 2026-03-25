"""
TRADEZ Web Dashboard — FastAPI backend.

Endpoints:
    GET  /                     → serve dashboard HTML
    GET  /api/state            → live bot state snapshot
    GET  /api/trades           → recent trade history
    GET  /api/equity           → equity curve data points
    GET  /api/summary          → today's daily summary
    GET  /api/regime           → current regime info + params
    GET  /api/events           → recent activity events
    POST /api/lab/run          → run backtest + Monte Carlo on any strategy
    GET  /api/lab/strategies   → list available strategies
    WS   /ws                   → WebSocket — pushes full data bundle every 5s

Run:
    uvicorn web.api:app --reload --port 8000
"""

import asyncio
import sys
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from data.trade_log import (
    init_db,
    get_bot_state,
    get_recent_trades,
    get_equity_curve,
    get_daily_summary,
    get_recent_events,
)
from strategy.regime import get_regime_info

STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(title="TRADEZ Dashboard", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

init_db()


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _full_payload() -> dict:
    import json as _json
    state   = get_bot_state()
    vix     = state.get("vix") if state else None
    summary = get_daily_summary()

    # Parse advisory JSON blob from bot_state if present
    advisory = {"available": False}
    if state:
        raw = state.get("llm_advisory")
        if raw:
            try:
                advisory = {**_json.loads(raw), "available": True}
            except Exception:
                pass

    return {
        "state":    state,
        "trades":   get_recent_trades(limit=30),
        "equity":   get_equity_curve(limit=150),
        "summary":  summary,
        "events":   get_recent_events(limit=40),
        "regime":   get_regime_info(vix),
        "settings": api_settings(),
        "advisory": advisory,
        "server_ts": datetime.now(timezone.utc).isoformat(),
    }


# ─── Pages ────────────────────────────────────────────────────────────────────

@app.get("/", include_in_schema=False)
def index():
    return FileResponse(STATIC_DIR / "index.html")


# ─── REST API ─────────────────────────────────────────────────────────────────

@app.get("/api/state")
def api_state():
    state = get_bot_state()
    if state is None:
        return JSONResponse({"error": "No state yet — run the scheduler first."}, status_code=503)
    return state


@app.get("/api/trades")
def api_trades(limit: int = 50):
    return get_recent_trades(limit=limit)


@app.get("/api/equity")
def api_equity(limit: int = 200):
    return get_equity_curve(limit=limit)


@app.get("/api/summary")
def api_summary(date: str | None = None):
    return get_daily_summary(date_str=date)


@app.get("/api/regime")
def api_regime():
    state = get_bot_state()
    vix = state.get("vix") if state else None
    return get_regime_info(vix)


@app.get("/api/events")
def api_events(limit: int = 40):
    return get_recent_events(limit=limit)


@app.get("/api/advisory")
def api_advisory():
    """Return the latest AI advisory from the background LLM engine."""
    import json as _json
    state = get_bot_state()
    if not state:
        return {"available": False}
    raw = state.get("llm_advisory")
    if not raw:
        return {"available": False}
    try:
        data = _json.loads(raw)
        data["available"] = True
        return data
    except Exception:
        return {"available": False}


@app.get("/api/all")
def api_all():
    return _full_payload()


@app.get("/api/broker/status")
def api_broker_status():
    """
    Check broker connectivity and credential presence.
    Does NOT attempt a live API call — only validates that credentials exist
    and returns connection state if the router was already initialized.
    Safe to call at any time without side effects.
    """
    from config import settings as s
    tradovate_ready = bool(
        s.TRADOVATE_USERNAME and s.TRADOVATE_PASSWORD
        and s.TRADOVATE_CID and s.TRADOVATE_SEC
    )
    alpaca_ready = bool(s.ALPACA_API_KEY and s.ALPACA_SECRET_KEY)
    telegram_ready = bool(s.TELEGRAM_TOKEN and s.TELEGRAM_CHAT_ID)

    return {
        "paper_trading": s.PAPER_TRADING,
        "tradovate": {
            "credentials_set": tradovate_ready,
            "mode":            "DEMO" if s.PAPER_TRADING else "LIVE",
            "username":        s.TRADOVATE_USERNAME or "(not set)",
        },
        "alpaca": {
            "credentials_set": alpaca_ready,
        },
        "telegram": {
            "configured": telegram_ready,
            "chat_id":    s.TELEGRAM_CHAT_ID or "(not set)",
        },
        "symbols":  s.SYMBOLS,
        "risk": {
            "per_trade_pct":     s.RISK_PER_TRADE * 100,
            "daily_stop_pct":    s.MAX_DAILY_DRAWDOWN * 100,
            "portfolio_heat_pct": s.PORTFOLIO_HEAT_MAX * 100,
        },
    }


# ─── Strategy Lab ────────────────────────────────────────────────────────────

# All strategies available in the Lab
LAB_STRATEGIES = {
    "BRT":       {"name": "Break & Retest",         "instruments": ["MES", "ES"], "timeframe": "15min"},
    "ORB":       {"name": "Opening Range Breakout",  "instruments": ["MES", "ES", "SPY", "QQQ"], "timeframe": "1h"},
    "DONCHIAN":  {"name": "Donchian Breakout",       "instruments": ["MGC", "GC", "SIL", "SI", "MCL"], "timeframe": "1d"},
    "RSI2":      {"name": "RSI(2) Daily",            "instruments": ["SPY", "QQQ", "IWM", "GLD"], "timeframe": "1d"},
    "VWAP_MR":   {"name": "VWAP Mean Reversion",    "instruments": ["MES", "ES"], "timeframe": "5min"},
}

# yfinance ticker map for each instrument
_YF_MAP = {
    "MES": "ES=F", "ES": "ES=F", "MNQ": "NQ=F", "NQ": "NQ=F",
    "MGC": "GC=F", "GC": "GC=F", "SIL": "SI=F", "SI": "SI=F",
    "MCL": "CL=F", "CL": "CL=F",
    "SPY": "SPY", "QQQ": "QQQ", "IWM": "IWM",
    "GLD": "GLD", "SLV": "SLV", "TLT": "TLT",
}

# Timeframe → yfinance interval string
_TF_MAP = {
    "5min": "5m", "15min": "15m", "1h": "1h", "1d": "1d",
}

# How many days of history to fetch per timeframe
_HISTORY_DAYS = {
    "5min": 59, "15min": 60, "1h": 365, "1d": 730,
}


class LabRunRequest(BaseModel):
    strategy:        str
    symbol:          str
    initial_capital: float = 10_000.0
    run_monte_carlo: bool  = True
    n_mc_sims:       int   = 2000      # default lower for web responsiveness


@app.get("/api/lab/strategies")
def api_lab_strategies():
    """List all available strategies and their supported instruments."""
    return LAB_STRATEGIES


@app.post("/api/lab/run")
def api_lab_run(req: LabRunRequest):
    """
    Run a full backtest + optional Monte Carlo on the requested strategy/instrument.
    Downloads fresh data from yfinance.

    Returns JSON with:
        metrics     — standard backtest metrics (win rate, Sharpe, etc.)
        trades      — list of individual trades
        equity      — equity curve data points
        monte_carlo — Monte Carlo results (if run_monte_carlo=True)
        n_trades    — total trade count
        warning     — string warning if trade count is insufficient
    """
    import yfinance as yf

    strategy = req.strategy.upper()
    symbol   = req.symbol.upper()

    if strategy not in LAB_STRATEGIES:
        return JSONResponse(
            {"error": f"Unknown strategy '{strategy}'. Available: {list(LAB_STRATEGIES.keys())}"},
            status_code=400,
        )

    strat_meta = LAB_STRATEGIES[strategy]
    tf         = strat_meta["timeframe"]
    yf_ticker  = _YF_MAP.get(symbol, symbol)
    interval   = _TF_MAP[tf]
    days       = _HISTORY_DAYS[tf]

    # ── Download price data ────────────────────────────────────────────────────
    try:
        ticker = yf.Ticker(yf_ticker)
        df = ticker.history(period=f"{days}d", interval=interval, auto_adjust=True)
        if df.empty:
            return JSONResponse({"error": f"No data returned for {yf_ticker}"}, status_code=422)
        df.columns = [c.lower() for c in df.columns]
        df = df[["open", "high", "low", "close", "volume"]].dropna()
    except Exception as e:
        return JSONResponse({"error": f"Data download failed: {e}"}, status_code=500)

    # ── Run strategy signal generation ────────────────────────────────────────
    try:
        if strategy == "BRT":
            from strategy.break_retest import prepare_break_retest
            df = prepare_break_retest(df)
        elif strategy == "ORB":
            from strategy.orb import prepare_orb
            df = prepare_orb(df)
        elif strategy == "DONCHIAN":
            from strategy.donchian import prepare_donchian
            df = prepare_donchian(df)
        elif strategy == "RSI2":
            from strategy.rsi2_daily import prepare_rsi2
            df = prepare_rsi2(df)
        elif strategy == "VWAP_MR":
            from strategy.vwap_reversion import prepare_vwap_reversion
            df = prepare_vwap_reversion(df)
    except Exception as e:
        return JSONResponse({"error": f"Signal generation failed: {e}"}, status_code=500)

    # ── Run backtest ───────────────────────────────────────────────────────────
    try:
        from backtest.engine import run_backtest
        from backtest.report import generate_report

        # Map Lab strategies to backtest engine strategy names
        bt_strategy_map = {
            "BRT": "BRT", "ORB": "ORB", "DONCHIAN": "DONCHIAN",
            "RSI2": "RSI2", "VWAP_MR": "VWAP_MR",
        }
        bt_strategy = bt_strategy_map.get(strategy, "GENERIC")
        result = run_backtest(df, bt_strategy, initial_capital=req.initial_capital)
        metrics = generate_report(result, symbol)
    except Exception as e:
        return JSONResponse({"error": f"Backtest failed: {e}"}, status_code=500)

    n_trades = metrics.get("total_trades", 0)
    warning  = None
    if n_trades < 30:
        warning = (
            f"Only {n_trades} trades — results are statistically unreliable. "
            f"Minimum 100 trades required for confidence. Extend the date range."
        )
    elif n_trades < 100:
        warning = (
            f"{n_trades} trades — use with caution. "
            f"100+ trades needed for reliable Monte Carlo and Sharpe estimates."
        )

    # ── Equity curve as list of {x, y} points ─────────────────────────────────
    equity_points = [
        {"i": i, "equity": float(v)}
        for i, v in enumerate(result.get("equity_curve", []))
    ]

    # ── Trades as list of dicts ────────────────────────────────────────────────
    trades_list = []
    if not result["trades"].empty:
        for _, row in result["trades"].iterrows():
            trades_list.append({
                "entry_time":  str(row.get("entry_time", "")),
                "exit_time":   str(row.get("exit_time",  "")),
                "direction":   str(row.get("direction",  "")),
                "entry":       float(row.get("entry_price", 0)),
                "exit":        float(row.get("exit_price",  0)),
                "pnl":         float(row.get("pnl",         0)),
                "result":      str(row.get("result",        "")),
                "contracts":   int(row.get("contracts",     1)),
            })

    # ── Monte Carlo ───────────────────────────────────────────────────────────
    mc_output = None
    if req.run_monte_carlo and n_trades >= 10:
        try:
            from backtest.monte_carlo import from_backtest_result
            mc_results = from_backtest_result(
                result,
                n_simulations=req.n_mc_sims,
                method="bootstrap",
            )
            mc = mc_results["bootstrap"]
            mc_output = {
                "ruin_probability":    round(mc.ruin_probability,    4),
                "prob_profit":         round(mc.prob_profit,         4),
                "median_final_equity": round(mc.median_final_equity, 2),
                "p05_final_equity":    round(mc.p05_final_equity,    2),
                "p95_final_equity":    round(mc.p95_final_equity,    2),
                "median_max_dd":       round(mc.median_max_dd,       4),
                "p95_max_dd":          round(mc.p95_max_dd,          4),
                "passes_all_gates":    mc.passes_all_gates,
                "n_simulations":       mc.n_simulations,
            }
        except Exception as e:
            mc_output = {"error": str(e)}

    return {
        "strategy":    strategy,
        "symbol":      symbol,
        "metrics":     metrics,
        "trades":      trades_list,
        "equity":      equity_points,
        "monte_carlo": mc_output,
        "n_trades":    n_trades,
        "warning":     warning,
        "timeframe":   tf,
        "data_bars":   len(df),
    }


@app.get("/api/settings")
def api_settings():
    """Return current active BRT settings for dashboard display."""
    from config import settings as s
    return {
        "paper_trading":        s.PAPER_TRADING,
        "risk_per_trade":       s.RISK_PER_TRADE,
        "max_daily_drawdown":   s.MAX_DAILY_DRAWDOWN,
        "portfolio_heat_max":   s.PORTFOLIO_HEAT_MAX,
        "brt_adx_min":          s.BRT_ADX_MIN,
        "brt_tp_rr":            s.BRT_TP_RR,
        "brt_sl_buffer":        s.BRT_SL_BUFFER,
        "brt_max_retest_bars":  s.BRT_MAX_RETEST_BARS,
        "brt_level_tolerance":  s.BRT_LEVEL_TOLERANCE,
        "brt_break_buffer":     s.BRT_BREAK_BUFFER,
        "brt_volume_threshold": s.BRT_VOLUME_THRESHOLD,
        "brt_rsi_long_min":     s.BRT_RSI_LONG_MIN,
        "brt_rsi_long_max":     s.BRT_RSI_LONG_MAX,
        "brt_session_start":    s.BRT_SESSION_START_HOUR,
        "brt_session_end":      s.BRT_SESSION_END_HOUR,
        "brt_lunch_start":      getattr(s, "BRT_LUNCH_START_HOUR", 12),
        "brt_lunch_end":        getattr(s, "BRT_LUNCH_END_HOUR", 14),
        "brt_vsa_close":        getattr(s, "BRT_VSA_CLOSE_POSITION", True),
        "brt_require_sweep":    getattr(s, "BRT_REQUIRE_SWEEP", False),
        "brt_point_value":      s.BRT_POINT_VALUE,
        "brt_cost_per_rt":      s.BRT_COST_PER_RT,
        "brt_swing_window":     s.BRT_SWING_WINDOW,
        "brt_ema_period":       s.BRT_EMA_PERIOD,
        "brt_atr_period":       s.BRT_ATR_PERIOD,
        "symbols":              s.SYMBOLS,
    }


# ─── WebSocket ────────────────────────────────────────────────────────────────

@app.websocket("/ws")
async def ws_endpoint(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            payload = _full_payload()
            await websocket.send_json(payload)
            await asyncio.sleep(5)
    except (WebSocketDisconnect, Exception):
        pass
