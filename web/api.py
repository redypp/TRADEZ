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
import hashlib
import logging
import sys
import threading
import time
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

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(title="TRADEZ Dashboard", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

init_db()


# ══════════════════════════════════════════════════════════════════════════════
# SCREENER BACKGROUND WORKERS
# Runs independently of the main scheduler — the screener works even when
# the trading bot is not running.
# ══════════════════════════════════════════════════════════════════════════════

# ── LLM Specialist cache ──────────────────────────────────────────────────────
_llm_spec_cache:   dict  = {}   # last advisory result from Grok+GPT4+Claude
_llm_spec_ts:      float = 0.0  # unix time of last successful run
_llm_spec_running: bool  = False
_llm_spec_queued:  bool  = False  # True = run immediately on next cycle
_LLM_SPEC_INTERVAL = 20 * 60     # auto-refresh every 20 minutes


def _run_screener_llm_worker():
    """
    Daemon thread: fires the three-specialist LLM advisory pipeline (Grok →
    GPT-4 → Claude) every 20 minutes — or immediately when _llm_spec_queued
    is set.  Stores the result in _llm_spec_cache so the screener endpoint
    can return it without blocking.
    """
    global _llm_spec_cache, _llm_spec_ts, _llm_spec_running, _llm_spec_queued

    while True:
        now = time.time()
        due = (now - _llm_spec_ts) >= _LLM_SPEC_INTERVAL
        if not (due or _llm_spec_queued):
            time.sleep(15)
            continue

        _llm_spec_queued  = False
        _llm_spec_running = True
        try:
            from data.fundamentals import get_live_fundamentals
            from strategy.llm_advisory import _async_get_advisory

            fundamentals = get_live_fundamentals()
            mkt          = _fetch_mes_snapshot()
            market_data  = {
                **mkt,
                "vix":          fundamentals.get("vix"),
                "yield_10y":    fundamentals.get("yield_10y"),
                "dxy":          fundamentals.get("dxy"),
                "regime":       fundamentals.get("regime", "NORMAL"),
                "spy_vol_ratio":fundamentals.get("spy_vol_ratio"),
                "headwinds":    fundamentals.get("headwinds", []),
                "tailwinds":    fundamentals.get("tailwinds", []),
            }

            loop = asyncio.new_event_loop()
            try:
                result = loop.run_until_complete(
                    _async_get_advisory(market_data, "BRT", "NEUTRAL", "SCREENER")
                )
            finally:
                loop.close()

            if result:
                _llm_spec_cache = result
                _llm_spec_ts    = time.time()
                logger.info(
                    f"[ScreenerLLM] Done — sentiment={result.get('sentiment')} "
                    f"quality={result.get('signal_quality')}"
                )
                # Bridge to scheduler process: write to bot_state so orchestrator
                # can use it as an advisory quality gate fallback (cross-process).
                try:
                    import json as _json
                    from data.trade_log import update_bot_state
                    update_bot_state({"screener_advisory": _json.dumps(result)})
                except Exception as _e:
                    logger.debug(f"[ScreenerLLM] bot_state bridge skipped: {_e}")

                # Standalone LLM watch alert: high-confidence trade idea with no
                # mechanical signal → fire a Telegram alert so the trader knows.
                try:
                    idea     = result.get("trade_idea") or {}
                    idea_dir = idea.get("direction", "FLAT")
                    idea_conf = float(idea.get("confidence") or 0.0)
                    if idea_dir in ("LONG", "SHORT") and idea_conf >= 0.70:
                        from data.trade_log import log_event
                        from monitor.alerts import send_telegram
                        thesis = idea.get("thesis", "")
                        entry_low  = idea.get("entry_low")
                        entry_high = idea.get("entry_high")
                        stop       = idea.get("stop")
                        target     = idea.get("target")
                        entry_str  = (f"{entry_low}–{entry_high}" if entry_low and entry_high
                                      else str(entry_low or entry_high or "—"))
                        msg = (
                            f"🤖 LLM Watch — {idea_dir} MES\n"
                            f"Entry: {entry_str} | Stop: {stop or '—'} | Target: {target or '—'}\n"
                            f"Conf: {idea_conf:.0%} | {thesis}"
                        )
                        log_event(f"LLM Watch: {idea_dir} MES (conf={idea_conf:.0%})", "INFO", thesis)
                        send_telegram(msg)
                except Exception as _te:
                    logger.debug(f"[ScreenerLLM] watch alert skipped: {_te}")

        except Exception as e:
            logger.error(f"[ScreenerLLM] Worker failed: {e}")
        finally:
            _llm_spec_running = False

        time.sleep(30)  # check again in 30s


# ── News scraper cache ────────────────────────────────────────────────────────
_news_items:    list  = []   # list of {source, headline, impact, direction, ts, link}
_news_lock             = threading.Lock()
_news_seen_hashes: set = set()
_news_grok_ts:  float  = 0.0
_NEWS_RSS_INTERVAL  = 60    # seconds between RSS polls
_NEWS_GROK_INTERVAL = 180   # seconds between Grok breaking-news checks
_NEWS_MAX_ITEMS     = 50

RSS_FEEDS = [
    ("Reuters",    "https://feeds.reuters.com/reuters/businessNews"),
    ("CNBC",       "https://www.cnbc.com/id/100003114/device/rss/rss.html"),
    ("MarketWatch","https://feeds.marketwatch.com/marketwatch/topstories/"),
    ("Investing",  "https://www.investing.com/rss/news.rss"),
    ("Yahoo Fin",  "https://finance.yahoo.com/news/rssindex"),
]

_HIGH_KW = [
    "fomc","federal reserve","rate cut","rate hike","cpi","pce","nfp","jobs report",
    "gdp","inflation","war","attack","sanctions","default","circuit breaker",
    "trading halt","bankruptcy","collapse","tariff","executive order","flash crash",
]
_MED_KW = [
    "earnings","fed speaker","powell","jobless","pmi","ism","layoffs","oil","opec",
    "recession","ipo","profit warning","guidance","consumer confidence","gdp",
]

def _impact_score(text: str) -> str:
    t = text.lower()
    for kw in _HIGH_KW:
        if kw in t: return "HIGH"
    for kw in _MED_KW:
        if kw in t: return "MEDIUM"
    return "LOW"

def _hsh(s: str) -> str:
    return hashlib.md5(s.lower().strip().encode()).hexdigest()[:10]


def _fetch_rss_batch() -> list[dict]:
    try:
        import feedparser
    except ImportError:
        return []
    items = []
    for source, url in RSS_FEEDS:
        try:
            feed = feedparser.parse(url)
            for e in feed.entries[:6]:
                hl = (e.get("title") or "").strip()
                if not hl:
                    continue
                h = _hsh(hl)
                if h in _news_seen_hashes:
                    continue
                _news_seen_hashes.add(h)
                impact = _impact_score(hl + " " + (e.get("summary") or ""))
                items.append({
                    "source":  source,
                    "headline": hl,
                    "link":    e.get("link", ""),
                    "impact":  impact,
                    "direction": None,
                    "ts":      datetime.now(timezone.utc).isoformat(),
                })
        except Exception:
            pass
    return items


def _grok_breaking_news() -> Optional[dict]:
    """Ask Grok: anything break in the last 5 min that moves ES?"""
    try:
        from config import settings
        import openai, json as _j, re as _re
        api_key = getattr(settings, "XAI_API_KEY", "") or ""
        if not api_key:
            return None
        prompt = (
            "You are a real-time market scanner for a futures trader.\n"
            "Scan X/Twitter and news RIGHT NOW for anything that broke in the LAST 5 MINUTES "
            "that could immediately move ES/SPX futures.\n"
            "High priority: FOMC surprise, major M&A, geopolitical shock, flash crash, CPI/NFP miss, "
            "large earnings miss, regulatory ruling.\n"
            "If NOTHING notable in last 5 min respond exactly: "
            '{"impact":"NONE","headline":"","summary":"","direction":"NEUTRAL"}\n'
            "If something broke respond: "
            '{"impact":"HIGH or MEDIUM","headline":"under 70 chars","summary":"2 sentences","direction":"BULLISH or BEARISH or NEUTRAL"}'
        )
        client = openai.OpenAI(api_key=api_key, base_url="https://api.x.ai/v1")
        resp = client.chat.completions.create(
            model="grok-3-mini", temperature=0.1, max_tokens=200,
            messages=[{"role": "user", "content": prompt}],
            timeout=12,
        )
        text = resp.choices[0].message.content or ""
        text = _re.sub(r"```(?:json)?", "", text).strip()
        m = _re.search(r"\{.*\}", text, _re.DOTALL)
        if m:
            d = _j.loads(m.group())
            if d.get("impact") in ("HIGH", "MEDIUM") and d.get("headline"):
                return {
                    "source":   "Grok · X/Twitter",
                    "headline": d["headline"],
                    "link":     "",
                    "impact":   d["impact"],
                    "direction": d.get("direction", "NEUTRAL"),
                    "summary":  d.get("summary", ""),
                    "ts":       datetime.now(timezone.utc).isoformat(),
                }
    except Exception as e:
        logger.debug(f"[ScreenerNews] Grok check failed: {e}")
    return None


def _run_news_scraper_worker():
    """Daemon thread: polls RSS every 60s + Grok every 3 min for breaking news."""
    global _news_grok_ts
    last_rss = 0.0

    while True:
        now = time.time()

        # RSS poll
        if now - last_rss >= _NEWS_RSS_INTERVAL:
            try:
                new_items = _fetch_rss_batch()
                if new_items:
                    with _news_lock:
                        _news_items[:0] = new_items
                        del _news_items[_NEWS_MAX_ITEMS:]
                    logger.debug(f"[ScreenerNews] +{len(new_items)} RSS items")
            except Exception as e:
                logger.debug(f"[ScreenerNews] RSS error: {e}")
            last_rss = now

        # Grok breaking news
        if now - _news_grok_ts >= _NEWS_GROK_INTERVAL:
            try:
                item = _grok_breaking_news()
                if item:
                    with _news_lock:
                        _news_items.insert(0, item)
                        del _news_items[_NEWS_MAX_ITEMS:]
                    logger.info(f"[ScreenerNews] Grok: {item['impact']} — {item['headline'][:60]}")
            except Exception as e:
                logger.debug(f"[ScreenerNews] Grok worker error: {e}")
            _news_grok_ts = now

        time.sleep(10)


# ── Start background workers when API boots ───────────────────────────────────
threading.Thread(target=_run_screener_llm_worker,  daemon=True, name="screener-llm").start()
threading.Thread(target=_run_news_scraper_worker,  daemon=True, name="screener-news").start()
logger.info("[Screener] Background workers started (LLM + News)")


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
    "BRT":       {"name": "Break & Retest",         "instruments": ["MES", "ES"],                   "timeframes": ["5min", "15min", "1h"], "default_tf": "15min"},
    "ORB":       {"name": "Opening Range Breakout",  "instruments": ["MES", "ES", "SPY", "QQQ"],    "timeframes": ["5min", "15min", "1h"], "default_tf": "1h"},
    "DONCHIAN":  {"name": "Donchian Breakout",       "instruments": ["MGC", "GC", "SIL", "SI", "MCL"], "timeframes": ["1d"],             "default_tf": "1d"},
    "RSI2":      {"name": "RSI(2) Daily",            "instruments": ["SPY", "QQQ", "IWM", "GLD"],   "timeframes": ["1d"],                 "default_tf": "1d"},
    "VWAP_MR":   {"name": "VWAP Mean Reversion",    "instruments": ["MES", "ES"],                   "timeframes": ["5min", "15min"],       "default_tf": "5min"},
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
    timeframe:       str   = ""        # optional override; falls back to strategy default


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

    strat_meta   = LAB_STRATEGIES[strategy]
    valid_tfs    = strat_meta["timeframes"]
    requested_tf = req.timeframe.strip() if req.timeframe else ""
    if requested_tf and requested_tf in valid_tfs:
        tf = requested_tf
    elif requested_tf and requested_tf not in valid_tfs:
        return JSONResponse(
            {"error": f"Timeframe '{requested_tf}' not supported for {strategy}. Valid options: {valid_tfs}"},
            status_code=400,
        )
    else:
        tf = strat_meta["default_tf"]
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


# ── Screener live-data helpers ────────────────────────────────────────────────

_screener_cache:    dict  = {}
_screener_cache_ts: float = 0.0
_SCREENER_TTL = 45  # seconds between yfinance re-fetches


def _is_session_open() -> bool:
    from datetime import datetime
    import pytz
    et = datetime.now(pytz.timezone("America/New_York"))
    return et.weekday() < 5 and 9 <= et.hour < 16


def _fetch_mes_snapshot() -> dict:
    """Fetch 15-min ES=F data and compute key indicators. Returns {} on failure."""
    try:
        import yfinance as yf
        import pandas as pd
        import ta

        ticker = yf.Ticker("ES=F")
        df = ticker.history(period="5d", interval="15m", auto_adjust=True)
        if df.empty or len(df) < 30:
            return {}
        df.columns = [c.lower() for c in df.columns]
        df = df[["open", "high", "low", "close", "volume"]].dropna()

        # Indicators
        df["ema20"]  = ta.trend.EMAIndicator(df["close"], window=20).ema_indicator()
        df["rsi"]    = ta.momentum.RSIIndicator(df["close"], window=14).rsi()
        adx_ind      = ta.trend.ADXIndicator(df["high"], df["low"], df["close"], window=14)
        df["adx"]    = adx_ind.adx()
        df["adx_pos"] = adx_ind.adx_pos()
        df["adx_neg"] = adx_ind.adx_neg()
        atr_ind      = ta.volatility.AverageTrueRange(df["high"], df["low"], df["close"], window=14)
        df["atr"]    = atr_ind.average_true_range()

        # Intraday VWAP (today's bars only)
        import pytz
        et   = pytz.timezone("America/New_York")
        today = df.index.tz_convert(et).normalize().max()
        today_mask = df.index.tz_convert(et).normalize() == today
        today_df   = df[today_mask]
        if not today_df.empty:
            tp   = (today_df["high"] + today_df["low"] + today_df["close"]) / 3
            vwap = (tp * today_df["volume"]).cumsum() / today_df["volume"].cumsum()
            df.loc[today_df.index, "vwap"] = vwap
        else:
            df["vwap"] = None

        # PDH / PDL
        prev_mask = df.index.tz_convert(et).normalize() == (today - pd.Timedelta(days=1))
        prev_df   = df[prev_mask] if prev_mask.any() else pd.DataFrame()
        pdh = float(prev_df["high"].max())  if not prev_df.empty else None
        pdl = float(prev_df["low"].min())   if not prev_df.empty else None

        last = df.iloc[-1]
        return {
            "close":    round(float(last["close"]),  2),
            "ema20":    round(float(last["ema20"]),  2) if not pd.isna(last["ema20"])  else None,
            "vwap":     round(float(last["vwap"]),   2) if "vwap" in df.columns and not pd.isna(last["vwap"]) else None,
            "rsi":      round(float(last["rsi"]),    1) if not pd.isna(last["rsi"])    else None,
            "adx":      round(float(last["adx"]),    1) if not pd.isna(last["adx"])    else None,
            "adx_pos":  round(float(last["adx_pos"]),1) if not pd.isna(last["adx_pos"]) else None,
            "adx_neg":  round(float(last["adx_neg"]),1) if not pd.isna(last["adx_neg"]) else None,
            "atr":      round(float(last["atr"]),    2) if not pd.isna(last["atr"])    else None,
            "pdh":      round(pdh, 2) if pdh else None,
            "pdl":      round(pdl, 2) if pdl else None,
            "bars":     len(df),
        }
    except Exception as e:
        return {"error": str(e)}


def _mechanical_bias(mkt: dict, fundamentals: dict) -> tuple[str, float, str]:
    """
    Derive bias purely from technical indicators.
    Returns (direction, confidence, reason).
    """
    if not mkt or "close" not in mkt:
        return "NEUTRAL", 0.50, "Insufficient market data"

    close = mkt.get("close", 0)
    ema20 = mkt.get("ema20")
    vwap  = mkt.get("vwap")
    rsi   = mkt.get("rsi")
    adx   = mkt.get("adx")
    adx_p = mkt.get("adx_pos")
    adx_n = mkt.get("adx_neg")
    regime = fundamentals.get("regime", "RISK_ON")

    if regime == "NO_TRADE":
        return "NEUTRAL", 0.30, "VIX extreme — no-trade regime active"

    bull_pts = 0
    bear_pts = 0
    reasons  = []

    if ema20:
        if close > ema20:
            bull_pts += 1; reasons.append(f"price above EMA20 ({ema20:.0f})")
        else:
            bear_pts += 1; reasons.append(f"price below EMA20 ({ema20:.0f})")

    if vwap:
        if close > vwap:
            bull_pts += 1; reasons.append(f"above VWAP ({vwap:.0f})")
        else:
            bear_pts += 1; reasons.append(f"below VWAP ({vwap:.0f})")

    if rsi is not None:
        if rsi > 55:
            bull_pts += 1; reasons.append(f"RSI bullish ({rsi:.0f})")
        elif rsi < 45:
            bear_pts += 1; reasons.append(f"RSI bearish ({rsi:.0f})")

    if adx_p and adx_n:
        if adx_p > adx_n:
            bull_pts += 1; reasons.append("DI+ > DI−")
        else:
            bear_pts += 1; reasons.append("DI− > DI+")

    # Macro modifier
    yield_trend = fundamentals.get("yield_trend", "STABLE")
    dxy_trend   = fundamentals.get("dxy_trend",   "STABLE")
    if yield_trend == "FALLING" or dxy_trend == "WEAKENING":
        bull_pts += 1; reasons.append("macro tailwind")
    elif yield_trend == "RISING" or dxy_trend == "STRENGTHENING":
        bear_pts += 1; reasons.append("macro headwind")

    total = bull_pts + bear_pts
    if total == 0:
        return "NEUTRAL", 0.50, "No clear signal"

    if bull_pts > bear_pts:
        conf = 0.45 + 0.10 * (bull_pts - bear_pts)
        return "BULLISH", min(round(conf, 2), 0.85), f"Technical confluence: {', '.join(reasons[:3])}"
    elif bear_pts > bull_pts:
        conf = 0.45 + 0.10 * (bear_pts - bull_pts)
        return "BEARISH", min(round(conf, 2), 0.85), f"Technical confluence: {', '.join(reasons[:3])}"
    else:
        return "NEUTRAL", 0.50, f"Mixed signals: {', '.join(reasons[:3])}"


@app.get("/api/screener")
def api_screener():
    """
    AI Screener — always fetches live market data directly.
    Works whether or not the scheduler is running.
    Cached for 45s to avoid hammering yfinance.
    """
    import time
    import json as _json

    global _screener_cache, _screener_cache_ts
    now = time.time()

    # Return cached result if fresh
    if _screener_cache and (now - _screener_cache_ts) < _SCREENER_TTL:
        return _screener_cache

    # ── 1. Live fundamentals (VIX, 10Y, DXY, SPY vol) ────────────────────────
    try:
        from data.fundamentals import get_live_fundamentals
        fundamentals = get_live_fundamentals()
    except Exception as e:
        fundamentals = {"vix": None, "regime": "UNKNOWN", "yield_10y": None,
                        "dxy": None, "headwinds": [], "tailwinds": [], "error": str(e)}

    # ── 2. Live MES 15-min price + indicators ────────────────────────────────
    mkt = _fetch_mes_snapshot()

    # ── 3. Advisory from bot_state (optional — scheduler may not be running) ──
    state    = get_bot_state()
    advisory: dict = {}
    if state:
        raw = state.get("llm_advisory")
        if raw:
            try:
                advisory = _json.loads(raw)
            except Exception:
                pass

    # ── 4. LLM selector cache ────────────────────────────────────────────────
    selector:    dict = {}
    gate_status: dict = {}
    try:
        from monitor.llm_gate import get_llm_selection, get_status
        selector    = get_llm_selection()
        gate_status = get_status()
    except Exception:
        pass

    # ── 5. Overall bias — LLM if available, else mechanical ──────────────────
    mech_dir, mech_conf, mech_reason = _mechanical_bias(mkt, fundamentals)

    adv_quality = advisory.get("signal_quality", "")
    if advisory.get("sentiment") and adv_quality in ("HIGH", "MEDIUM"):
        bias_dir  = advisory["sentiment"].upper()
        bias_conf = {"HIGH": 0.82, "MEDIUM": 0.64}.get(adv_quality, 0.60)
        bias_src  = "LLM ADVISORY"
        bias_hl   = advisory.get("headline", mech_reason)
        bias_brief = advisory.get("brief", "")
    elif selector.get("bias") and (selector.get("confidence") or 0) >= 0.60:
        bias_dir  = selector["bias"].upper()
        bias_conf = selector["confidence"]
        bias_src  = "LLM SELECTOR"
        r = selector.get("reasoning", "")
        bias_hl   = r[:100] if r else mech_reason
        bias_brief = ""
    else:
        bias_dir  = mech_dir
        bias_conf = mech_conf
        bias_src  = "TECHNICAL"
        bias_hl   = mech_reason
        bias_brief = ""

    # ── 6. Opportunities ──────────────────────────────────────────────────────
    regime       = fundamentals.get("regime", "UNKNOWN")
    regime_ok    = regime not in ("NO_TRADE", "RISK_OFF")
    close        = mkt.get("close")
    ema20        = mkt.get("ema20")
    vwap         = mkt.get("vwap")
    adx          = mkt.get("adx")
    rsi          = mkt.get("rsi")
    state_brt    = (state or {}).get("brt_state", "NEUTRAL")
    watch_level  = (state or {}).get("watch_level")
    watch_ltype  = (state or {}).get("watch_ltype")

    # BRT opportunity
    brt_dir  = "LONG" if state_brt == "WATCHING_LONG" else "SHORT" if state_brt == "WATCHING_SHORT" else bias_dir
    brt_qual = advisory.get("signal_quality", "N/A") if advisory else (
        "HIGH" if adx and adx > 25 and regime_ok else
        "MEDIUM" if regime_ok else "LOW"
    )
    if watch_level and watch_ltype:
        brt_note = f"{'Broke above' if brt_dir == 'LONG' else 'Broke below'} {watch_ltype} — watching retest @ {watch_level:.2f}"
    elif close and ema20:
        gap = close - ema20
        brt_note = (f"Price {'above' if gap > 0 else 'below'} EMA20 by {abs(gap):.1f}pts — "
                    f"watching for break of key level")
    else:
        brt_note = advisory.get("watch_for") or "Monitoring for institutional breakout"

    # VWAP MR opportunity
    vwap_dir  = "NEUTRAL"
    vwap_note = "ADX too high for mean reversion" if (adx and adx > 20) else "Ranging market — VWAP reversion eligible"
    vwap_qual = "MEDIUM" if (adx and adx < 18 and regime_ok) else "LOW"
    if vwap and close:
        dev = close - vwap
        if abs(dev) > 4:
            vwap_dir  = "SHORT" if dev > 0 else "LONG"
            vwap_note = f"Price {'extended above' if dev > 0 else 'extended below'} VWAP by {abs(dev):.1f}pts — reversion candidate"
            vwap_qual = "MEDIUM" if regime_ok else "LOW"

    opportunities = [
        {
            "strategy":    "BRT",
            "symbol":      "MES",
            "timeframe":   "15min",
            "direction":   brt_dir,
            "quality":     brt_qual,
            "watch_level": watch_level,
            "level_type":  watch_ltype,
            "regime":      regime,
            "regime_ok":   regime_ok,
            "risk_flags":  advisory.get("risk_flags", []),
            "setup_note":  brt_note,
        },
        {
            "strategy":    "VWAP MR",
            "symbol":      "MES",
            "timeframe":   "5min",
            "direction":   vwap_dir,
            "quality":     vwap_qual,
            "watch_level": vwap,
            "level_type":  "VWAP",
            "regime":      regime,
            "regime_ok":   regime_ok and (adx is None or adx < 20),
            "risk_flags":  [],
            "setup_note":  vwap_note,
        },
    ]

    # ── 7. Trade watch ────────────────────────────────────────────────────────
    trade_watch = []
    if watch_level and watch_ltype and state_brt in ("WATCHING_LONG", "WATCHING_SHORT"):
        trade_watch.append({
            "priority":   1,
            "symbol":     "MES",
            "strategy":   "BRT",
            "direction":  brt_dir,
            "trigger":    f"Retest of {watch_ltype} @ {watch_level:.2f}",
            "confidence": advisory.get("signal_quality", "N/A"),
        })
    elif close and ema20:
        gap = close - ema20
        lvl = ema20 if abs(gap) < 8 else vwap
        lvl_name = "EMA20" if abs(gap) < 8 else "VWAP"
        trade_watch.append({
            "priority":   1,
            "symbol":     "MES",
            "strategy":   "BRT",
            "direction":  bias_dir,
            "trigger":    f"Watch for break + retest of {lvl_name} ({lvl:.2f})" if lvl else "Awaiting key level break",
            "confidence": brt_qual,
        })

    if vwap_dir != "NEUTRAL" and vwap:
        trade_watch.append({
            "priority":   2,
            "symbol":     "MES",
            "strategy":   "VWAP MR",
            "direction":  vwap_dir,
            "trigger":    f"Revert to VWAP ({vwap:.2f}) from {'above' if vwap_dir == 'SHORT' else 'below'}",
            "confidence": vwap_qual,
        })

    if selector.get("strategy") and selector.get("strategy") != "FLAT":
        conf_raw = selector.get("confidence")
        trade_watch.append({
            "priority":   3,
            "symbol":     "MES",
            "strategy":   selector["strategy"],
            "direction":  selector.get("bias", "NEUTRAL"),
            "trigger":    "LLM selector recommendation",
            "confidence": f"{conf_raw:.0%}" if conf_raw else "—",
        })

    # ── 8. Risk flags ─────────────────────────────────────────────────────────
    risk_flags = list(advisory.get("risk_flags", []))
    for hw in fundamentals.get("headwinds", []):
        if hw not in risk_flags:
            risk_flags.append(hw)

    # ── 9. Build and cache result ─────────────────────────────────────────────
    # Merge screener LLM cache (from background worker) with scheduler advisory
    _merged_adv = _llm_spec_cache if _llm_spec_cache else advisory

    result = {
        "available":  True,
        "as_of":      datetime.now(timezone.utc).isoformat(),
        "bias": {
            "direction":  bias_dir,
            "confidence": round(bias_conf, 3),
            "headline":   bias_hl,
            "brief":      bias_brief,
            "source":     bias_src,
            "timestamp":  advisory.get("timestamp") or datetime.now(timezone.utc).isoformat(),
            "watch_for":  advisory.get("watch_for", ""),
        },
        "specialists": {
            "grok": {
                "sentiment":   _merged_adv.get("sentiment", advisory.get("grok_sentiment", "")),
                "summary":     _merged_adv.get("grok_summary", advisory.get("grok_summary", "")),
                "trade_bias":  _merged_adv.get("grok_bias", ""),
                "bias_reason": _merged_adv.get("grok_bias_reason", ""),
            },
            "gpt4": {
                "summary":        _merged_adv.get("gpt4_summary", advisory.get("gpt4_summary", "")),
                "signal_quality": _merged_adv.get("signal_quality", ""),
                "watch_for":      _merged_adv.get("watch_for", ""),
                "macro_supports": _merged_adv.get("macro_supports"),
                "entry_low":      _merged_adv.get("entry_low"),
                "entry_high":     _merged_adv.get("entry_high"),
                "stop_level":     _merged_adv.get("stop_level"),
                "target_level":   _merged_adv.get("target_level"),
            },
            "claude": {
                "headline":   _merged_adv.get("headline", ""),
                "brief":      _merged_adv.get("brief", ""),
                "risk_flags": _merged_adv.get("risk_flags", []),
            },
            "selector":    selector or None,
            "llm_running": _llm_spec_running,
            "llm_last_run": datetime.fromtimestamp(_llm_spec_ts, tz=timezone.utc).isoformat()
                            if _llm_spec_ts else None,
        },
        "trade_idea": _merged_adv.get("trade_idea") or None,
        "opportunities": opportunities,
        "trade_watch":   trade_watch,
        "risk_flags":    risk_flags,
        "macro": {
            "vix":           fundamentals.get("vix"),
            "vix_regime":    fundamentals.get("vix_regime", ""),
            "regime":        regime,
            "yield_10y":     fundamentals.get("yield_10y"),
            "yield_trend":   fundamentals.get("yield_trend", ""),
            "dxy":           fundamentals.get("dxy"),
            "dxy_trend":     fundamentals.get("dxy_trend", ""),
            "spy_vol_ratio": fundamentals.get("spy_vol_ratio"),
            "session_open":  _is_session_open(),
            "close":         mkt.get("close"),
            "ema20":         mkt.get("ema20"),
            "vwap":          mkt.get("vwap"),
            "rsi":           mkt.get("rsi"),
            "adx":           mkt.get("adx"),
            "atr":           mkt.get("atr"),
            "pdh":           mkt.get("pdh"),
            "pdl":           mkt.get("pdl"),
            "tailwinds":     fundamentals.get("tailwinds", []),
        },
        "gate_status": gate_status,
    }

    _screener_cache    = result
    _screener_cache_ts = now
    return result


@app.post("/api/screener/refresh")
def api_screener_refresh():
    """Force-clear the screener cache so the next GET fetches fresh data."""
    global _screener_cache, _screener_cache_ts
    _screener_cache    = {}
    _screener_cache_ts = 0.0
    return {"cleared": True}


@app.post("/api/screener/analyze")
def api_screener_analyze():
    """
    Queue an immediate LLM specialist run (Grok + GPT-4 + Claude).
    Returns immediately — poll /api/screener for results.
    """
    global _llm_spec_queued
    if _llm_spec_running:
        return {"queued": False, "reason": "Already running"}
    _llm_spec_queued = True
    return {"queued": True}


@app.get("/api/screener/news")
def api_screener_news(limit: int = 30):
    """Live news feed — RSS + Grok breaking news items."""
    with _news_lock:
        items = list(_news_items[:limit])
    return {
        "items":      items,
        "count":      len(items),
        "grok_last":  datetime.fromtimestamp(_news_grok_ts, tz=timezone.utc).isoformat()
                      if _news_grok_ts else None,
    }


@app.get("/api/swing/screener")
def api_swing_screener():
    """
    Run the Momentum Swing universe scan and return today's setups.
    Cached for 10 minutes — daily strategy so no need for frequent refresh.
    """
    import time as _time
    cache = getattr(api_swing_screener, "_cache", None)
    cache_ts = getattr(api_swing_screener, "_cache_ts", 0)
    if cache is not None and (_time.time() - cache_ts) < 600:
        return cache
    try:
        from strategy.momentum_swing import MomentumSwingStrategy
        strategy = MomentumSwingStrategy()
        setups = strategy.scan_universe()
        result = {"setups": setups, "count": len(setups),
                  "as_of": datetime.now(timezone.utc).isoformat()}
        api_swing_screener._cache    = result
        api_swing_screener._cache_ts = _time.time()
        return result
    except Exception as e:
        logger.error(f"[SwingScreener] {e}")
        return {"setups": [], "count": 0, "error": str(e),
                "as_of": datetime.now(timezone.utc).isoformat()}


@app.get("/api/strategy/status")
def api_strategy_status():
    """
    Live signal status for all strategies — used by VWAP MR / ORB / RSI2 pages.
    Pulls from bot_state where available, fetches live data where needed.
    """
    import yfinance as yf
    import pandas as pd

    from config import settings as s

    state = get_bot_state() or {}

    # ── Shared market snapshot ─────────────────────────────────────────────────
    close = state.get("close")
    vwap  = state.get("vwap")
    adx   = state.get("adx")
    rsi   = state.get("rsi")
    orh   = state.get("orh")
    orl   = state.get("orl")

    # If scheduler not running, fetch live snapshot
    if not close:
        snap = _fetch_mes_snapshot()
        close = snap.get("close")
        vwap  = snap.get("vwap")
        adx   = snap.get("adx")
        rsi   = snap.get("rsi")

    # ── VWAP MR ───────────────────────────────────────────────────────────────
    deviation = (close - vwap) if (close and vwap) else None
    adx_max   = getattr(s, "VWAP_ADX_MAX", 15)
    vwap_eligible = (
        _is_session_open()
        and adx is not None and adx < adx_max
        and deviation is not None and abs(deviation) > 4
    )
    vwap_signal = "NEUTRAL"
    if vwap_eligible and deviation:
        vwap_signal = "SHORT" if deviation > 0 else "LONG"

    vwap_note = ""
    if not _is_session_open():
        vwap_note = "Market closed — no entries"
    elif adx and adx >= adx_max:
        vwap_note = f"ADX {adx:.1f} ≥ {adx_max} — trending, strategy skipped"
    elif deviation is not None and abs(deviation) < 4:
        vwap_note = f"Deviation only {abs(deviation):.1f} pts — waiting for ≥ 4 pts"
    elif vwap_eligible:
        vwap_note = f"Price {'above' if deviation > 0 else 'below'} VWAP by {abs(deviation):.1f} pts — eligible"

    # ── ORB ───────────────────────────────────────────────────────────────────
    import pytz
    et_now = datetime.now(pytz.timezone("America/New_York"))
    range_set = orh is not None and orl is not None
    orb_eligible = range_set and _is_session_open() and et_now.hour >= 10

    # Compute SMA20 from hourly data if possible
    sma20 = None
    orb_signal = "NEUTRAL"
    try:
        df_h = yf.Ticker("ES=F").history(period="30d", interval="1h", auto_adjust=True)
        if not df_h.empty:
            df_h.columns = [c.lower() for c in df_h.columns]
            sma20 = float(df_h["close"].tail(20).mean())
            if close and orb_eligible:
                if close > (orh or 0) and close > sma20:
                    orb_signal = "LONG"
                elif close < (orl or 0) and close < sma20:
                    orb_signal = "SHORT"
    except Exception:
        pass

    orb_note = ""
    if not range_set:
        orb_note = "Range sets 9:30–10:30 ET"
    elif not _is_session_open():
        orb_note = "Market closed"
    elif et_now.hour < 10:
        orb_note = "Waiting for range to form (10:30 ET)"
    elif orb_signal != "NEUTRAL":
        orb_note = f"{'LONG' if orb_signal == 'LONG' else 'SHORT'} breakout of opening range"
    else:
        orb_note = "Range formed — watching for breakout"

    # ── RSI2 (daily — fetch after market close) ───────────────────────────────
    rsi2_signals = {}
    for sym in ["SPY", "QQQ", "IWM"]:
        try:
            df = yf.Ticker(sym).history(period="300d", interval="1d", auto_adjust=True)
            if df.empty or len(df) < 10:
                continue
            df.columns = [c.lower() for c in df.columns]
            df = df[["open", "high", "low", "close", "volume"]].dropna()

            import ta as _ta
            rsi2_val = float(_ta.momentum.RSIIndicator(df["close"], window=2).rsi().iloc[-1])
            sma200   = float(df["close"].tail(200).mean()) if len(df) >= 200 else None
            sym_close = float(df["close"].iloc[-1])
            above_200 = sma200 is not None and sym_close > sma200
            eligible  = above_200 and rsi2_val < 10

            rsi2_signals[sym] = {
                "close":    round(sym_close, 2),
                "rsi2":     round(rsi2_val, 1),
                "sma200":   round(sma200, 2) if sma200 else None,
                "above_200ma": above_200,
                "eligible": eligible,
            }
        except Exception:
            rsi2_signals[sym] = {"close": None, "rsi2": None, "sma200": None,
                                 "above_200ma": None, "eligible": False}

    return {
        "VWAP_MR": {
            "enabled":   getattr(s, "STRATEGY_ENABLED", {}).get("VWAP_MR", False),
            "signal":    vwap_signal,
            "close":     close,
            "vwap":      vwap,
            "deviation": round(deviation, 2) if deviation is not None else None,
            "adx":       adx,
            "rsi":       rsi,
            "eligible":  vwap_eligible,
            "note":      vwap_note,
        },
        "ORB": {
            "enabled":  getattr(s, "STRATEGY_ENABLED", {}).get("ORB", False),
            "signal":   orb_signal,
            "close":    close,
            "orh":      orh,
            "orl":      orl,
            "sma20":    round(sma20, 2) if sma20 else None,
            "eligible": orb_eligible,
            "note":     orb_note,
        },
        "RSI2": {
            "enabled":  getattr(s, "STRATEGY_ENABLED", {}).get("RSI2", False),
            "signals":  rsi2_signals,
        },
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
        "strategy_enabled": {
            "BRT":   getattr(s, "STRATEGY_ENABLED", {}).get("BRT", True),
            "SWING": getattr(s, "STRATEGY_ENABLED", {}).get("SWING", False),
        },
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
