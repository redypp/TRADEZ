"""
TRADEZ Web Dashboard — FastAPI backend.

Endpoints:
    GET  /               → serve dashboard HTML
    GET  /api/state      → live bot state snapshot
    GET  /api/trades     → recent trade history
    GET  /api/equity     → equity curve data points
    GET  /api/summary    → today's daily summary
    GET  /api/regime     → current regime info + params
    GET  /api/events     → recent activity events
    WS   /ws             → WebSocket — pushes full data bundle every 5s

Run:
    uvicorn web.api:app --reload --port 8000
"""

import asyncio
import sys
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse

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
    state   = get_bot_state()
    vix     = state.get("vix") if state else None
    summary = get_daily_summary()
    return {
        "state":   state,
        "trades":  get_recent_trades(limit=30),
        "equity":  get_equity_curve(limit=150),
        "summary": summary,
        "events":  get_recent_events(limit=40),
        "regime":  get_regime_info(vix),
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


@app.get("/api/all")
def api_all():
    return _full_payload()


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
