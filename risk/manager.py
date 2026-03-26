"""
risk/manager.py

Pre-trade risk checks. Every check must pass before an order is placed.
If any check fails the trade is blocked and the reason is logged.

Checks (in order):
    1. Fundamentals regime   — block if NO_TRADE or RISK_OFF (VIX / yield gate)
    2. Daily drawdown        — block if total portfolio equity down > MAX_DAILY_DRAWDOWN
    3. Open position         — block if already in this symbol
    4. Portfolio heat        — block if total risk-at-stop exceeds PORTFOLIO_HEAT_MAX
    5. Contract risk cap     — block if 1 contract exceeds MAX_TRADE_RISK of equity

Portfolio heat is computed across ALL brokers via router.get_portfolio().
Open trade heat is tracked in-process in OPEN_TRADES (cleared on restart).
"""

import logging
import sqlite3
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from config import settings

logger = logging.getLogger(__name__)


class RiskBlock(Exception):
    """Raised when a risk check blocks a trade."""
    pass


# ─── Open Trade Registry ──────────────────────────────────────────────────────
# Tracks active trades and their dollar risk at stop for portfolio heat.
# In-memory only — reset on process restart (fine for intraday strategies).

@dataclass
class OpenTrade:
    symbol:     str
    direction:  int        # 1 = long, -1 = short
    qty:        int
    entry:      float
    stop:       float
    tp:         float
    dollar_risk: float     # abs(entry - stop) * qty * point_value


# symbol → OpenTrade for current session
OPEN_TRADES: dict[str, OpenTrade] = {}

# ─── SQLite path (same DB as trade_log.py) ────────────────────────────────────
_DB_PATH = Path(__file__).parent.parent / "data" / "trades.db"

# ─── Consecutive loss tracker ──────────────────────────────────────────────────
# Tracks how many losses have occurred in a row this session.
# Reset to 0 on any winning trade. Reset to 0 at start of each day.
_streak: dict = {
    "consecutive_losses": 0,
    "last_reset_date":    None,
}


def _reset_streak_if_new_day() -> None:
    today = date.today()
    if _streak["last_reset_date"] != today:
        _streak["consecutive_losses"] = 0
        _streak["last_reset_date"]    = today


def record_trade_outcome(won: bool) -> None:
    """
    Call after a trade closes (TP or SL hit) to update the loss streak.

    Args:
        won : True if the trade was a winner, False if a loser
    """
    _reset_streak_if_new_day()
    if won:
        if _streak["consecutive_losses"] > 0:
            logger.info(
                f"Winning trade — consecutive loss streak reset "
                f"(was {_streak['consecutive_losses']})"
            )
        _streak["consecutive_losses"] = 0
    else:
        _streak["consecutive_losses"] += 1
        logger.warning(
            f"Losing trade — consecutive losses: {_streak['consecutive_losses']}"
        )


def get_risk_scale_factor() -> float:
    """
    Return the position-size scale factor based on current loss streak.

    Returns:
        1.0  — normal sizing
        BRT_LOSING_STREAK_RISK_FACTOR (e.g. 0.5) — step-down after N consecutive losses

    Example: 2 losses in a row → return 0.5 → trade at half normal risk.
    Recovery: next winning trade resets to 1.0 immediately.
    """
    _reset_streak_if_new_day()
    if _streak["consecutive_losses"] >= settings.BRT_LOSING_STREAK_MAX:
        factor = settings.BRT_LOSING_STREAK_RISK_FACTOR
        logger.warning(
            f"Drawdown step-down active — {_streak['consecutive_losses']} consecutive losses. "
            f"Risk factor: {factor:.0%} of normal."
        )
        return factor
    return 1.0


def register_trade(
    symbol:      str,
    direction:   int,
    qty:         int,
    entry:       float,
    stop:        float,
    tp:          float,
    point_value: float,
) -> None:
    """Call after a bracket order is successfully submitted."""
    dollar_risk = abs(entry - stop) * qty * point_value
    trade = OpenTrade(
        symbol=symbol, direction=direction, qty=qty,
        entry=entry, stop=stop, tp=tp, dollar_risk=dollar_risk,
    )
    OPEN_TRADES[symbol] = trade
    _persist_open_trade(trade)  # crash-safe: survives process restart
    logger.info(
        f"Trade registered: {symbol} x{qty} {'LONG' if direction==1 else 'SHORT'} | "
        f"entry={entry:.2f} SL={stop:.2f} TP={tp:.2f} | risk=${dollar_risk:.2f}"
    )


def close_trade(symbol: str) -> None:
    """Call when a trade is closed (TP hit, SL hit, or manual close)."""
    if symbol in OPEN_TRADES:
        logger.info(f"Trade closed: {symbol}")
        del OPEN_TRADES[symbol]
        _clear_persisted_trade(symbol)


def get_portfolio_heat_dollars() -> float:
    """Sum of dollar risk-at-stop across all currently registered open trades."""
    return sum(t.dollar_risk for t in OPEN_TRADES.values())


# ─── SQLite open trade persistence ────────────────────────────────────────────
# In-memory OPEN_TRADES is lost on process restart. These helpers persist/restore
# the registry so the bot can recover its risk state after a crash or restart.
# The open_positions table is managed here — trade_log.py manages its own tables.

def _db_connect() -> sqlite3.Connection:
    conn = sqlite3.connect(_DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_open_positions_table() -> None:
    """Create the open_positions table if it doesn't exist."""
    try:
        with _db_connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS open_positions (
                    symbol      TEXT PRIMARY KEY,
                    direction   INTEGER NOT NULL,
                    qty         INTEGER NOT NULL,
                    entry       REAL    NOT NULL,
                    stop        REAL    NOT NULL,
                    tp          REAL    NOT NULL,
                    dollar_risk REAL    NOT NULL,
                    opened_at   TEXT    NOT NULL
                )
            """)
    except Exception as e:
        logger.warning(f"Could not create open_positions table: {e}")


def load_open_trades_from_db() -> None:
    """
    Restore OPEN_TRADES from SQLite on startup.
    Call once at bot startup to survive crashes/restarts.

    If the broker shows a flat position for a symbol that's in the DB,
    the entry is stale — clear_stale_open_trades() handles that.
    """
    _ensure_open_positions_table()
    try:
        with _db_connect() as conn:
            rows = conn.execute("SELECT * FROM open_positions").fetchall()
        for row in rows:
            r = dict(row)
            OPEN_TRADES[r["symbol"]] = OpenTrade(
                symbol=r["symbol"],
                direction=r["direction"],
                qty=r["qty"],
                entry=r["entry"],
                stop=r["stop"],
                tp=r["tp"],
                dollar_risk=r["dollar_risk"],
            )
            logger.info(
                f"Restored open trade from DB: {r['symbol']} "
                f"{'LONG' if r['direction']==1 else 'SHORT'} x{r['qty']} "
                f"entry={r['entry']:.2f}"
            )
    except Exception as e:
        logger.warning(f"Could not restore open trades from DB: {e}")


def _persist_open_trade(trade: OpenTrade) -> None:
    """Write/update an open trade to SQLite."""
    _ensure_open_positions_table()
    try:
        from datetime import datetime, timezone
        with _db_connect() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO open_positions
                   (symbol, direction, qty, entry, stop, tp, dollar_risk, opened_at)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (trade.symbol, trade.direction, trade.qty, trade.entry,
                 trade.stop, trade.tp, trade.dollar_risk,
                 datetime.now(timezone.utc).isoformat()),
            )
    except Exception as e:
        logger.warning(f"Could not persist open trade for {trade.symbol}: {e}")


def _clear_persisted_trade(symbol: str) -> None:
    """Remove a closed trade from the open_positions table."""
    try:
        with _db_connect() as conn:
            conn.execute("DELETE FROM open_positions WHERE symbol=?", (symbol,))
    except Exception as e:
        logger.warning(f"Could not clear persisted trade for {symbol}: {e}")


def clear_stale_open_trades(live_positions: dict[str, int]) -> None:
    """
    Remove any open trades from the registry where the broker shows a flat position.
    Call after reconnecting to the broker on startup.

    Args:
        live_positions : {symbol: position_size} from broker (0 = flat)
    """
    stale = [sym for sym, pos in live_positions.items() if pos == 0 and sym in OPEN_TRADES]
    for sym in stale:
        logger.warning(
            f"Stale open trade cleared: {sym} was in registry but broker shows flat."
        )
        close_trade(sym)


# ─── Breakeven stop management ─────────────────────────────────────────────────

def check_breakeven_moves(live_prices: dict[str, float], router) -> None:
    """
    For each open trade, check if price has reached 1:1 R:R.
    If so, move the stop to breakeven (entry price) via the broker.

    Called each hourly tick BEFORE the new signal check.
    Requires settings.BRT_BREAKEVEN_AT_1R = True.

    Args:
        live_prices : {symbol: current_price} snapshot
        router      : execution router (must support router.modify_stop)
    """
    if not getattr(settings, "BRT_BREAKEVEN_AT_1R", False):
        return

    for symbol, trade in list(OPEN_TRADES.items()):
        price = live_prices.get(symbol)
        if price is None:
            continue

        risk   = abs(trade.entry - trade.stop)
        target_1r = (trade.entry + risk) if trade.direction == 1 else (trade.entry - risk)

        # Already at breakeven or better?
        if trade.direction == 1 and trade.stop >= trade.entry:
            continue
        if trade.direction == -1 and trade.stop <= trade.entry:
            continue

        # Has price reached 1R profit?
        reached_1r = (
            (trade.direction == 1  and price >= target_1r) or
            (trade.direction == -1 and price <= target_1r)
        )

        if reached_1r:
            try:
                router.modify_stop(symbol, trade.entry)
                # Update in-memory registry
                OPEN_TRADES[symbol] = OpenTrade(
                    symbol=symbol, direction=trade.direction, qty=trade.qty,
                    entry=trade.entry, stop=trade.entry, tp=trade.tp,
                    dollar_risk=0.0,  # stop at entry = zero risk remaining
                )
                _persist_open_trade(OPEN_TRADES[symbol])
                logger.info(
                    f"Breakeven stop set: {symbol} stop moved to entry {trade.entry:.2f} "
                    f"(price reached {price:.2f}, 1R={target_1r:.2f})"
                )
            except AttributeError:
                logger.warning(
                    f"Breakeven: router.modify_stop not implemented — "
                    f"add modify_stop() to execution/router.py to enable this feature."
                )
            except Exception as e:
                logger.warning(f"Breakeven stop move failed for {symbol}: {e}")


# ─── Main Check Entry Point ────────────────────────────────────────────────────

def check_all(
    symbol:             str,
    fundamentals:       dict,
    account_equity:     float,
    open_position_size: int,
    signal:             dict,
    point_value:        float | None = None,
    trades_today:       int          = 0,
) -> int:
    """
    Run all pre-trade checks and return the approved contract/share count.

    Args:
        symbol             : Instrument symbol (e.g. 'MES', 'SPY')
        fundamentals       : Output of get_live_fundamentals()
        account_equity     : Total portfolio equity across all brokers
        open_position_size : Current position in symbol (0 = flat)
        signal             : Dict with at minimum 'close' and 'stop_loss'
        point_value        : Dollar value per point (None = use settings default for symbol)

    Returns:
        Number of contracts/shares to trade (always >= 1 if checks pass)

    Raises:
        RiskBlock if any check fails
    """
    _check_fundamentals(fundamentals)
    _check_equity_floor(account_equity)
    _check_max_trades_today(trades_today)
    _check_open_position(symbol, open_position_size)
    _check_portfolio_heat(account_equity)
    point_val  = point_value or _get_point_value(symbol)
    contracts  = _check_position_size(symbol, signal, account_equity, point_val)
    return contracts


# ─── Individual checks ────────────────────────────────────────────────────────

def _check_equity_floor(account_equity: float) -> None:
    """Block all trading if account falls below the absolute equity floor."""
    floor = getattr(settings, "EQUITY_FLOOR", 0.0)
    if floor > 0 and account_equity < floor:
        raise RiskBlock(
            f"Account equity ${account_equity:,.2f} is below EQUITY_FLOOR ${floor:,.2f}. "
            f"All trading halted. Review performance and reset EQUITY_FLOOR to resume."
        )


def _check_max_trades_today(trades_today: int) -> None:
    """Block new entries if the daily trade cap has been reached."""
    max_trades = getattr(settings, "MAX_TRADES_PER_DAY", 5)
    if trades_today >= max_trades:
        raise RiskBlock(
            f"Daily trade cap reached: {trades_today} trades today "
            f"(MAX_TRADES_PER_DAY={max_trades}). "
            f"Choppy days generate many signals — capping prevents overtrading."
        )


def _check_fundamentals(fundamentals: dict) -> None:
    regime = fundamentals.get("regime", "CAUTIOUS")

    if regime == "NO_TRADE":
        vix = fundamentals.get("vix", "?")
        raise RiskBlock(f"NO_TRADE regime — VIX extreme ({vix}). All entries blocked.")

    if regime == "RISK_OFF":
        headwinds = " | ".join(fundamentals.get("headwinds", []))
        raise RiskBlock(f"RISK_OFF regime — multiple headwinds active: {headwinds}")

    if regime == "CAUTIOUS":
        logger.warning("CAUTIOUS regime — proceeding but staying selective")


def _check_open_position(symbol: str, open_position_size: int) -> None:
    if open_position_size != 0:
        raise RiskBlock(
            f"Already in {symbol} position ({open_position_size:+d}). "
            f"No new entries until flat."
        )


def _check_portfolio_heat(account_equity: float) -> None:
    """Block if total portfolio heat (risk at stop across all open trades) is too high."""
    if account_equity <= 0:
        return

    heat_dollars = get_portfolio_heat_dollars()
    heat_pct = heat_dollars / account_equity

    if heat_pct >= settings.PORTFOLIO_HEAT_MAX:
        raise RiskBlock(
            f"Portfolio heat limit reached: {heat_pct*100:.1f}% "
            f"(${heat_dollars:.2f} at risk across {len(OPEN_TRADES)} open trades). "
            f"Max allowed: {settings.PORTFOLIO_HEAT_MAX*100:.0f}%."
        )

    if heat_pct >= settings.PORTFOLIO_HEAT_MAX * 0.75:
        logger.warning(
            f"Portfolio heat at {heat_pct*100:.1f}% — approaching limit "
            f"({settings.PORTFOLIO_HEAT_MAX*100:.0f}%)"
        )


def _check_position_size(
    symbol:      str,
    signal:      dict,
    equity:      float,
    point_value: float,
) -> int:
    """
    Compute contract/share count from risk budget.
    Raises RiskBlock if even 1 contract exceeds the per-trade risk cap.
    Returns approved count (>= 1).
    """
    if signal.get("stop_loss") is None or signal.get("close") is None:
        raise RiskBlock("Signal missing stop_loss or close price.")

    # Apply step-down factor if in a losing streak
    scale = get_risk_scale_factor()

    # Apply late-session size reduction (liquidity thins after BRT_LATE_SESSION_HOUR)
    from datetime import datetime
    import pytz
    et_hour = datetime.now(pytz.timezone("America/New_York")).hour
    late_hour   = getattr(settings, "BRT_LATE_SESSION_HOUR", 14)
    late_factor = getattr(settings, "BRT_LATE_SESSION_SIZE_FACTOR", 1.0)
    if et_hour >= late_hour:
        scale *= late_factor
        logger.debug(f"Late-session size factor applied ({late_factor}x after {late_hour}:00 ET)")

    risk_budget   = equity * settings.RISK_PER_TRADE * scale
    max_risk_hard = equity * settings.MAX_TRADE_RISK
    points_at_risk = abs(signal["close"] - signal["stop_loss"])
    dollar_risk_1c = points_at_risk * point_value

    if dollar_risk_1c <= 0:
        raise RiskBlock("Stop loss distance is zero — invalid signal.")

    if dollar_risk_1c > max_risk_hard:
        raise RiskBlock(
            f"{symbol}: 1 unit risk ${dollar_risk_1c:.2f} exceeds hard cap "
            f"${max_risk_hard:.2f} ({settings.MAX_TRADE_RISK*100:.0f}% of equity). "
            f"Stop is {points_at_risk:.4f} pts — too wide to size safely."
        )

    contracts = max(1, int(risk_budget / dollar_risk_1c))

    logger.info(
        f"Risk check passed | {symbol} | equity=${equity:,.2f} | "
        f"budget=${risk_budget:.2f} | risk/unit=${dollar_risk_1c:.2f} | "
        f"units={contracts}"
    )
    return contracts


def check_daily_drawdown(account_equity: float, session_start_equity: float) -> None:
    """
    Block trading if today's drawdown exceeds MAX_DAILY_DRAWDOWN.
    Uses total portfolio equity across all brokers.

    Args:
        account_equity       : Current total portfolio equity (all brokers)
        session_start_equity : Equity recorded at market open today
    """
    if session_start_equity <= 0:
        return

    drawdown = (account_equity - session_start_equity) / session_start_equity

    if drawdown < -settings.MAX_DAILY_DRAWDOWN:
        raise RiskBlock(
            f"Daily drawdown limit hit: {drawdown*100:.1f}% "
            f"(max allowed: -{settings.MAX_DAILY_DRAWDOWN*100:.0f}%). "
            f"No more trades today."
        )

    if drawdown < -settings.MAX_DAILY_DRAWDOWN * 0.7:
        logger.warning(
            f"Approaching daily drawdown limit: {drawdown*100:.1f}% "
            f"(limit: -{settings.MAX_DAILY_DRAWDOWN*100:.0f}%)"
        )


# ─── Helpers ──────────────────────────────────────────────────────────────────

# Point value per instrument ($ per point per contract/share)
_POINT_VALUES: dict[str, float] = {
    "MES":  5.00,    # Micro E-mini S&P: $5/pt
    "ES":   50.00,   # E-mini S&P: $50/pt
    "MNQ":  2.00,    # Micro E-mini Nasdaq: $2/pt
    "NQ":   20.00,   # E-mini Nasdaq: $20/pt
    "MYM":  0.50,    # Micro E-mini Dow: $0.50/pt
    "MGC":  10.00,   # Micro Gold: $10/pt
    "GC":   100.00,  # Gold: $100/pt
    "SIL":  1000.00, # Silver: $1,000/pt (5,000 oz × $0.20/pt display)
    "SI":   5000.00, # Full silver contract
    "MCL":  100.00,  # Micro crude oil: $100/pt
    "CL":   1000.00, # Crude oil: $1,000/pt
    # Stocks/ETFs: point value = 1.0 (1 share × $1 move = $1)
}
_DEFAULT_STOCK_POINT_VALUE = 1.0


def _get_point_value(symbol: str) -> float:
    root = "".join(c for c in symbol.upper() if c.isalpha())
    return _POINT_VALUES.get(root, _DEFAULT_STOCK_POINT_VALUE)
