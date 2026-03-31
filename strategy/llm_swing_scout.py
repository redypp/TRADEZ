"""
llm_swing_scout.py
──────────────────
Proactive LLM-driven swing opportunity scanner.

Rather than only filtering existing technical signals, this module asks the
LLMs to independently identify US stocks worth going long as swings — based
on catalysts, sector momentum, earnings setups, macro tailwinds, and news.

Pipeline:
    1. Grok   — scans X/Twitter + news for catalyst-driven stock ideas
    2. GPT-4  — scores each idea on technicals + risk/reward
    3. Claude — ranks ideas, assigns conviction tiers, writes thesis per trade

Results are stored in SQLite (bot_state "swing_scout") and surfaced in the
AI Screener tab as "LLM Ideas" alongside the technical screener setups.

Called by:
    - scheduler EOD swing scan (run_eod_swing_scan)
    - web/api.py GET /api/swing/llm-ideas (10-min cache)
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import datetime, timezone

import pytz

logger = logging.getLogger(__name__)

ET = pytz.timezone("America/New_York")

# ─── Prompts ──────────────────────────────────────────────────────────────────

_GROK_SWING_PROMPT = """\
You are a swing trading intelligence analyst with access to live X/Twitter and news feeds.

Today's date: {today}
Market context: VIX={vix}, SPY trend={spy_trend}, sector leaders={sector_leaders}

Your job: identify 3-5 specific US stocks that look compelling for a LONG swing trade \
(hold days to weeks). Focus on:
- Stocks with upcoming catalysts (earnings in 2-4 weeks, product launches, FDA dates, contract wins)
- Sector momentum plays (which sectors are rotating into right now?)
- Stocks with unusual options activity or institutional accumulation signals
- Names where social sentiment is building but price hasn't fully moved yet
- Post-earnings runners with clean breakout structure
- Avoid anything with VIX > 35 conditions or broad market breakdown risk

For each idea, be specific. Tickers only from liquid US stocks (>1M avg daily volume).

Respond in JSON:
{{"ideas": [{{"symbol": "TICKER", "catalyst": "<specific catalyst — earnings date, event, etc>", \
"thesis": "<one sentence — why now, why long>", "sector": "<sector>", \
"urgency": "HIGH|MEDIUM|LOW", "source": "<news/options/sentiment/technical>"}}], \
"market_bias": "RISK_ON|RISK_OFF|NEUTRAL", "avoid_sectors": ["<sector1>"]}}"""


_GPT4_SWING_PROMPT = """\
You are a quantitative analyst scoring swing trade ideas for a systematic trading bot.

Market context: VIX={vix}, DXY={dxy}, 10Y yield={yield_10y}%
Today: {today}

The following stock ideas were generated from news/sentiment analysis:
{ideas_json}

For each symbol, assess:
1. Does the current macro environment (VIX, rates, dollar) support a LONG swing trade?
2. Rate the risk/reward as HIGH / MEDIUM / LOW
3. Suggest a rough entry zone (near current price or a key level)
4. What's the key risk that could invalidate this trade?

Be concise. Use null for fields you can't assess without live price data.

Respond in JSON:
{{"scored": [{{"symbol": "TICKER", "rr_rating": "HIGH|MEDIUM|LOW", \
"macro_ok": true|false, "entry_note": "<brief level note>", \
"key_risk": "<one risk>", "conviction": <0.0-1.0>}}]}}"""


_CLAUDE_SWING_PROMPT = """\
You are the final decision layer for a swing trading bot's LLM pipeline.

Today: {today}
VIX: {vix} | Market bias: {market_bias}

Grok identified these opportunities from news/sentiment:
{grok_ideas_json}

GPT-4 scored them on macro/technicals:
{gpt4_scored_json}

Your job:
1. Combine both analyses and rank the top 3 ideas by overall conviction
2. For each, write a sharp 1-sentence thesis the bot can use to explain the trade
3. Flag any ideas that should be rejected (poor macro, too risky, unclear catalyst)
4. Assign a final confidence score (0.0-1.0) per idea

Only include ideas where confidence >= 0.60. Be selective — 1 great idea beats 5 mediocre ones.
A "calculated risk" means: clear catalyst, defined stop (prior structure), asymmetric upside.

Respond in JSON:
{{"top_ideas": [{{"symbol": "TICKER", "thesis": "<sharp one sentence>", \
"confidence": <0.0-1.0>, "catalyst": "<specific catalyst>", \
"entry_note": "<entry context>", "key_risk": "<main risk>", \
"conviction_tier": "HIGH|MEDIUM"}}], \
"rejected": ["TICKER1", "TICKER2"], \
"market_note": "<one sentence on overall swing environment right now>"}}"""


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _parse_json(text: str) -> dict:
    if not text:
        return {}
    text = re.sub(r"```(?:json)?", "", text).strip().strip("`")
    try:
        return json.loads(text)
    except Exception:
        m = re.search(r"\{[\s\S]*\}", text)
        if m:
            try:
                return json.loads(m.group())
            except Exception:
                pass
    return {}


async def _query_grok_swing(vix: float, spy_trend: str, sector_leaders: str) -> dict:
    try:
        from config import settings as s
        if not getattr(s, "GROK_API_KEY", ""):
            return {"ideas": [], "market_bias": "NEUTRAL", "avoid_sectors": []}

        from openai import AsyncOpenAI
        client = AsyncOpenAI(
            api_key=s.GROK_API_KEY,
            base_url="https://api.x.ai/v1",
        )
        prompt = _GROK_SWING_PROMPT.format(
            today=datetime.now(ET).strftime("%A %B %d, %Y"),
            vix=round(vix, 1),
            spy_trend=spy_trend,
            sector_leaders=sector_leaders,
        )
        resp = await asyncio.wait_for(
            client.chat.completions.create(
                model="grok-3-mini",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.4,
                max_tokens=800,
            ),
            timeout=20.0,
        )
        result = _parse_json(resp.choices[0].message.content or "")
        logger.info(f"[SwingScout/Grok] {len(result.get('ideas', []))} ideas found")
        return result
    except Exception as e:
        logger.warning(f"[SwingScout] Grok failed: {e}")
        return {"ideas": [], "market_bias": "NEUTRAL", "avoid_sectors": []}


async def _query_gpt4_swing(ideas: list, vix: float, dxy: float, yield_10y: float) -> dict:
    try:
        from config import settings as s
        if not getattr(s, "OPENAI_API_KEY", "") or not ideas:
            return {"scored": []}

        from openai import AsyncOpenAI
        client = AsyncOpenAI(api_key=s.OPENAI_API_KEY)
        prompt = _GPT4_SWING_PROMPT.format(
            vix=round(vix, 1),
            dxy=round(dxy, 2) if dxy else "n/a",
            yield_10y=round(yield_10y, 3) if yield_10y else "n/a",
            today=datetime.now(ET).strftime("%B %d, %Y"),
            ideas_json=json.dumps(ideas, indent=2),
        )
        resp = await asyncio.wait_for(
            client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2,
                max_tokens=600,
            ),
            timeout=15.0,
        )
        result = _parse_json(resp.choices[0].message.content or "")
        logger.info(f"[SwingScout/GPT-4] scored {len(result.get('scored', []))} ideas")
        return result
    except Exception as e:
        logger.warning(f"[SwingScout] GPT-4 failed: {e}")
        return {"scored": []}


async def _query_claude_swing(grok_out: dict, gpt4_out: dict, vix: float) -> dict:
    try:
        from config import settings as s
        if not getattr(s, "ANTHROPIC_API_KEY", ""):
            return {"top_ideas": [], "rejected": [], "market_note": ""}

        import anthropic
        client = anthropic.AsyncAnthropic(api_key=s.ANTHROPIC_API_KEY)
        prompt = _CLAUDE_SWING_PROMPT.format(
            today=datetime.now(ET).strftime("%B %d, %Y"),
            vix=round(vix, 1),
            market_bias=grok_out.get("market_bias", "NEUTRAL"),
            grok_ideas_json=json.dumps(grok_out.get("ideas", []), indent=2),
            gpt4_scored_json=json.dumps(gpt4_out.get("scored", []), indent=2),
        )
        resp = await asyncio.wait_for(
            client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=700,
                messages=[{"role": "user", "content": prompt}],
            ),
            timeout=20.0,
        )
        result = _parse_json(resp.content[0].text if resp.content else "")
        logger.info(f"[SwingScout/Claude] {len(result.get('top_ideas', []))} top ideas ranked")
        return result
    except Exception as e:
        logger.warning(f"[SwingScout] Claude failed: {e}")
        return {"top_ideas": [], "rejected": [], "market_note": ""}


# ─── Public API ───────────────────────────────────────────────────────────────

async def _async_scan(market_data: dict) -> dict:
    """
    Run the full 3-LLM swing scout pipeline.
    Returns a dict ready to be stored in bot_state["swing_scout"].
    """
    vix       = float(market_data.get("vix") or 18.0)
    dxy       = float(market_data.get("dxy") or 104.0)
    yield_10y = float(market_data.get("yield_10y") or 4.3)

    # Infer rough SPY trend from VIX level
    spy_trend = "uptrend" if vix < 20 else "choppy" if vix < 28 else "downtrend/caution"
    sector_leaders = "tech, energy, financials"  # could be dynamic later

    # Grok + GPT-4 in parallel, Claude synthesizes
    grok_out, gpt4_out = await asyncio.gather(
        _query_grok_swing(vix, spy_trend, sector_leaders),
        asyncio.sleep(0),  # placeholder so gather works even if grok is fast
    )
    # Now score Grok ideas through GPT-4
    gpt4_out = await _query_gpt4_swing(grok_out.get("ideas", []), vix, dxy, yield_10y)
    claude_out = await _query_claude_swing(grok_out, gpt4_out, vix)

    return {
        "top_ideas":    claude_out.get("top_ideas", []),
        "rejected":     claude_out.get("rejected", []),
        "market_note":  claude_out.get("market_note", ""),
        "market_bias":  grok_out.get("market_bias", "NEUTRAL"),
        "avoid_sectors": grok_out.get("avoid_sectors", []),
        "timestamp":    datetime.now(ET).strftime("%H:%M ET"),
        "vix":          vix,
    }


def run_swing_scout(market_data: dict) -> dict:
    """Synchronous wrapper — call from scheduler or API."""
    try:
        return asyncio.run(_async_scan(market_data))
    except Exception as e:
        logger.error(f"[SwingScout] pipeline failed: {e}")
        return {"top_ideas": [], "market_note": "", "timestamp": "", "error": str(e)}
