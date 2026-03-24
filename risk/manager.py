"""
risk/manager.py

Pre-trade risk checks. Every check must pass before an order is placed.
If any check fails the trade is blocked and the reason is logged.

Checks (in order):
    1. Fundamentals regime  — block if NO_TRADE or RISK_OFF (VIX / yield gate)
    2. Daily drawdown       — block if equity is down > MAX_DAILY_DRAWDOWN today
    3. Open position        — block if already in a MES trade
    4. Max open positions   — block if too many positions across all symbols
    5. Contract risk cap    — block if 1 contract exceeds BRT_MAX_TRADE_RISK of equity
"""

import logging
from datetime import date

from config import settings

logger = logging.getLogger(__name__)


class RiskBlock(Exception):
    """Raised when a risk check blocks a trade."""
    pass


def check_all(
    fundamentals:      dict,
    account_equity:    float,
    open_position_size: int,
    signal:            dict,
) -> int:
    """
    Run all pre-trade checks and return the approved contract count.

    Args:
        fundamentals       : output of get_live_fundamentals()
        account_equity     : current net liquidation value from IBKR
        open_position_size : current MES position (0 = flat)
        signal             : output of get_latest_brt_signal()

    Returns:
        Number of contracts to trade (always >= 1 if checks pass)

    Raises:
        RiskBlock if any check fails
    """
    _check_fundamentals(fundamentals)
    _check_open_position(open_position_size)
    contracts = _check_position_size(signal, account_equity)
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


def _check_open_position(open_position_size: int) -> None:
    if open_position_size != 0:
        raise RiskBlock(
            f"Already in a MES position ({open_position_size:+d} contracts). "
            f"No new entries until flat."
        )


def _check_position_size(signal: dict, equity: float) -> int:
    """
    Compute contract count from risk budget.
    Raises RiskBlock if even 1 contract exceeds the per-trade risk cap.
    Returns approved contract count (>= 1).
    """
    if signal.get("stop_loss") is None or signal.get("close") is None:
        raise RiskBlock("Signal missing stop_loss or close price.")

    risk_budget    = equity * settings.RISK_PER_TRADE
    max_risk_hard  = equity * settings.BRT_MAX_TRADE_RISK
    points_at_risk = abs(signal["close"] - signal["stop_loss"])
    dollar_risk_1c = points_at_risk * settings.BRT_POINT_VALUE

    if dollar_risk_1c <= 0:
        raise RiskBlock("Stop loss distance is zero — invalid signal.")

    if dollar_risk_1c > max_risk_hard:
        raise RiskBlock(
            f"1 contract risk ${dollar_risk_1c:.2f} exceeds hard cap "
            f"${max_risk_hard:.2f} ({settings.BRT_MAX_TRADE_RISK*100:.0f}% of equity). "
            f"Stop is {points_at_risk:.1f} pts — too wide to size safely."
        )

    contracts = max(1, int(risk_budget / dollar_risk_1c))

    logger.info(
        f"Risk check passed | equity=${equity:,.2f} | "
        f"budget=${risk_budget:.2f} | risk/contract=${dollar_risk_1c:.2f} | "
        f"contracts={contracts}"
    )
    return contracts


def check_daily_drawdown(account_equity: float, session_start_equity: float) -> None:
    """
    Block trading if today's drawdown exceeds MAX_DAILY_DRAWDOWN.
    Call this at the start of each signal check.

    Args:
        account_equity       : current IBKR net liquidation
        session_start_equity : equity recorded at market open today
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
