"""
strategy/llm_advisory.py

Multi-LLM Advisory Engine — runs in a background thread alongside the algo.
The algo trades as normal. This generates human-readable market intelligence
for the trader, displayed on the dashboard and sent via Telegram.

Architecture (Specialist Routing):
    Grok   → real-time X/Twitter sentiment + breaking news
    GPT-4  → macro/quant context + signal quality assessment
    Claude → synthesizes into a clean brief for the human trader

Output:
    {
        "headline":       str,           # one-liner for Telegram subject
        "sentiment":      "BULLISH" | "BEARISH" | "NEUTRAL",
        "signal_quality": "HIGH" | "MEDIUM" | "LOW" | "N/A",
        "risk_flags":     [str, ...],    # warnings worth knowing
        "grok_summary":   str,
        "gpt4_summary":   str,
        "brief":          str,           # 2-3 sentence plain-English summary
        "timestamp":      str,
        "trigger":        "SIGNAL" | "HOURLY" | "PRE_MARKET",
    }

This module NEVER touches execution. It is purely informational.
"""

import asyncio
import json
import logging
import re
from datetime import datetime
from typing import Any

import pytz

logger = logging.getLogger(__name__)

ET = pytz.timezone("America/New_York")

TIMEOUT_GROK   = 10.0
TIMEOUT_GPT4   = 10.0
TIMEOUT_CLAUDE = 12.0

CLAUDE_MODEL = "claude-haiku-4-5-20251001"
GPT4_MODEL   = "gpt-4o-mini"
GROK_MODEL   = "grok-3-mini"


# ─────────────────────────────────────────────────────────────────────────────
# Prompts
# ─────────────────────────────────────────────────────────────────────────────

_GROK_PROMPT = """\
You are a real-time market intelligence analyst for a human futures trader watching MES (S&P 500 micro futures).

Current market snapshot:
{context_json}

Using your live X/Twitter access and news knowledge, answer these questions for the trader:
1. What's the current social sentiment on ES/SPY/S&P 500? (BULLISH / BEARISH / NEUTRAL)
2. Any breaking macro events, Fed speakers, or major news in the last 2 hours or next 2 hours?
3. Anything unusual — large options flows, whale activity, unusual volume, fear/greed extremes?

Keep it factual and concise. The trader needs actionable context, not generic commentary.

Respond in JSON:
{{"sentiment": "BULLISH|BEARISH|NEUTRAL", "risk_events": "none|<what and when>", "unusual": "none|<brief>", "summary": "<2 sentences max — what should the trader know right now>"}}"""

_GPT4_PROMPT = """\
You are a quantitative market analyst advising a human trader on MES (Micro E-mini S&P 500) futures.

Current market data:
{context_json}

The algo has produced: strategy={strategy_id}, signal={signal_direction}

Assess the current setup for the trader:
1. Does the macro environment (VIX={vix}, yields, DXY={dxy}) support or work against this signal?
2. How strong is this setup? (HIGH / MEDIUM / LOW quality)
3. What should the trader be watching in the next hour?

Be direct. The trader can see the charts — give them context they can't easily quantify.

Respond in JSON:
{{"signal_quality": "HIGH|MEDIUM|LOW|N/A", "macro_supports": true|false, "watch_for": "<1 sentence>", "summary": "<2 sentences — what the quant data says about this setup>"}}"""

_CLAUDE_BRIEF_PROMPT = """\
You are an AI co-pilot helping a human trader interpret their automated MES futures trading bot.

The algo ({strategy_id}, {signal_direction}) just ran. Here's the full picture:

GROK (real-time sentiment/news):
{grok_json}

GPT-4 (macro/quant analysis):
{gpt4_json}

Market snapshot:
{context_json}

Write a concise 2-3 sentence advisory brief for the trader. Be direct and useful:
- Does the market context support or conflict with what the algo is doing?
- Any specific thing the trader should watch or be cautious about?
- If no trade was taken (FLAT), why does that look right or wrong?

Do NOT tell the trader what to do with execution — the algo handles that.
Write in plain English, no jargon overload. Think: smart friend with market knowledge.

Also extract:
- A one-line headline (under 60 chars)
- Any risk flags worth a ⚠️ (0-3 max, only real ones)

Respond in JSON:
{{"headline": "<60 chars>", "brief": "<2-3 sentences>", "risk_flags": ["<flag1>", "<flag2>"]}}"""


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _parse_json(text: str) -> dict:
    if not text:
        return {}
    text = re.sub(r"```(?:json)?", "", text).strip()
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass
    return {}


def _build_context(market_data: dict) -> dict:
    close = market_data.get("close", 0) or 0
    ema20 = market_data.get("ema20", 0) or 0
    vwap  = market_data.get("vwap", 0) or 0

    return {
        "symbol":         "MES (Micro E-mini S&P 500)",
        "timestamp":      datetime.now(ET).strftime("%Y-%m-%d %H:%M ET"),
        "session_hour":   market_data.get("session_hour"),
        "close":          round(close, 2),
        "close_vs_ema20": "ABOVE" if close > ema20 else "BELOW",
        "close_vs_vwap":  "ABOVE" if close > vwap else "BELOW",
        "adx":            round(market_data.get("adx", 0) or 0, 1),
        "rsi":            round(market_data.get("rsi", 0) or 0, 1),
        "atr":            round(market_data.get("atr", 0) or 0, 2),
        "vix":            market_data.get("vix"),
        "yield_10y":      market_data.get("yield_10y"),
        "dxy":            market_data.get("dxy"),
        "spy_vol_ratio":  round(market_data.get("spy_vol_ratio", 1.0) or 1.0, 2),
        "regime":         market_data.get("regime", "NORMAL"),
        "vpoc_migration": market_data.get("vpoc_migration", "NEUTRAL"),
        "headwinds":      market_data.get("headwinds", []),
        "tailwinds":      market_data.get("tailwinds", []),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Async model queries
# ─────────────────────────────────────────────────────────────────────────────

async def _query_grok(context_json: str) -> dict:
    from config import settings
    _default = {"sentiment": "NEUTRAL", "risk_events": "none", "unusual": "none",
                "summary": "Grok not available"}

    api_key = getattr(settings, "XAI_API_KEY", "") or ""
    if not api_key:
        return {**_default, "summary": "Grok not configured"}

    try:
        import openai
        client = openai.AsyncOpenAI(api_key=api_key, base_url="https://api.x.ai/v1")
        prompt = _GROK_PROMPT.format(context_json=context_json)
        resp = await asyncio.wait_for(
            client.chat.completions.create(
                model=GROK_MODEL,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2,
                max_tokens=300,
            ),
            timeout=TIMEOUT_GROK,
        )
        result = _parse_json(resp.choices[0].message.content or "")
        if result:
            logger.info(f"[Advisory/Grok] sentiment={result.get('sentiment')} events={result.get('risk_events')}")
            return result
        return {**_default, "summary": "Grok returned unparseable response"}
    except asyncio.TimeoutError:
        logger.warning("[Advisory] Grok timed out")
        return {**_default, "summary": "Grok timed out"}
    except Exception as e:
        logger.warning(f"[Advisory] Grok failed: {e}")
        return {**_default, "summary": f"Grok unavailable"}


async def _query_gpt4(context_json: str, context: dict,
                      strategy_id: str, signal_direction: str) -> dict:
    from config import settings
    _default = {"signal_quality": "N/A", "macro_supports": None,
                "watch_for": "n/a", "summary": "GPT-4 not available"}

    api_key = getattr(settings, "OPENAI_API_KEY", "") or ""
    if not api_key:
        return {**_default, "summary": "GPT-4 not configured"}

    try:
        import openai
        client = openai.AsyncOpenAI(api_key=api_key)
        prompt = _GPT4_PROMPT.format(
            context_json=context_json,
            strategy_id=strategy_id,
            signal_direction=signal_direction,
            vix=context.get("vix", "?"),
            dxy=context.get("dxy", "?"),
        )
        resp = await asyncio.wait_for(
            client.chat.completions.create(
                model=GPT4_MODEL,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2,
                max_tokens=300,
            ),
            timeout=TIMEOUT_GPT4,
        )
        result = _parse_json(resp.choices[0].message.content or "")
        if result:
            logger.info(f"[Advisory/GPT-4] quality={result.get('signal_quality')} macro_ok={result.get('macro_supports')}")
            return result
        return {**_default, "summary": "GPT-4 returned unparseable response"}
    except asyncio.TimeoutError:
        logger.warning("[Advisory] GPT-4 timed out")
        return {**_default, "summary": "GPT-4 timed out"}
    except Exception as e:
        logger.warning(f"[Advisory] GPT-4 failed: {e}")
        return {**_default, "summary": "GPT-4 unavailable"}


async def _query_claude_brief(context_json: str, grok_out: dict, gpt4_out: dict,
                               strategy_id: str, signal_direction: str) -> dict:
    from config import settings
    _default = {"headline": "AI Advisory unavailable",
                "brief": "Claude not configured — add ANTHROPIC_API_KEY to .env",
                "risk_flags": []}

    api_key = getattr(settings, "ANTHROPIC_API_KEY", "") or ""
    if not api_key:
        return {**_default, "brief": "Claude not configured"}

    try:
        import anthropic
        client = anthropic.AsyncAnthropic(api_key=api_key)
        prompt = _CLAUDE_BRIEF_PROMPT.format(
            strategy_id=strategy_id,
            signal_direction=signal_direction,
            grok_json=json.dumps(grok_out, indent=2),
            gpt4_json=json.dumps(gpt4_out, indent=2),
            context_json=context_json,
        )
        resp = await asyncio.wait_for(
            client.messages.create(
                model=CLAUDE_MODEL,
                max_tokens=300,
                temperature=0.3,
                messages=[{"role": "user", "content": prompt}],
            ),
            timeout=TIMEOUT_CLAUDE,
        )
        content = resp.content[0].text if resp.content else ""
        result = _parse_json(content)
        if result:
            logger.info(f"[Advisory/Claude] headline={result.get('headline')}")
            return result
        return {**_default, "brief": "Claude returned unparseable response"}
    except asyncio.TimeoutError:
        logger.warning("[Advisory] Claude timed out")
        return {**_default, "brief": "Claude timed out"}
    except Exception as e:
        logger.warning(f"[Advisory] Claude failed: {e}")
        return {**_default, "brief": "Claude unavailable"}


# ─────────────────────────────────────────────────────────────────────────────
# Async pipeline
# ─────────────────────────────────────────────────────────────────────────────

async def _async_get_advisory(market_data: dict, strategy_id: str,
                               signal_direction: str, trigger: str) -> dict:
    context     = _build_context(market_data)
    context_json = json.dumps(context, indent=2)

    # Grok + GPT-4 in parallel
    grok_out, gpt4_out = await asyncio.gather(
        _query_grok(context_json),
        _query_gpt4(context_json, context, strategy_id, signal_direction),
    )

    # Claude synthesizes into a human brief
    claude_out = await _query_claude_brief(
        context_json, grok_out, gpt4_out, strategy_id, signal_direction
    )

    return {
        "headline":       claude_out.get("headline", f"{strategy_id} — {signal_direction}"),
        "sentiment":      grok_out.get("sentiment", "NEUTRAL"),
        "signal_quality": gpt4_out.get("signal_quality", "N/A"),
        "risk_flags":     claude_out.get("risk_flags", []),
        "grok_summary":   grok_out.get("summary", ""),
        "gpt4_summary":   gpt4_out.get("summary", ""),
        "watch_for":      gpt4_out.get("watch_for", ""),
        "brief":          claude_out.get("brief", ""),
        "risk_events":    grok_out.get("risk_events", "none"),
        "unusual":        grok_out.get("unusual", "none"),
        "macro_supports": gpt4_out.get("macro_supports"),
        "timestamp":      datetime.now(ET).strftime("%H:%M ET"),
        "trigger":        trigger,
        "strategy_id":    strategy_id,
        "signal":         signal_direction,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Public synchronous API
# ─────────────────────────────────────────────────────────────────────────────

def get_advisory(
    market_data:      dict,
    strategy_id:      str  = "FLAT",
    signal_direction: str  = "FLAT",
    trigger:          str  = "HOURLY",
) -> dict:
    """
    Synchronous wrapper — safe to call from a background thread.

    Args:
        market_data:      dict of live market indicators (same as llm_selector)
        strategy_id:      what the algo chose (BRT / ORB / FLAT)
        signal_direction: LONG / SHORT / FLAT
        trigger:          why this was called (SIGNAL / HOURLY / PRE_MARKET)

    Returns:
        Advisory dict — always returns, never raises.
    """
    try:
        return asyncio.run(_async_get_advisory(market_data, strategy_id,
                                               signal_direction, trigger))
    except RuntimeError:
        try:
            loop = asyncio.get_event_loop()
            return loop.run_until_complete(
                _async_get_advisory(market_data, strategy_id, signal_direction, trigger)
            )
        except Exception as e:
            logger.error(f"[Advisory] Async error: {e}")
    except Exception as e:
        logger.error(f"[Advisory] Failed: {e}")

    return {
        "headline":       "AI Advisory unavailable",
        "sentiment":      "NEUTRAL",
        "signal_quality": "N/A",
        "risk_flags":     [],
        "grok_summary":   "",
        "gpt4_summary":   "",
        "watch_for":      "",
        "brief":          "Advisory models unavailable. Check API keys in .env.",
        "risk_events":    "none",
        "unusual":        "none",
        "macro_supports": None,
        "timestamp":      datetime.now(ET).strftime("%H:%M ET"),
        "trigger":        trigger,
        "strategy_id":    strategy_id,
        "signal":         signal_direction,
    }
