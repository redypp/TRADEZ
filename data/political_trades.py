"""
data/political_trades.py
────────────────────────
Congressional / political trading tracker.

US Congress members disclose stock trades under the STOCK Act.
Research shows congressional trades consistently outperform the market,
making cluster buying a strong institutional signal.

Data source: Quiver Quantitative API (free tier).
    https://api.quiverquant.com/beta/historical/congresstrading/{symbol}

Usage:
    from data.political_trades import get_congress_trades, get_political_score
    trades = get_congress_trades("NVDA")
    score_delta, detail = get_political_score("NVDA")
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

# Cache: symbol → (trades_list, timestamp)
_CONGRESS_CACHE: dict[str, tuple[list, float]] = {}
_CONGRESS_CACHE_TTL = 12 * 3600  # 12 hours — disclosures are delayed 45 days


def get_congress_trades(symbol: str, days: int = 90) -> list[dict]:
    """
    Fetch recent congressional stock trades for a symbol.

    Returns list of trades:
        [{
            "member": "Nancy Pelosi",
            "party": "D",
            "chamber": "House",
            "transaction_type": "Purchase",  # or "Sale"
            "amount_range": "$1,000,001 - $5,000,000",
            "disclosure_date": "2024-03-01",
            "transaction_date": "2024-02-15",
        }]
    """
    cached = _CONGRESS_CACHE.get(symbol)
    if cached and (time.time() - cached[1]) < _CONGRESS_CACHE_TTL:
        return cached[0]

    trades = []
    try:
        import requests

        # Quiver Quantitative free API
        url = f"https://api.quiverquant.com/beta/historical/congresstrading/{symbol}"
        headers = {
            "Accept": "application/json",
            "User-Agent": "TRADEZ-Bot",
        }

        resp = requests.get(url, headers=headers, timeout=10)
        if resp.status_code != 200:
            logger.debug(f"[Congress] API returned {resp.status_code} for {symbol}")
            _CONGRESS_CACHE[symbol] = ([], time.time())
            return []

        data = resp.json()
        cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

        for entry in data:
            tx_date = entry.get("TransactionDate", "") or entry.get("transaction_date", "")
            if tx_date and tx_date < cutoff:
                continue

            trades.append({
                "member": entry.get("Representative", entry.get("representative", "")),
                "party": entry.get("Party", entry.get("party", "")),
                "chamber": entry.get("House", entry.get("chamber", "")),
                "transaction_type": entry.get("Transaction", entry.get("transaction", "")),
                "amount_range": entry.get("Range", entry.get("amount", "")),
                "disclosure_date": entry.get("ReportDate", entry.get("disclosure_date", "")),
                "transaction_date": tx_date,
            })

    except Exception as e:
        logger.debug(f"[Congress] Failed to fetch trades for {symbol}: {e}")

    _CONGRESS_CACHE[symbol] = (trades, time.time())
    return trades


def get_political_score(symbol: str) -> tuple[int, str]:
    """
    Calculate score adjustment based on congressional trading activity.

    Returns (score_delta, detail_string).

    Scoring:
      - 1 congress member bought in 30d → +8
      - 2+ members bought in 60d → +12
      - Members selling → -5
    """
    trades = get_congress_trades(symbol, days=90)
    if not trades:
        return 0, "No congressional trades found"

    cutoff_30d = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
    cutoff_60d = (datetime.now() - timedelta(days=60)).strftime("%Y-%m-%d")

    buys_30d = []
    buys_60d = []
    sells_60d = []

    for t in trades:
        tx_date = t.get("transaction_date", "")
        tx_type = (t.get("transaction_type") or "").lower()

        if "purchase" in tx_type or "buy" in tx_type:
            if tx_date >= cutoff_30d:
                buys_30d.append(t)
            if tx_date >= cutoff_60d:
                buys_60d.append(t)
        elif "sale" in tx_type or "sell" in tx_type:
            if tx_date >= cutoff_60d:
                sells_60d.append(t)

    score = 0
    details = []

    # Unique members buying
    buy_members_30d = set(t["member"] for t in buys_30d if t["member"])
    buy_members_60d = set(t["member"] for t in buys_60d if t["member"])
    sell_members_60d = set(t["member"] for t in sells_60d if t["member"])

    if len(buy_members_60d) >= 2:
        score += 12
        names = ", ".join(list(buy_members_60d)[:3])
        details.append(f"+12: {len(buy_members_60d)} Congress members bought ({names})")
    elif len(buy_members_30d) >= 1:
        score += 8
        names = ", ".join(list(buy_members_30d)[:2])
        details.append(f"+8: {len(buy_members_30d)} Congress member(s) bought recently ({names})")

    if len(sell_members_60d) >= 2:
        score -= 5
        details.append(f"-5: {len(sell_members_60d)} members selling")
    elif len(sell_members_60d) == 1 and not buy_members_60d:
        score -= 3
        details.append(f"-3: Congress member sold ({list(sell_members_60d)[0]})")

    detail_str = " | ".join(details) if details else f"{len(trades)} trades in 90d (neutral)"
    return score, detail_str
