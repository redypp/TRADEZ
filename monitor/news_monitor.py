"""
monitor/news_monitor.py

Real-time news & social media monitor — runs as a background daemon thread.
Polls RSS feeds every NEWS_POLL_INTERVAL_SECONDS and Grok (X/Twitter) every
NEWS_GROK_INTERVAL_SECONDS. Sends immediate Telegram alerts on HIGH/MEDIUM
impact events and optionally sets a trading halt flag.

Sources:
    RSS (no API key):
        - Reuters Business
        - CNBC Top News
        - MarketWatch Top Stories
        - CoinDesk (crypto)
        - Decrypt (crypto)
    Grok (xAI API — requires XAI_API_KEY):
        - Live X/Twitter scan for breaking market-moving news

Integration:
    1. Start the monitor at bot startup:
           from monitor.news_monitor import NewsMonitor
           news_monitor = NewsMonitor()
           news_monitor.start()

    2. Check halt flag in strategy layer (optional, requires NEWS_HALT_ENABLED=true):
           from monitor.news_monitor import is_news_halt_active
           if is_news_halt_active():
               return  # skip entry during breaking news window
"""

import asyncio
import hashlib
import json
import logging
import re
import threading
import time
from datetime import datetime, timedelta
from typing import Optional

import pytz
import requests

logger = logging.getLogger(__name__)

ET = pytz.timezone("America/New_York")

# ─────────────────────────────────────────────────────────────────────────────
# Impact keyword scoring
# ─────────────────────────────────────────────────────────────────────────────

_HIGH_KEYWORDS = [
    "emergency", "flash crash", "circuit breaker", "halt trading", "suspend",
    "fed rate", "fomc", "federal reserve decision", "rate cut", "rate hike",
    "cpi", "pce", "nfp", "jobs report", "gdp", "inflation data",
    "war", "attack", "explosion", "geopolitical", "sanctions", "default",
    "bitcoin etf", "btc etf", "crypto ban", "sec ruling", "sec lawsuit",
    "partnership", "acquisition", "merger", "buyout", "takeover",
    "stripe", "paypal", "visa", "mastercard", "blackrock", "fidelity",
    "black swan", "systemic", "contagion", "bankruptcy", "collapse",
    "tariff", "trade war", "executive order",
]

_MEDIUM_KEYWORDS = [
    "earnings", "revenue miss", "revenue beat", "guidance", "outlook",
    "fed speaker", "powell", "yellen", "bullard", "kashkari", "waller",
    "jobless claims", "pmi", "ism", "consumer confidence",
    "layoffs", "restructuring", "profit warning",
    "oil", "opec", "natural gas", "supply chain",
    "bitcoin", "ethereum", "crypto", "defi", "blockchain",
    "recession", "slowdown", "contraction", "stagflation",
    "ipo", "spac", "secondary offering",
]


def _score_impact(text: str) -> str:
    """Return HIGH, MEDIUM, or LOW based on keyword presence."""
    lower = text.lower()
    for kw in _HIGH_KEYWORDS:
        if kw in lower:
            return "HIGH"
    for kw in _MEDIUM_KEYWORDS:
        if kw in lower:
            return "MEDIUM"
    return "LOW"


def _headline_hash(headline: str) -> str:
    return hashlib.md5(headline.lower().strip().encode()).hexdigest()[:12]


# ─────────────────────────────────────────────────────────────────────────────
# RSS feed definitions
# ─────────────────────────────────────────────────────────────────────────────

RSS_FEEDS = [
    ("Reuters Business",  "https://feeds.reuters.com/reuters/businessNews"),
    ("CNBC",              "https://www.cnbc.com/id/100003114/device/rss/rss.html"),
    ("MarketWatch",       "https://feeds.marketwatch.com/marketwatch/topstories/"),
    ("CoinDesk",          "https://www.coindesk.com/arc/outboundfeeds/rss/"),
    ("Decrypt",           "https://decrypt.co/feed"),
]

# ─────────────────────────────────────────────────────────────────────────────
# Grok breaking-news prompt
# ─────────────────────────────────────────────────────────────────────────────

_GROK_NEWS_PROMPT = """\
You are a real-time market news scanner for a futures trader.

Scan X/Twitter and news right now for anything that broke in the LAST 5 MINUTES
that could immediately move ES/S&P 500 futures, BTC, or major markets.

High-priority examples:
- Fed emergency action or surprise statement
- Major company partnership or acquisition (e.g. Stripe+BTC, PayPal+crypto)
- Geopolitical shock (attack, war escalation, major sanctions)
- BTC/crypto ETF approval or rejection
- Flash crash, trading halt, exchange suspension
- Surprise economic data release (CPI, NFP, GDP)
- Major regulatory ruling (SEC, CFTC)

If NOTHING notable broke in the last 5 minutes, respond exactly:
{"impact": "NONE", "headline": "", "summary": "", "assets": ""}

If something broke:
{"impact": "HIGH|MEDIUM", "headline": "<under 70 chars>", "summary": "<2 sentences max>", "assets": "<e.g. BTC, ES, GOLD or ALL>"}

Be factual. Only report what actually just happened, not what might happen."""


# ─────────────────────────────────────────────────────────────────────────────
# Grok: assess directional trade impact for MES
# ─────────────────────────────────────────────────────────────────────────────

_GROK_TRADE_PROMPT = """\
Breaking news just hit: "{headline}"

You are advising a MES (Micro E-mini S&P 500 futures) trader.

In the next 30-60 minutes, is this news directionally BULLISH, BEARISH, or NEUTRAL for ES/MES?

Examples:
- "Fed emergency rate cut" → BULLISH (markets rally on rate cuts), confidence 0.85
- "CPI comes in above expectations" → BEARISH (rate hike fear), confidence 0.80
- "Stripe announces Bitcoin payments" → NEUTRAL for MES (crypto specific, indirect), confidence 0.65
- "Flash crash / circuit breaker triggered" → BEARISH, confidence 0.95
- "Strong NFP beat" → can be BEARISH (rate fear) or BULLISH depending on magnitude

Be direct. Only give HIGH confidence (>0.75) if the impact on ES is clear and immediate.

Respond in JSON only:
{{"direction": "BULLISH|BEARISH|NEUTRAL", "confidence": 0.0-1.0, "reason": "<1 sentence>"}}"""


def _assess_trade_direction(headline: str) -> Optional[dict]:
    """Ask Grok: given this headline, which way should we trade MES?"""
    from config import settings
    api_key = getattr(settings, "XAI_API_KEY", "") or ""
    if not api_key:
        return None

    try:
        import openai
        import json, re
        client = openai.OpenAI(api_key=api_key, base_url="https://api.x.ai/v1")
        resp = client.chat.completions.create(
            model="grok-4.20-0309-reasoning",
            messages=[{"role": "user", "content": _GROK_TRADE_PROMPT.format(headline=headline)}],
            temperature=0.1,
            max_tokens=150,
            timeout=10,
        )
        text = resp.choices[0].message.content or ""
        text = re.sub(r"```(?:json)?", "", text).strip()
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            return json.loads(match.group())
    except Exception as e:
        logger.debug(f"[NewsMonitor] Trade direction assessment failed: {e}")

    return None


# ─────────────────────────────────────────────────────────────────────────────
# Shared trade signal state (thread-safe)
# ─────────────────────────────────────────────────────────────────────────────

_signal_lock = threading.Lock()
_news_trade_signal: Optional[dict] = None  # {direction, confidence, reason, headline, expires_at}


def get_active_news_signal() -> Optional[dict]:
    """
    Returns the active news-driven trade signal if one exists and hasn't expired.
    Called by the strategy layer before entering a trade.

    Returns dict with keys: direction (BULLISH/BEARISH/NEUTRAL), confidence (0-1),
    reason (str), headline (str), source (str)
    — or None if no active signal.
    """
    from config import settings
    if not getattr(settings, "NEWS_TRADE_ENABLED", False):
        return None
    with _signal_lock:
        if _news_trade_signal is None:
            return None
        if datetime.now(ET) > _news_trade_signal.get("expires_at", datetime.now(ET)):
            return None
        return dict(_news_trade_signal)


def _set_news_trade_signal(direction: str, confidence: float,
                           reason: str, headline: str, source: str) -> None:
    global _news_trade_signal
    from config import settings
    expiry_min = getattr(settings, "NEWS_SIGNAL_EXPIRY_MINUTES", 30)
    with _signal_lock:
        _news_trade_signal = {
            "direction":  direction,
            "confidence": confidence,
            "reason":     reason,
            "headline":   headline,
            "source":     source,
            "expires_at": datetime.now(ET) + timedelta(minutes=expiry_min),
            "timestamp":  datetime.now(ET).strftime("%H:%M ET"),
        }
    logger.info(f"[NewsMonitor] Trade signal set: {direction} (conf={confidence:.2f}) — {headline[:60]}")


# ─────────────────────────────────────────────────────────────────────────────
# Shared halt state (thread-safe)
# ─────────────────────────────────────────────────────────────────────────────

_halt_lock = threading.Lock()
_halt_until: Optional[datetime] = None


def is_news_halt_active() -> bool:
    """
    Returns True if a HIGH-impact news event was detected recently and
    NEWS_HALT_ENABLED=true in settings. Safe to call from any thread.
    """
    from config import settings
    if not getattr(settings, "NEWS_HALT_ENABLED", False):
        return False
    with _halt_lock:
        if _halt_until is None:
            return False
        return datetime.now(ET) < _halt_until


def _set_halt(minutes: int) -> None:
    global _halt_until
    with _halt_lock:
        _halt_until = datetime.now(ET) + timedelta(minutes=minutes)
    logger.warning(f"[NewsMonitor] Trading halt set for {minutes} min due to breaking news")


# ─────────────────────────────────────────────────────────────────────────────
# RSS polling
# ─────────────────────────────────────────────────────────────────────────────

def _fetch_rss_headlines() -> list[dict]:
    """Fetch and parse all RSS feeds. Returns list of {source, headline, link}."""
    try:
        import feedparser
    except ImportError:
        logger.warning("[NewsMonitor] feedparser not installed — RSS disabled. Run: pip install feedparser")
        return []

    results = []
    for source, url in RSS_FEEDS:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:5]:  # top 5 per source
                headline = entry.get("title", "").strip()
                link = entry.get("link", "")
                if headline:
                    results.append({"source": source, "headline": headline, "link": link})
        except Exception as e:
            logger.debug(f"[NewsMonitor] RSS error ({source}): {e}")

    return results


# ─────────────────────────────────────────────────────────────────────────────
# Grok scan
# ─────────────────────────────────────────────────────────────────────────────

def _grok_news_scan() -> Optional[dict]:
    """Query Grok for breaking X/Twitter news. Returns None if nothing notable."""
    from config import settings
    api_key = getattr(settings, "XAI_API_KEY", "") or ""
    if not api_key:
        return None

    try:
        import openai
        client = openai.OpenAI(api_key=api_key, base_url="https://api.x.ai/v1")
        resp = client.chat.completions.create(
            model="grok-4.20-0309-reasoning",
            messages=[{"role": "user", "content": _GROK_NEWS_PROMPT}],
            temperature=0.1,
            max_tokens=200,
            timeout=12,
        )
        text = resp.choices[0].message.content or ""
        text = re.sub(r"```(?:json)?", "", text).strip()
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            data = json.loads(match.group())
            if data.get("impact", "NONE") != "NONE":
                return data
    except Exception as e:
        logger.debug(f"[NewsMonitor] Grok scan error: {e}")

    return None


# ─────────────────────────────────────────────────────────────────────────────
# NewsMonitor class
# ─────────────────────────────────────────────────────────────────────────────

class NewsMonitor:
    """
    Background news monitor. Polls RSS + Grok on configurable intervals.
    Sends Telegram alerts for HIGH/MEDIUM impact events.
    Sets trading halt flag for HIGH impact events when NEWS_HALT_ENABLED=true.
    """

    def __init__(self):
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._seen: dict[str, datetime] = {}  # hash -> first_seen (dedup TTL 6h)
        self._last_grok_scan = 0.0

    def start(self) -> None:
        """Start the background monitor thread."""
        from config import settings
        if not getattr(settings, "NEWS_MONITOR_ENABLED", False):
            logger.info("[NewsMonitor] Disabled (NEWS_MONITOR_ENABLED=false)")
            return

        self._thread = threading.Thread(
            target=self._loop,
            name="news-monitor",
            daemon=True,
        )
        self._thread.start()
        logger.info("[NewsMonitor] Started — RSS + Grok scanning active")

    def stop(self) -> None:
        self._stop_event.set()

    def _loop(self) -> None:
        from config import settings
        poll_interval = getattr(settings, "NEWS_POLL_INTERVAL_SECONDS", 120)
        grok_interval = getattr(settings, "NEWS_GROK_INTERVAL_SECONDS", 300)
        halt_minutes  = getattr(settings, "NEWS_HALT_MINUTES", 15)

        while not self._stop_event.is_set():
            try:
                self._purge_seen()

                # ── RSS scan (every poll cycle) ───────────────────────────
                headlines = _fetch_rss_headlines()
                for item in headlines:
                    h = item["headline"]
                    impact = _score_impact(h)
                    if impact in ("HIGH", "MEDIUM"):
                        self._handle_event(
                            source=item["source"],
                            headline=h,
                            summary="",
                            impact=impact,
                            assets="ES/MES",
                            link=item.get("link", ""),
                            halt_minutes=halt_minutes,
                        )

                # ── Grok scan (less frequent, costs API credits) ──────────
                now = time.time()
                if now - self._last_grok_scan >= grok_interval:
                    self._last_grok_scan = now
                    result = _grok_news_scan()
                    if result:
                        self._handle_event(
                            source="Grok/X",
                            headline=result.get("headline", "Breaking news detected"),
                            summary=result.get("summary", ""),
                            impact=result.get("impact", "MEDIUM"),
                            assets=result.get("assets", ""),
                            link="",
                            halt_minutes=halt_minutes,
                        )

            except Exception as e:
                logger.error(f"[NewsMonitor] Loop error: {e}")

            self._stop_event.wait(poll_interval)

    def _handle_event(
        self,
        source: str,
        headline: str,
        summary: str,
        impact: str,
        assets: str,
        link: str,
        halt_minutes: int,
    ) -> None:
        """Deduplicate, alert, and optionally halt trading."""
        h = _headline_hash(headline)
        if h in self._seen:
            return  # already alerted

        self._seen[h] = datetime.now(ET)
        logger.info(f"[NewsMonitor] {impact} | {source} | {headline}")

        # Send Telegram alert
        from monitor.alerts import notify_breaking_news
        notify_breaking_news(
            source=source,
            headline=headline,
            summary=summary,
            impact=impact,
            assets=assets,
            link=link,
        )

        # Set trading halt on HIGH impact
        if impact == "HIGH":
            _set_halt(halt_minutes)

        # Ask Grok to assess directional trade impact on MES
        from config import settings
        if getattr(settings, "NEWS_TRADE_ENABLED", False) and impact in ("HIGH", "MEDIUM"):
            assessment = _assess_trade_direction(headline)
            if assessment:
                direction   = assessment.get("direction", "NEUTRAL")
                confidence  = float(assessment.get("confidence", 0.0))
                reason      = assessment.get("reason", "")
                min_conf    = getattr(settings, "NEWS_TRADE_CONFIDENCE_MIN", 0.70)

                if direction != "NEUTRAL" and confidence >= min_conf:
                    _set_news_trade_signal(direction, confidence, reason, headline, source)
                    from monitor.alerts import notify_news_trade_signal
                    notify_news_trade_signal(direction, confidence, reason, headline, source)

    def _purge_seen(self) -> None:
        """Remove entries older than 6 hours to prevent set from growing forever."""
        cutoff = datetime.now(ET) - timedelta(hours=6)
        stale = [k for k, v in self._seen.items() if v < cutoff]
        for k in stale:
            del self._seen[k]
