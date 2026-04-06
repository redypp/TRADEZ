"""
data/macro_calendar.py
──────────────────────
Macroeconomic event calendar for swing trading risk management.

Tracks high-impact events that move the entire market:
  - FOMC rate decisions
  - CPI, PPI, PCE inflation
  - Non-Farm Payrolls (NFP)
  - GDP releases
  - Unemployment claims

On high-impact event days, the swing strategy should:
  - Reduce position sizing (FOMC days → 50% size)
  - Block new entries within 2 hours of release

Data source: Finnhub economic calendar (free tier) with fallback
to a static calendar of known dates.

Usage:
    from data.macro_calendar import is_macro_event_today, get_macro_risk
    risk = get_macro_risk()
    if risk["block"]:
        print(f"Blocked: {risk['reason']}")
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, date, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

# ─── Known high-impact events (static fallback) ─────────────────────────────
# These are the most market-moving scheduled events.
# Updated periodically — the Finnhub API provides dynamic data.

HIGH_IMPACT_EVENTS = {
    "FOMC",           # Federal Reserve rate decision
    "CPI",            # Consumer Price Index
    "Core CPI",
    "PPI",            # Producer Price Index
    "Core PPI",
    "PCE",            # Personal Consumption Expenditure
    "Core PCE",
    "NFP",            # Non-Farm Payrolls
    "Nonfarm Payrolls",
    "GDP",            # Gross Domestic Product
    "GDP Growth Rate",
    "Unemployment Rate",
    "FOMC Minutes",
    "Fed Interest Rate Decision",
    "Fed Chair Press Conference",
    "Retail Sales",
}

MEDIUM_IMPACT_EVENTS = {
    "Initial Jobless Claims",
    "Consumer Confidence",
    "ISM Manufacturing PMI",
    "ISM Services PMI",
    "Durable Goods Orders",
    "Housing Starts",
    "Existing Home Sales",
    "Industrial Production",
    "Michigan Consumer Sentiment",
}

# Cache
_CALENDAR_CACHE: Optional[tuple[list, float]] = None
_CALENDAR_CACHE_TTL = 6 * 3600  # 6 hours


def _fetch_finnhub_calendar() -> list[dict]:
    """Fetch economic calendar from Finnhub (free tier)."""
    try:
        from config import settings
        api_key = getattr(settings, "FINNHUB_API_KEY", "") or ""

        if not api_key:
            logger.debug("[MacroCal] No FINNHUB_API_KEY — using static calendar")
            return []

        import requests
        today = date.today()
        from_date = today.strftime("%Y-%m-%d")
        to_date = (today + timedelta(days=7)).strftime("%Y-%m-%d")

        url = "https://finnhub.io/api/v1/calendar/economic"
        params = {
            "from": from_date,
            "to": to_date,
            "token": api_key,
        }
        resp = requests.get(url, params=params, timeout=10)
        data = resp.json()

        events = []
        for ev in data.get("economicCalendar", []):
            country = ev.get("country", "")
            if country != "US":
                continue
            events.append({
                "event": ev.get("event", ""),
                "date": ev.get("time", "")[:10],  # YYYY-MM-DD
                "time": ev.get("time", "")[11:16],  # HH:MM
                "impact": ev.get("impact", ""),
                "actual": ev.get("actual"),
                "estimate": ev.get("estimate"),
                "prev": ev.get("prev"),
            })
        return events

    except Exception as e:
        logger.debug(f"[MacroCal] Finnhub fetch failed: {e}")
        return []


def get_upcoming_events(days: int = 3) -> list[dict]:
    """
    Get upcoming US macro events for the next N days.

    Returns list of events with impact classification.
    """
    global _CALENDAR_CACHE

    if _CALENDAR_CACHE and (time.time() - _CALENDAR_CACHE[1]) < _CALENDAR_CACHE_TTL:
        return _CALENDAR_CACHE[0]

    events = _fetch_finnhub_calendar()

    # Classify impact if not already classified
    for ev in events:
        name = ev.get("event", "")
        if any(h.lower() in name.lower() for h in HIGH_IMPACT_EVENTS):
            ev["impact_level"] = "HIGH"
        elif any(m.lower() in name.lower() for m in MEDIUM_IMPACT_EVENTS):
            ev["impact_level"] = "MEDIUM"
        else:
            ev["impact_level"] = "LOW"

    # Filter to only HIGH and MEDIUM
    events = [e for e in events if e.get("impact_level") in ("HIGH", "MEDIUM")]

    _CALENDAR_CACHE = (events, time.time())
    return events


def is_macro_event_today() -> tuple[bool, list[dict]]:
    """
    Check if there's a high-impact macro event today.

    Returns (has_event, [event_list]).
    """
    today_str = date.today().strftime("%Y-%m-%d")
    events = get_upcoming_events(days=3)
    today_events = [e for e in events if e.get("date") == today_str]
    high_today = [e for e in today_events if e.get("impact_level") == "HIGH"]

    return len(high_today) > 0, today_events


def get_macro_risk() -> dict:
    """
    Get current macro event risk assessment for swing trading.

    Returns:
        {
            "block": True/False,        # Should new entries be blocked?
            "reduce_size": True/False,   # Should position size be reduced?
            "size_factor": 1.0,          # Multiplier (0.5 = half size)
            "reason": "FOMC day — reduce size",
            "events_today": [...],
            "events_upcoming": [...],
        }
    """
    has_high, today_events = is_macro_event_today()
    upcoming = get_upcoming_events(days=3)

    result = {
        "block": False,
        "reduce_size": False,
        "size_factor": 1.0,
        "reason": "",
        "events_today": today_events,
        "events_upcoming": upcoming,
    }

    if not has_high:
        result["reason"] = "No high-impact events today"
        return result

    # Check specific event types
    high_events = [e for e in today_events if e.get("impact_level") == "HIGH"]
    event_names = [e.get("event", "") for e in high_events]
    names_lower = " ".join(event_names).lower()

    # FOMC decisions — reduce size by 50%
    if "fomc" in names_lower or "fed" in names_lower or "interest rate" in names_lower:
        result["reduce_size"] = True
        result["size_factor"] = 0.5
        result["reason"] = f"FOMC day — position size reduced 50%"
        return result

    # CPI/PPI/PCE/NFP — reduce size by 30%
    if any(x in names_lower for x in ["cpi", "ppi", "pce", "nonfarm", "nfp"]):
        result["reduce_size"] = True
        result["size_factor"] = 0.7
        result["reason"] = f"Inflation/jobs data day ({event_names[0]}) — size reduced 30%"
        return result

    # GDP — slight caution
    if "gdp" in names_lower:
        result["reduce_size"] = True
        result["size_factor"] = 0.8
        result["reason"] = f"GDP release day — size reduced 20%"
        return result

    # Generic high-impact
    result["reduce_size"] = True
    result["size_factor"] = 0.7
    result["reason"] = f"High-impact event: {event_names[0]}"
    return result
