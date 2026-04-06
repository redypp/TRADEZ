"""
data/sec_edgar.py
─────────────────
SEC EDGAR filing monitor for swing trading edge.

Tracks material filings for swing universe stocks:
  - 8-K filings:  M&A, guidance changes, executive departures, material events
  - Form 4:       Insider transaction detail (individual buys/sells with prices)
  - 13D/13G:      Activist accumulations >5% ownership

Data source: SEC EDGAR EFTS API (completely free, no API key required).
Rate limit: 10 requests/sec per SEC fair access policy. We use User-Agent header.

Usage:
    from data.sec_edgar import get_recent_filings, get_sec_score
    filings = get_recent_filings("AAPL", days=14)
    score_delta, detail = get_sec_score("AAPL")
"""

from __future__ import annotations

import logging
import time
import re
from datetime import datetime, timedelta
from typing import Optional

import requests

logger = logging.getLogger(__name__)

# SEC EDGAR requires a valid User-Agent header
_HEADERS = {
    "User-Agent": "TRADEZ-Bot research@tradez.dev",
    "Accept": "application/json",
}

# SEC EFTS full-text search API
_EFTS_URL = "https://efts.sec.gov/LATEST/search-index"

# SEC EDGAR company filings API
_FILINGS_URL = "https://efts.sec.gov/LATEST/search-index"
_EDGAR_SEARCH_URL = "https://efts.sec.gov/LATEST/search-index"

# CIK lookup cache
_CIK_CACHE: dict[str, str] = {}

# Filing cache: symbol → (filings_list, timestamp)
_FILING_CACHE: dict[str, tuple[list, float]] = {}
_FILING_CACHE_TTL = 3600  # 1 hour — filings don't appear every minute


def _get_cik(symbol: str) -> Optional[str]:
    """Look up SEC CIK number for a ticker symbol."""
    if symbol in _CIK_CACHE:
        return _CIK_CACHE[symbol]
    try:
        url = "https://www.sec.gov/cgi-bin/browse-edgar"
        params = {
            "action": "getcompany",
            "company": "",
            "CIK": symbol,
            "type": "",
            "dateb": "",
            "owner": "include",
            "count": 1,
            "search_text": "",
            "output": "atom",
        }
        resp = requests.get(url, params=params, headers=_HEADERS, timeout=8)
        # Extract CIK from response
        match = re.search(r"CIK=(\d+)", resp.text)
        if match:
            cik = match.group(1).zfill(10)
            _CIK_CACHE[symbol] = cik
            return cik
    except Exception as e:
        logger.debug(f"[SEC] CIK lookup failed for {symbol}: {e}")
    return None


def get_recent_filings(symbol: str, days: int = 14) -> list[dict]:
    """
    Fetch recent SEC filings for a symbol.

    Returns list of dicts:
        [{
            "form_type": "8-K",
            "filed_date": "2024-03-15",
            "description": "Material event...",
            "url": "https://...",
        }]
    """
    cached = _FILING_CACHE.get(symbol)
    if cached and (time.time() - cached[1]) < _FILING_CACHE_TTL:
        return cached[0]

    filings = []
    try:
        filings = _fetch_edgar_company_filings(symbol, days)
    except Exception as e:
        logger.debug(f"[SEC] Filing fetch failed for {symbol}: {e}")

    _FILING_CACHE[symbol] = (filings, time.time())
    return filings


def _fetch_edgar_company_filings(symbol: str, days: int = 14) -> list[dict]:
    """Fallback: fetch filings from SEC EDGAR company search API."""
    filings = []
    try:
        # Use the SEC company tickers JSON to get CIK
        resp = requests.get(
            "https://www.sec.gov/files/company_tickers.json",
            headers=_HEADERS,
            timeout=8,
        )
        tickers = resp.json()
        cik = None
        for _, entry in tickers.items():
            if entry.get("ticker", "").upper() == symbol.upper():
                cik = str(entry["cik_str"]).zfill(10)
                break

        if not cik:
            return []

        # Fetch recent filings for this CIK
        url = f"https://data.sec.gov/submissions/CIK{cik}.json"
        resp = requests.get(url, headers=_HEADERS, timeout=10)
        data = resp.json()

        recent = data.get("filings", {}).get("recent", {})
        forms = recent.get("form", [])
        dates = recent.get("filingDate", [])
        descriptions = recent.get("primaryDocDescription", [])
        accessions = recent.get("accessionNumber", [])

        cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

        for i, (form, date, desc, acc) in enumerate(zip(forms, dates, descriptions, accessions)):
            if date < cutoff:
                break  # filings are sorted newest first
            if form in ("8-K", "8-K/A", "4", "4/A", "SC 13D", "SC 13D/A", "SC 13G", "SC 13G/A"):
                acc_no = acc.replace("-", "")
                filings.append({
                    "form_type": form,
                    "filed_date": date,
                    "description": desc or form,
                    "url": f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc_no}/",
                    "entity_name": data.get("name", symbol),
                })
            if len(filings) >= 20:
                break

    except Exception as e:
        logger.debug(f"[SEC] Fallback filing fetch failed for {symbol}: {e}")

    return filings


def get_form4_cluster(symbol: str, days: int = 14) -> dict:
    """
    Analyze Form 4 filings for insider buying/selling clusters.

    Returns:
        {
            "cluster_buy": True/False,  # 3+ insiders buying in window
            "cluster_sell": True/False,
            "buy_count": int,
            "sell_count": int,
            "detail": "3 insiders bought in last 14 days"
        }
    """
    result = {"cluster_buy": False, "cluster_sell": False,
              "buy_count": 0, "sell_count": 0, "detail": ""}

    filings = get_recent_filings(symbol, days=days)
    form4s = [f for f in filings if f["form_type"] in ("4", "4/A")]

    # Count Form 4 filings — each typically = one insider transaction
    # We can't parse the XML without another request, so we use count as proxy
    buy_count = 0
    sell_count = 0

    for f4 in form4s:
        desc = (f4.get("description") or "").lower()
        # Heuristic: Form 4 descriptions sometimes mention acquisition/disposition
        if "acqui" in desc or "purchase" in desc or "grant" in desc:
            buy_count += 1
        elif "dispos" in desc or "sale" in desc:
            sell_count += 1
        else:
            # Unknown direction — count as neutral
            buy_count += 0.5
            sell_count += 0.5

    result["buy_count"] = int(buy_count)
    result["sell_count"] = int(sell_count)

    if buy_count >= 3:
        result["cluster_buy"] = True
        result["detail"] = f"{int(buy_count)} insider buys in last {days}d (cluster)"
    elif sell_count >= 3:
        result["cluster_sell"] = True
        result["detail"] = f"{int(sell_count)} insider sales in last {days}d (cluster)"
    else:
        result["detail"] = f"Form 4: {int(buy_count)} buys, {int(sell_count)} sells ({days}d)"

    return result


def has_activist_filing(symbol: str, days: int = 30) -> dict:
    """
    Check for 13D/13G filings indicating activist/large holder accumulation.

    Returns:
        {
            "has_13d": True/False,
            "has_13g": True/False,
            "detail": "13D filed 2024-03-10 — activist accumulation"
        }
    """
    result = {"has_13d": False, "has_13g": False, "detail": ""}

    filings = get_recent_filings(symbol, days=days)
    for f in filings:
        ft = f.get("form_type", "")
        if "13D" in ft:
            result["has_13d"] = True
            result["detail"] = f"SC 13D filed {f['filed_date']} — activist accumulation >5%"
            break
        elif "13G" in ft:
            result["has_13g"] = True
            result["detail"] = f"SC 13G filed {f['filed_date']} — passive large holder >5%"

    return result


def has_material_8k(symbol: str, days: int = 7) -> dict:
    """
    Check for recent 8-K filings indicating material events.

    Returns:
        {
            "has_8k": True/False,
            "count": int,
            "latest_date": "2024-03-15",
            "detail": "8-K filed 2024-03-15 — material event"
        }
    """
    filings = get_recent_filings(symbol, days=days)
    eightks = [f for f in filings if f["form_type"] in ("8-K", "8-K/A")]

    if not eightks:
        return {"has_8k": False, "count": 0, "latest_date": "", "detail": ""}

    latest = eightks[0]
    return {
        "has_8k": True,
        "count": len(eightks),
        "latest_date": latest["filed_date"],
        "detail": f"{len(eightks)} 8-K(s) in {days}d — latest {latest['filed_date']}",
    }


def get_sec_score(symbol: str) -> tuple[int, str]:
    """
    Calculate a score adjustment (-20 to +15) based on SEC filings.

    Returns (score_delta, detail_string).
    """
    score = 0
    details = []

    # Form 4 cluster analysis
    f4 = get_form4_cluster(symbol, days=14)
    if f4["cluster_buy"]:
        score += 12
        details.append(f"+12: {f4['detail']}")
    elif f4["cluster_sell"]:
        score -= 8
        details.append(f"-8: {f4['detail']}")

    # 13D activist filing
    activist = has_activist_filing(symbol, days=30)
    if activist["has_13d"]:
        score += 10
        details.append(f"+10: {activist['detail']}")
    elif activist["has_13g"]:
        score += 4
        details.append(f"+4: {activist['detail']}")

    # 8-K material events (recent = attention, can be positive or negative)
    eightk = has_material_8k(symbol, days=7)
    if eightk["has_8k"] and eightk["count"] >= 2:
        # Multiple 8-Ks in a week = high activity, flag for caution
        score -= 3
        details.append(f"-3: High 8-K activity ({eightk['count']} in 7d) — verify catalyst")
    elif eightk["has_8k"]:
        # Single 8-K = notable but needs context (LLM will interpret)
        details.append(f"Note: {eightk['detail']}")

    detail_str = " | ".join(details) if details else "No notable SEC filings"
    return score, detail_str
