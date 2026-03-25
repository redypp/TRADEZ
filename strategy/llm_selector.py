"""
strategy/llm_selector.py

Multi-LLM Strategy Selector — queries Claude, GPT-4, and Grok in parallel
to determine which trading strategy has edge in the current market environment.

Architecture (Specialist Routing):
    Grok   → real-time X/Twitter sentiment + breaking news (xAI Live Search)
    GPT-4  → macro/quantitative analysis (yields, DXY, vol regime)
    Claude → orchestrator: receives all specialist inputs + makes final call

Flow:
    1. Grok + GPT-4 run in parallel (asyncio.gather)
    2. Their outputs are fed into Claude as context
    3. Claude returns the final structured strategy recommendation

Output schema:
    {
        "strategy":   "BRT" | "ORB" | "VWAP_MR" | "FLAT",
        "bias":       "LONG" | "SHORT" | "NEUTRAL",
        "confidence": 0.0–1.0,
        "reasoning":  str,
        "votes": {
            "grok":   {"sentiment": ..., "risk_events": ..., "summary": ...},
            "gpt4":   {"strategy": ..., "bias": ..., "confidence": ..., "reasoning": ...},
            "claude": {"strategy": ..., "bias": ..., "confidence": ..., "reasoning": ...},
        },
        "source": "ensemble" | "fallback",
    }

Fallback behaviour:
    - If a model key is missing → that model is skipped gracefully
    - If a model times out or errors → default neutral response is used
    - If ALL models fail → returns FLAT with source="fallback"
    - LLM_SELECTOR_ENABLED=false → never called (gated in scheduler)
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

# ── Available strategies ───────────────────────────────────────────────────────
STRATEGY_OPTIONS = ["BRT", "ORB", "VWAP_MR", "FLAT"]

# ── Model IDs ─────────────────────────────────────────────────────────────────
CLAUDE_MODEL = "claude-haiku-4-5-20251001"   # fast + cheap orchestrator
GPT4_MODEL   = "gpt-4o-mini"                  # fast + cheap macro analyst
GROK_MODEL   = "grok-3-mini"                  # fast + X/live search access

# ── LLM call timeouts (seconds) ───────────────────────────────────────────────
TIMEOUT_GROK   = 10.0
TIMEOUT_GPT4   = 10.0
TIMEOUT_CLAUDE = 12.0

# ─────────────────────────────────────────────────────────────────────────────
# Prompts
# ─────────────────────────────────────────────────────────────────────────────

_GROK_PROMPT = """\
You are a real-time market sentiment analyst for ES/S&P 500 futures trading.
Use your live X/Twitter feed access and current news knowledge to assess the market NOW.

Current market snapshot:
{context_json}

Answer these three questions based on real-time data:
1. What is the current social/news sentiment for ES/SPY/S&P 500? (BULLISH / BEARISH / NEUTRAL)
2. Are there any breaking macro events, Fed speakers, or data releases in the next 2 hours?
3. Is there any unusual options flow, large block trades, or institutional positioning signals visible?

Respond ONLY in valid JSON, no extra text:
{{"sentiment": "BULLISH|BEARISH|NEUTRAL", "risk_events": "none|<brief description>", "unusual_activity": "none|<brief description>", "summary": "<2 sentences max>"}}"""

_GPT4_PROMPT = """\
You are a quantitative macro analyst for intraday CME micro-futures trading (MES/ES).

Current market snapshot:
{context_json}

Based ONLY on the quantitative data provided, assess:
1. Does the macro regime (VIX={vix}, yields trending, DXY={dxy}) support trend-following or mean-reversion?
2. Given ADX={adx} and RSI={rsi}, is the market trending (BRT/ORB) or ranging (VWAP_MR)?
3. Is the MES directional bias LONG, SHORT, or NEUTRAL right now?

Available strategies:
- BRT: Break & Retest momentum — needs ADX > 20, trending market
- ORB: Opening Range Breakout — best in first 2 hours of NY session
- VWAP_MR: VWAP Mean Reversion — best when ADX < 20, choppy conditions
- FLAT: No trade — high uncertainty, conflicting signals, or VIX too elevated

Respond ONLY in valid JSON, no extra text:
{{"strategy": "BRT|ORB|VWAP_MR|FLAT", "bias": "LONG|SHORT|NEUTRAL", "confidence": 0.55-0.95, "reasoning": "<2 sentences max>"}}"""

_CLAUDE_ORCHESTRATOR_PROMPT = """\
You are the strategy orchestrator for an automated MES (Micro E-mini S&P 500) futures trading bot.

You have received analysis from two specialist models:

GROK (real-time sentiment/news):
{grok_output}

GPT-4 (macro/quantitative analysis):
{gpt4_output}

Current technical market data:
{context_json}

Available strategies:
- BRT: Break & Retest — needs ADX > 20, trending, price at institutional level after break
- ORB: Opening Range Breakout — best in session hours 10-12 ET with directional momentum
- VWAP_MR: VWAP Mean Reversion — best when ADX < 20, price stretched from VWAP
- FLAT: No trade — uncertainty, conflict, or risk too high

Decision rules (hard gates — override your analysis if triggered):
- regime is NO_TRADE or VIX > 40 → FLAT
- Grok sentiment is BEARISH and bias would be LONG (MES is long-only) → FLAT
- ADX < 18 → avoid BRT and ORB; prefer VWAP_MR or FLAT
- risk_events contain Fed/FOMC/CPI/NFP → reduce confidence, lean FLAT
- If confidence < 0.55 → output FLAT regardless of strategy preference

Synthesize all inputs and output ONE final strategy recommendation.

Respond ONLY in valid JSON, no extra text:
{{"strategy": "BRT|ORB|VWAP_MR|FLAT", "bias": "LONG|SHORT|NEUTRAL", "confidence": 0.0-1.0, "reasoning": "<2 sentences max>"}}"""


# ─────────────────────────────────────────────────────────────────────────────
# Context builder
# ─────────────────────────────────────────────────────────────────────────────

def _build_context(market_data: dict) -> dict:
    """Convert raw market_data into a clean, LLM-readable context dict."""
    close = market_data.get("close", 0) or 0
    ema20 = market_data.get("ema20", 0) or 0
    vwap  = market_data.get("vwap", 0) or 0
    adx   = market_data.get("adx", 0) or 0
    rsi   = market_data.get("rsi", 0) or 0

    return {
        "symbol":         "MES (Micro E-mini S&P 500)",
        "timestamp":      datetime.now(ET).strftime("%Y-%m-%d %H:%M ET"),
        "session_hour":   market_data.get("session_hour"),
        # Price action
        "close":          round(close, 2),
        "close_vs_ema20": "ABOVE" if close > ema20 else "BELOW",
        "close_vs_vwap":  "ABOVE" if close > vwap  else "BELOW",
        # Indicators
        "adx":            round(adx, 1),
        "rsi":            round(rsi, 1),
        "atr":            round(market_data.get("atr", 0) or 0, 2),
        # Fundamentals
        "vix":            market_data.get("vix"),
        "yield_10y":      market_data.get("yield_10y"),
        "dxy":            market_data.get("dxy"),
        "spy_vol_ratio":  round(market_data.get("spy_vol_ratio", 1.0) or 1.0, 2),
        # Regime
        "regime":         market_data.get("regime", "NORMAL"),
        "vpoc_migration": market_data.get("vpoc_migration", "NEUTRAL"),
        # Technical signals (from rule-based engine)
        "brt_signal_active": market_data.get("brt_signal", 0) != 0,
        "orb_signal_active": market_data.get("orb_signal", 0) != 0,
        # Macro context
        "headwinds":      market_data.get("headwinds", []),
        "tailwinds":      market_data.get("tailwinds", []),
        "long_only":      True,
    }


# ─────────────────────────────────────────────────────────────────────────────
# JSON parsing helper
# ─────────────────────────────────────────────────────────────────────────────

def _parse_json(text: str) -> dict:
    """
    Robustly extract a JSON object from an LLM response.
    Handles markdown code fences, extra prose, etc.
    """
    if not text:
        return {}
    # Strip markdown fences
    text = re.sub(r"```(?:json)?", "", text).strip()
    # Find first { ... } block
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass
    return {}


# ─────────────────────────────────────────────────────────────────────────────
# Async LLM query functions
# ─────────────────────────────────────────────────────────────────────────────

async def _query_grok(context_json: str) -> dict:
    """Query Grok (xAI) for real-time X/news sentiment."""
    from config import settings

    _default = {
        "sentiment": "NEUTRAL",
        "risk_events": "none",
        "unusual_activity": "none",
        "summary": "Grok not available",
    }

    api_key = getattr(settings, "XAI_API_KEY", "") or ""
    if not api_key:
        logger.debug("Grok skipped — XAI_API_KEY not configured")
        return {**_default, "summary": "Grok not configured (no XAI_API_KEY)"}

    try:
        import openai  # xAI uses OpenAI-compatible SDK
        client = openai.AsyncOpenAI(
            api_key=api_key,
            base_url="https://api.x.ai/v1",
        )
        prompt = _GROK_PROMPT.format(context_json=context_json)
        response = await asyncio.wait_for(
            client.chat.completions.create(
                model=GROK_MODEL,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
                max_tokens=250,
            ),
            timeout=TIMEOUT_GROK,
        )
        result = _parse_json(response.choices[0].message.content or "")
        if not result:
            return {**_default, "summary": "Grok returned unparseable response"}
        logger.info(f"[LLM/Grok] sentiment={result.get('sentiment')} events={result.get('risk_events')}")
        return result

    except asyncio.TimeoutError:
        logger.warning("Grok query timed out")
        return {**_default, "summary": "Grok timed out"}
    except ImportError:
        logger.warning("openai package not installed — Grok unavailable")
        return {**_default, "summary": "openai package missing"}
    except Exception as e:
        logger.warning(f"Grok query failed: {e}")
        return {**_default, "summary": f"Grok error: {e}"}


async def _query_gpt4(context_json: str, context: dict) -> dict:
    """Query GPT-4o-mini for macro/quantitative analysis."""
    from config import settings

    _default = {
        "strategy": "FLAT",
        "bias": "NEUTRAL",
        "confidence": 0.0,
        "reasoning": "GPT-4 not available",
    }

    api_key = getattr(settings, "OPENAI_API_KEY", "") or ""
    if not api_key:
        logger.debug("GPT-4 skipped — OPENAI_API_KEY not configured")
        return {**_default, "reasoning": "GPT-4 not configured (no OPENAI_API_KEY)"}

    try:
        import openai
        client = openai.AsyncOpenAI(api_key=api_key)
        prompt = _GPT4_PROMPT.format(
            context_json=context_json,
            vix=context.get("vix", "?"),
            dxy=context.get("dxy", "?"),
            adx=context.get("adx", "?"),
            rsi=context.get("rsi", "?"),
        )
        response = await asyncio.wait_for(
            client.chat.completions.create(
                model=GPT4_MODEL,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
                max_tokens=200,
            ),
            timeout=TIMEOUT_GPT4,
        )
        result = _parse_json(response.choices[0].message.content or "")
        if not result:
            return {**_default, "reasoning": "GPT-4 returned unparseable response"}
        # Clamp confidence to valid range
        result["confidence"] = max(0.0, min(1.0, float(result.get("confidence", 0.5))))
        logger.info(
            f"[LLM/GPT-4] strategy={result.get('strategy')} "
            f"bias={result.get('bias')} conf={result.get('confidence', 0):.2f}"
        )
        return result

    except asyncio.TimeoutError:
        logger.warning("GPT-4 query timed out")
        return {**_default, "reasoning": "GPT-4 timed out"}
    except ImportError:
        logger.warning("openai package not installed — GPT-4 unavailable")
        return {**_default, "reasoning": "openai package missing"}
    except Exception as e:
        logger.warning(f"GPT-4 query failed: {e}")
        return {**_default, "reasoning": f"GPT-4 error: {e}"}


async def _query_claude(context_json: str, grok_out: dict, gpt4_out: dict) -> dict:
    """Query Claude as the final orchestrating decision-maker."""
    from config import settings

    _default = {
        "strategy": "FLAT",
        "bias": "NEUTRAL",
        "confidence": 0.0,
        "reasoning": "Claude orchestrator not available",
    }

    api_key = getattr(settings, "ANTHROPIC_API_KEY", "") or ""
    if not api_key:
        logger.debug("Claude skipped — ANTHROPIC_API_KEY not configured")
        return {**_default, "reasoning": "Claude not configured (no ANTHROPIC_API_KEY)"}

    try:
        import anthropic
        client = anthropic.AsyncAnthropic(api_key=api_key)
        prompt = _CLAUDE_ORCHESTRATOR_PROMPT.format(
            context_json=context_json,
            grok_output=json.dumps(grok_out, indent=2),
            gpt4_output=json.dumps(gpt4_out, indent=2),
        )
        response = await asyncio.wait_for(
            client.messages.create(
                model=CLAUDE_MODEL,
                max_tokens=200,
                temperature=0.1,
                messages=[{"role": "user", "content": prompt}],
            ),
            timeout=TIMEOUT_CLAUDE,
        )
        content = response.content[0].text if response.content else ""
        result = _parse_json(content)
        if not result:
            return {**_default, "reasoning": "Claude returned unparseable response"}
        result["confidence"] = max(0.0, min(1.0, float(result.get("confidence", 0.5))))
        logger.info(
            f"[LLM/Claude] strategy={result.get('strategy')} "
            f"bias={result.get('bias')} conf={result.get('confidence', 0):.2f}"
        )
        return result

    except asyncio.TimeoutError:
        logger.warning("Claude orchestrator timed out")
        return {**_default, "reasoning": "Claude timed out"}
    except ImportError:
        logger.warning("anthropic package not installed — Claude unavailable")
        return {**_default, "reasoning": "anthropic package missing"}
    except Exception as e:
        logger.warning(f"Claude orchestrator failed: {e}")
        return {**_default, "reasoning": f"Claude error: {e}"}


# ─────────────────────────────────────────────────────────────────────────────
# Async ensemble coordinator
# ─────────────────────────────────────────────────────────────────────────────

async def _async_select_strategy(market_data: dict) -> dict:
    """
    Full async pipeline:
        1. Grok + GPT-4 in parallel
        2. Claude orchestrates using their outputs
        3. Returns final strategy recommendation dict
    """
    context = _build_context(market_data)
    context_json = json.dumps(context, indent=2)

    # ── Step 1: Grok + GPT-4 in parallel ─────────────────────────────────────
    grok_out, gpt4_out = await asyncio.gather(
        _query_grok(context_json),
        _query_gpt4(context_json, context),
    )

    # ── Step 2: Claude orchestrates ───────────────────────────────────────────
    claude_out = await _query_claude(context_json, grok_out, gpt4_out)

    # ── Step 3: Determine source + build output ───────────────────────────────
    # If Claude has a real answer, use it. Otherwise fall back to GPT-4.
    # If neither works, return FLAT.
    primary = claude_out
    has_real_answer = (
        primary.get("strategy") in STRATEGY_OPTIONS
        and primary.get("confidence", 0.0) > 0.0
        and "error" not in primary.get("reasoning", "").lower()
        and "not available" not in primary.get("reasoning", "").lower()
        and "not configured" not in primary.get("reasoning", "").lower()
    )

    if not has_real_answer:
        # Fall back to GPT-4 if Claude failed
        primary = gpt4_out
        has_real_answer = (
            primary.get("strategy") in STRATEGY_OPTIONS
            and primary.get("confidence", 0.0) > 0.0
            and "not configured" not in primary.get("reasoning", "").lower()
        )

    if not has_real_answer:
        logger.warning("[LLM] All models failed or unconfigured — returning FLAT fallback")
        return {
            "strategy":   "FLAT",
            "bias":       "NEUTRAL",
            "confidence": 0.0,
            "reasoning":  "All LLM models failed or are not configured. Falling back to rule-based engine.",
            "votes":      {"grok": grok_out, "gpt4": gpt4_out, "claude": claude_out},
            "source":     "fallback",
        }

    # Validate strategy value
    if primary.get("strategy") not in STRATEGY_OPTIONS:
        primary["strategy"] = "FLAT"

    return {
        "strategy":   primary.get("strategy", "FLAT"),
        "bias":       primary.get("bias", "NEUTRAL"),
        "confidence": primary.get("confidence", 0.5),
        "reasoning":  primary.get("reasoning", ""),
        "votes": {
            "grok":   grok_out,
            "gpt4":   gpt4_out,
            "claude": claude_out,
        },
        "source": "ensemble",
    }


# ─────────────────────────────────────────────────────────────────────────────
# Public synchronous API
# ─────────────────────────────────────────────────────────────────────────────

def get_llm_strategy_selection(market_data: dict) -> dict:
    """
    Synchronous wrapper — safe to call from APScheduler jobs.

    Args:
        market_data: dict with keys:
            close, ema20, vwap, adx, rsi, atr,
            vix, yield_10y, dxy, spy_vol_ratio,
            regime, vpoc_migration,
            brt_signal, orb_signal,
            headwinds, tailwinds, session_hour

    Returns:
        Strategy recommendation dict (see module docstring for schema).
        Always returns a valid dict — never raises.
    """
    try:
        return asyncio.run(_async_select_strategy(market_data))
    except RuntimeError:
        # If there's already an event loop (e.g. in tests), use get_event_loop
        try:
            loop = asyncio.get_event_loop()
            return loop.run_until_complete(_async_select_strategy(market_data))
        except Exception as e:
            logger.error(f"LLM selector async error: {e}")
            return {
                "strategy":   "FLAT",
                "bias":       "NEUTRAL",
                "confidence": 0.0,
                "reasoning":  f"Async error: {e}",
                "votes":      {},
                "source":     "fallback",
            }
    except Exception as e:
        logger.error(f"LLM selector failed: {e}")
        return {
            "strategy":   "FLAT",
            "bias":       "NEUTRAL",
            "confidence": 0.0,
            "reasoning":  f"Selector error: {e}",
            "votes":      {},
            "source":     "fallback",
        }
