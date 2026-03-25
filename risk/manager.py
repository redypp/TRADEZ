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
from dataclasses import dataclass, field
from datetime import date

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
    OPEN_TRADES[symbol] = OpenTrade(
        symbol=symbol, direction=direction, qty=qty,
        entry=entry, stop=stop, tp=tp, dollar_risk=dollar_risk,
    )
    logger.info(
        f"Trade registered: {symbol} x{qty} {'LONG' if direction==1 else 'SHORT'} | "
        f"entry={entry:.2f} SL={stop:.2f} TP={tp:.2f} | risk=${dollar_risk:.2f}"
    )


def close_trade(symbol: str) -> None:
    """Call when a trade is closed (TP hit, SL hit, or manual close)."""
    if symbol in OPEN_TRADES:
        logger.info(f"Trade closed: {symbol}")
        del OPEN_TRADES[symbol]


def get_portfolio_heat_dollars() -> float:
    """Sum of dollar risk-at-stop across all currently registered open trades."""
    return sum(t.dollar_risk for t in OPEN_TRADES.values())


# ─── Main Check Entry Point ────────────────────────────────────────────────────

def check_all(
    symbol:             str,
    fundamentals:       dict,
    account_equity:     float,
    open_position_size: int,
    signal:             dict,
    point_value:        float | None = None,
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
    _check_open_position(symbol, open_position_size)
    _check_portfolio_heat(account_equity)
    point_val = point_value or _get_point_value(symbol)
    contracts = _check_position_size(symbol, signal, account_equity, point_val)
    return contracts


# ─── Individual checks ────────────────────────────────────────────────────────

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

    risk_budget   = equity * settings.RISK_PER_TRADE
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
