"""
SQLite trade logger — persists bot state and trade history for the web dashboard.

Tables:
    trades     — one row per completed trade (entry + exit)
    bot_state  — single-row live snapshot, updated every scheduler tick
"""

import sqlite3
import logging
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

DB_PATH = Path(__file__).parent.parent / "data" / "trades.db"


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """Create tables if they don't exist. Safe to call on every startup."""
    with _connect() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS events (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT    NOT NULL,
                level     TEXT    NOT NULL DEFAULT 'INFO',
                message   TEXT    NOT NULL,
                detail    TEXT
            );

            CREATE TABLE IF NOT EXISTS trades (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp        TEXT    NOT NULL,
                symbol           TEXT    NOT NULL DEFAULT 'MES',
                direction        TEXT    NOT NULL,
                level_type       TEXT,
                entry_price      REAL,
                stop_loss        REAL,
                take_profit      REAL,
                exit_price       REAL,
                exit_reason      TEXT,
                pnl              REAL,
                contracts        INTEGER DEFAULT 1,
                regime           TEXT,
                vix              REAL,
                liquidity_sweep  INTEGER DEFAULT 0,
                cot_bias         TEXT    DEFAULT 'NEUTRAL'
            );

            CREATE TABLE IF NOT EXISTS open_positions (
                symbol      TEXT PRIMARY KEY,
                direction   INTEGER NOT NULL,
                qty         INTEGER NOT NULL,
                entry       REAL    NOT NULL,
                stop        REAL    NOT NULL,
                tp          REAL    NOT NULL,
                dollar_risk REAL    NOT NULL,
                opened_at   TEXT    NOT NULL
            );

            CREATE TABLE IF NOT EXISTS bot_state (
                id              INTEGER PRIMARY KEY DEFAULT 1,
                updated_at      TEXT,
                brt_state       TEXT,
                watch_level     REAL,
                watch_ltype     TEXT,
                close           REAL,
                ema20           REAL,
                atr             REAL,
                adx             REAL,
                rsi             REAL,
                vwap            REAL,
                pdh             REAL,
                pdl             REAL,
                orh             REAL,
                orl             REAL,
                swing_hi        REAL,
                swing_lo        REAL,
                regime          TEXT,
                vix             REAL,
                yield_10y       REAL,
                dxy             REAL,
                spy_vol_ratio   REAL,
                session_open    INTEGER DEFAULT 0,
                daily_pnl       REAL    DEFAULT 0,
                trades_today    INTEGER DEFAULT 0,
                adx_min         REAL,
                sl_buffer       REAL,
                tp_rr           REAL,
                max_retest_bars INTEGER,
                headwinds       TEXT,
                tailwinds       TEXT,
                paper_trading   INTEGER DEFAULT 1
            );
        """)
    # Migrations: add new columns to existing tables if upgrading from older schema
    with _connect() as conn:
        trade_cols = [r[1] for r in conn.execute("PRAGMA table_info(trades)").fetchall()]
        if "liquidity_sweep" not in trade_cols:
            conn.execute("ALTER TABLE trades ADD COLUMN liquidity_sweep INTEGER DEFAULT 0")
        if "cot_bias" not in trade_cols:
            conn.execute("ALTER TABLE trades ADD COLUMN cot_bias TEXT DEFAULT 'NEUTRAL'")

        state_cols = [r[1] for r in conn.execute("PRAGMA table_info(bot_state)").fetchall()]
        for col, typedef in [
            ("prior_poc",     "REAL"),
            ("prior_vah",     "REAL"),
            ("prior_val",     "REAL"),
            ("eqh",           "REAL"),
            ("eql",           "REAL"),
            ("fvg_bull_low",  "REAL"),
            ("fvg_bull_high", "REAL"),
            ("fvg_bear_low",  "REAL"),
            ("fvg_bear_high", "REAL"),
            ("vpoc_migration", "TEXT"),   # "RISING" / "FALLING" / "NEUTRAL"
            ("llm_advisory",   "TEXT"),   # JSON blob from AI advisory engine
        ]:
            if col not in state_cols:
                conn.execute(f"ALTER TABLE bot_state ADD COLUMN {col} {typedef}")
    logger.info(f"Trade DB ready: {DB_PATH}")


def log_event(message: str, level: str = "INFO", detail: str | None = None) -> None:
    """Append a live activity event (shown in dashboard feed)."""
    ts = datetime.now(timezone.utc).isoformat()
    with _connect() as conn:
        conn.execute(
            "INSERT INTO events (timestamp, level, message, detail) VALUES (?,?,?,?)",
            (ts, level, message, detail),
        )


def get_recent_events(limit: int = 40) -> list[dict]:
    """Return recent activity events, newest first."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM events ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]


def log_trade(
    direction: str,
    level_type: str,
    entry_price: float,
    stop_loss: float,
    take_profit: float,
    exit_price: float | None = None,
    exit_reason: str | None = None,
    pnl: float | None = None,
    contracts: int = 1,
    regime: str | None = None,
    vix: float | None = None,
    symbol: str = "MES",
    liquidity_sweep: int = 0,
    cot_bias: str = "NEUTRAL",
) -> int:
    """Insert a trade record. Returns the new row id."""
    ts = datetime.now(timezone.utc).isoformat()
    with _connect() as conn:
        cur = conn.execute(
            """INSERT INTO trades
               (timestamp, symbol, direction, level_type, entry_price, stop_loss,
                take_profit, exit_price, exit_reason, pnl, contracts, regime, vix,
                liquidity_sweep, cot_bias)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (ts, symbol, direction, level_type, entry_price, stop_loss,
             take_profit, exit_price, exit_reason, pnl, contracts, regime, vix,
             int(liquidity_sweep), cot_bias),
        )
        return cur.lastrowid


def update_trade_exit(trade_id: int, exit_price: float,
                      exit_reason: str, pnl: float) -> None:
    """Fill in exit fields on an existing trade row."""
    with _connect() as conn:
        conn.execute(
            "UPDATE trades SET exit_price=?, exit_reason=?, pnl=? WHERE id=?",
            (exit_price, exit_reason, pnl, trade_id),
        )


def update_bot_state(state: dict) -> None:
    """
    Upsert the single bot_state row (id=1) with the current live snapshot.

    Expected keys in `state` dict (all optional, missing keys are ignored):
        brt_state, watch_level, watch_ltype, close, ema20, atr, adx, rsi,
        vwap, pdh, pdl, orh, orl, swing_hi, swing_lo,
        regime, vix, yield_10y, dxy, spy_vol_ratio,
        session_open, daily_pnl, trades_today,
        adx_min, sl_buffer, tp_rr, max_retest_bars,
        headwinds, tailwinds, paper_trading
    """
    state = dict(state)
    state["updated_at"] = datetime.now(timezone.utc).isoformat()
    state["id"] = 1

    # Serialize lists to comma-separated strings
    for key in ("headwinds", "tailwinds"):
        if isinstance(state.get(key), list):
            state[key] = " | ".join(state[key])

    columns = list(state.keys())
    placeholders = ", ".join(f":{c}" for c in columns)
    updates = ", ".join(f"{c}=excluded.{c}" for c in columns if c != "id")

    sql = f"""
        INSERT INTO bot_state ({', '.join(columns)})
        VALUES ({placeholders})
        ON CONFLICT(id) DO UPDATE SET {updates}
    """
    with _connect() as conn:
        conn.execute(sql, state)


def get_bot_state() -> dict | None:
    """Return the current bot state snapshot as a dict, or None if not set."""
    with _connect() as conn:
        row = conn.execute("SELECT * FROM bot_state WHERE id=1").fetchone()
        return dict(row) if row else None


def get_recent_trades(limit: int = 50) -> list[dict]:
    """Return the most recent completed trades (newest first)."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM trades ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]


def get_daily_summary(date_str: str | None = None) -> dict:
    """
    Return P&L summary for a given date (YYYY-MM-DD).
    Defaults to today (UTC).
    """
    if date_str is None:
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    with _connect() as conn:
        row = conn.execute(
            """SELECT COUNT(*) as total,
                      SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) as wins,
                      SUM(CASE WHEN pnl <= 0 THEN 1 ELSE 0 END) as losses,
                      COALESCE(SUM(pnl), 0) as total_pnl
               FROM trades
               WHERE timestamp LIKE ? AND exit_price IS NOT NULL""",
            (f"{date_str}%",),
        ).fetchone()
        return dict(row) if row else {"total": 0, "wins": 0, "losses": 0, "total_pnl": 0.0}


def get_equity_curve(limit: int = 200) -> list[dict]:
    """Return running equity curve points from trade history."""
    with _connect() as conn:
        rows = conn.execute(
            """SELECT timestamp, pnl
               FROM trades
               WHERE exit_price IS NOT NULL
               ORDER BY id ASC
               LIMIT ?""",
            (limit,),
        ).fetchall()

    equity = 0.0
    curve = []
    for r in rows:
        if r["pnl"] is not None:
            equity += r["pnl"]
        curve.append({"timestamp": r["timestamp"], "equity": round(equity, 2)})
    return curve
