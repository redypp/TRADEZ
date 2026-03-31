"""
llm_swing_scout.py
──────────────────
Proactive LLM-driven swing opportunity scanner.

Rather than asking LLMs to guess what looks good, this module first gathers
REAL market intelligence across a broad universe, then feeds that structured
data to the LLM pipeline for synthesis and ranking.

Data collected per symbol:
    • Price trend & momentum (% return, ATR, RSI, distance from EMAs)
    • Volume anomalies (recent vs. 30-day avg)
    • Short interest (days-to-cover, % float short)
    • Institutional ownership (top holders, recent 13F changes)
    • Insider transactions (net buying/selling last 90 days)
    • Upcoming earnings (within 0–30 days — catalyst window)
    • Analyst consensus & recent upgrades/target raises
    • Sector ETF momentum (which sectors are rotating in)
    • Options unusual activity (volume spike vs. OI, call skew)

Pipeline:
    1. _gather_market_intelligence() — fetches all data above
    2. _score_and_filter()           — scores each symbol, keeps top 20
    3. Grok   — interprets news/X sentiment for the pre-filtered names
    4. GPT-4  — validates macro fit, R:R, entry zones
    5. Claude — final ranking, conviction tiers, thesis per trade

Called by:
    - scheduler run_eod_swing_scan (16:05 ET)
    - web/api.py GET /api/swing/llm-ideas (10-min cache)
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import datetime, timezone, timedelta
from typing import Any

import pytz

logger = logging.getLogger(__name__)

ET = pytz.timezone("America/New_York")

# ─── Universe ─────────────────────────────────────────────────────────────────
# Broader than the technical screener — includes high-momentum names,
# potential breakout candidates, and sectors with current tailwinds.

_SCAN_UNIVERSE = [
    # Mega-cap tech / AI
    "AAPL", "MSFT", "NVDA", "META", "GOOGL", "AMZN", "AMD", "AVGO", "TSM",
    # Software / cloud
    "CRM", "ORCL", "SNOW", "MDB", "DDOG", "ZS", "PANW", "CRWD", "SHOP",
    # Semis
    "AMAT", "KLAC", "LRCX", "ASML", "QCOM", "MRVL",
    # Financials
    "GS", "MS", "JPM", "V", "MA", "COF",
    # Healthcare / biotech
    "LLY", "NVO", "ABBV", "ISRG", "DXCM",
    # Energy / industrials
    "XOM", "CVX", "CAT", "DE", "GE",
    # Consumer / retail
    "COST", "NKE", "LULU", "DECK",
    # High-beta / momentum names
    "AXON", "PLTR", "APP", "RDDT", "ARM", "SMCI",
]

# Sector ETFs for rotation analysis
_SECTOR_ETFS = {
    "Tech":       "XLK",
    "Energy":     "XLE",
    "Financials": "XLF",
    "Healthcare": "XLV",
    "Industrials":"XLI",
    "Consumer":   "XLY",
    "Materials":  "XLB",
    "Utilities":  "XLU",
    "Semis":      "SOXX",
    "Biotech":    "XBI",
}


# ─── Market Intelligence Gatherer ─────────────────────────────────────────────

def _safe_float(val, default=None):
    try:
        f = float(val)
        return None if (f != f) else f  # NaN check
    except Exception:
        return default


def _gather_market_intelligence() -> dict:
    """
    Pull real data for the scan universe.
    Returns a dict with:
        symbols:  list of per-symbol intelligence dicts
        sectors:  sector ETF momentum snapshot
        summary:  high-level market snapshot string
    """
    try:
        import yfinance as yf
        import pandas as pd
        import numpy as np
    except ImportError:
        logger.warning("[SwingScout] yfinance not available — skipping intelligence gather")
        return {"symbols": [], "sectors": {}, "summary": ""}

    # ── Sector momentum (last 20 days vs. 5 days) ─────────────────────────
    sector_data = {}
    try:
        etf_tickers = list(_SECTOR_ETFS.values())
        etf_df = yf.download(
            etf_tickers, period="30d", interval="1d",
            auto_adjust=True, progress=False,
        )["Close"]
        for name, etf in _SECTOR_ETFS.items():
            if etf not in etf_df.columns:
                continue
            s = etf_df[etf].dropna()
            if len(s) < 5:
                continue
            ret_5d  = float((s.iloc[-1] / s.iloc[-5]  - 1) * 100) if len(s) >= 5  else None
            ret_20d = float((s.iloc[-1] / s.iloc[-20] - 1) * 100) if len(s) >= 20 else None
            sector_data[name] = {
                "etf": etf,
                "ret_5d":  round(ret_5d,  2) if ret_5d  is not None else None,
                "ret_20d": round(ret_20d, 2) if ret_20d is not None else None,
                "trend":   "STRONG" if (ret_5d or 0) > 1.5
                           else "WEAK" if (ret_5d or 0) < -1.5
                           else "NEUTRAL",
            }
    except Exception as e:
        logger.warning(f"[SwingScout] Sector ETF fetch failed: {e}")

    # ── Per-symbol intelligence ────────────────────────────────────────────
    symbol_intel = []
    for sym in _SCAN_UNIVERSE:
        try:
            t = yf.Ticker(sym)
            info = t.fast_info  # lightweight — no heavy scraping

            # Price & momentum
            hist = t.history(period="60d", interval="1d", auto_adjust=True)
            if hist.empty or len(hist) < 20:
                continue

            close   = float(hist["Close"].iloc[-1])
            vol_5d  = float(hist["Volume"].iloc[-5:].mean())
            vol_30d = float(hist["Volume"].iloc[-30:].mean())
            ret_5d  = float((hist["Close"].iloc[-1] / hist["Close"].iloc[-5]  - 1) * 100) if len(hist) >= 5  else None
            ret_20d = float((hist["Close"].iloc[-1] / hist["Close"].iloc[-20] - 1) * 100) if len(hist) >= 20 else None

            # RSI (14)
            delta  = hist["Close"].diff()
            gain   = delta.clip(lower=0).rolling(14).mean()
            loss   = (-delta.clip(upper=0)).rolling(14).mean()
            rs     = gain / loss.replace(0, 1e-9)
            rsi    = float(100 - 100 / (1 + rs.iloc[-1]))

            # ATR (14)
            hl  = hist["High"] - hist["Low"]
            hc  = (hist["High"] - hist["Close"].shift()).abs()
            lc  = (hist["Low"]  - hist["Close"].shift()).abs()
            atr = float(pd.concat([hl, hc, lc], axis=1).max(axis=1).rolling(14).mean().iloc[-1])

            # EMA distance
            ema20 = float(hist["Close"].ewm(span=20).mean().iloc[-1])
            ema50 = float(hist["Close"].ewm(span=50).mean().iloc[-1])
            above_ema20 = close > ema20
            above_ema50 = close > ema50
            ema20_dist_pct = round((close / ema20 - 1) * 100, 2)

            # Volume anomaly score (recent 3-day avg vs. 30-day avg)
            vol_ratio = round(vol_5d / max(vol_30d, 1), 2)

            # Short interest (from info dict — may not always be available)
            full_info = {}
            try:
                full_info = t.info
            except Exception:
                pass
            short_ratio   = _safe_float(full_info.get("shortRatio"))
            short_pct     = _safe_float(full_info.get("shortPercentOfFloat"))
            market_cap    = _safe_float(full_info.get("marketCap"))
            analyst_count = _safe_float(full_info.get("numberOfAnalystOpinions"))
            target_price  = _safe_float(full_info.get("targetMeanPrice"))
            target_upside = round((target_price / close - 1) * 100, 1) if target_price and close else None
            rec_key       = full_info.get("recommendationKey", "")  # "buy","hold","sell","strong_buy"

            # Insider transactions (net buying = bullish signal)
            insider_net = None
            insider_summary = ""
            try:
                ins = t.insider_transactions
                if ins is not None and not ins.empty:
                    # Filter to last 90 days
                    cutoff = datetime.now() - timedelta(days=90)
                    if "Start Date" in ins.columns:
                        ins = ins[pd.to_datetime(ins["Start Date"], errors="coerce") > cutoff]
                    elif "startDate" in ins.columns:
                        ins = ins[pd.to_datetime(ins["startDate"], errors="coerce") > cutoff]
                    # Sum shares acquired vs disposed
                    if "Shares" in ins.columns and "Transaction" in ins.columns:
                        buys  = ins[ins["Transaction"].str.contains("Purchase|Buy", na=False, case=False)]["Shares"].sum()
                        sells = ins[ins["Transaction"].str.contains("Sale|Sell",    na=False, case=False)]["Shares"].sum()
                        insider_net = int(buys - sells)
                        if insider_net > 50_000:
                            insider_summary = f"NET BUY {insider_net:,} shares (90d)"
                        elif insider_net < -50_000:
                            insider_summary = f"NET SELL {abs(insider_net):,} shares (90d)"
            except Exception:
                pass

            # Institutional ownership (top holders)
            inst_summary = ""
            try:
                inst = t.institutional_holders
                if inst is not None and not inst.empty and "% Out" in inst.columns:
                    top = inst.head(3)
                    inst_summary = ", ".join(
                        f"{r['Holder']} ({r['% Out']*100:.1f}%)" if isinstance(r.get('% Out'), float)
                        else str(r.get('Holder',''))
                        for _, r in top.iterrows()
                    )
            except Exception:
                pass

            # Earnings date (next upcoming)
            earnings_in_days = None
            earnings_date_str = ""
            try:
                cal = t.calendar
                if cal is not None:
                    if isinstance(cal, dict):
                        ed = cal.get("Earnings Date")
                        if ed and len(ed) > 0:
                            ed_dt = pd.to_datetime(ed[0])
                            earnings_in_days = (ed_dt.date() - datetime.now().date()).days
                            earnings_date_str = ed_dt.strftime("%b %d")
                    elif hasattr(cal, "loc"):
                        if "Earnings Date" in cal.index:
                            ed_raw = cal.loc["Earnings Date"].iloc[0]
                            ed_dt  = pd.to_datetime(ed_raw)
                            earnings_in_days = (ed_dt.date() - datetime.now().date()).days
                            earnings_date_str = ed_dt.strftime("%b %d")
            except Exception:
                pass

            # Options: call/put skew and unusual activity
            options_note = ""
            try:
                expirations = t.options
                if expirations:
                    # Use the nearest expiration 7-21 days out
                    today = datetime.now().date()
                    target_exp = None
                    for exp_str in expirations:
                        exp_dt = datetime.strptime(exp_str, "%Y-%m-%d").date()
                        days_out = (exp_dt - today).days
                        if 5 <= days_out <= 30:
                            target_exp = exp_str
                            break
                    if target_exp:
                        chain = t.option_chain(target_exp)
                        call_vol = chain.calls["volume"].sum() if not chain.calls.empty else 0
                        put_vol  = chain.puts["volume"].sum()  if not chain.puts.empty  else 0
                        call_oi  = chain.calls["openInterest"].sum() if not chain.calls.empty else 0
                        put_oi   = chain.puts["openInterest"].sum()  if not chain.puts.empty  else 0
                        cp_ratio = round(call_vol / max(put_vol, 1), 2)
                        # Unusual = call volume > 2× OI suggests institutional positioning
                        unusual = call_vol > 0 and call_oi > 0 and (call_vol / max(call_oi, 1)) > 1.5
                        if unusual:
                            options_note = f"UNUSUAL CALLS vol={call_vol:,} vs OI={call_oi:,}"
                        elif cp_ratio > 2:
                            options_note = f"CALL SKEW {cp_ratio:.1f}×"
                        elif cp_ratio < 0.5:
                            options_note = f"PUT HEAVY {cp_ratio:.2f}×"
            except Exception:
                pass

            # Opportunity score (0–100, higher = more interesting for LLM review)
            score = 50
            if above_ema20 and above_ema50:   score += 10
            if 40 < rsi < 70:                 score += 8   # not overbought or oversold
            if vol_ratio > 1.5:               score += 10  # volume pickup
            if (ret_5d or 0) > 3:             score += 8   # recent momentum
            if insider_net and insider_net > 0: score += 12  # insider buying
            if earnings_in_days and 7 <= earnings_in_days <= 28: score += 10  # earnings catalyst
            if (target_upside or 0) > 15:     score += 8   # analyst upside
            if "buy" in rec_key.lower():      score += 6
            if options_note.startswith("UNUSUAL"): score += 12  # unusual options
            if (short_pct or 0) > 0.15:      score += 5   # squeeze potential

            symbol_intel.append({
                "symbol":            sym,
                "close":             round(close, 2),
                "ret_5d":            round(ret_5d,  2) if ret_5d  is not None else None,
                "ret_20d":           round(ret_20d, 2) if ret_20d is not None else None,
                "rsi":               round(rsi, 1),
                "atr":               round(atr, 2),
                "ema20_dist_pct":    ema20_dist_pct,
                "above_ema20":       above_ema20,
                "above_ema50":       above_ema50,
                "vol_ratio":         vol_ratio,
                "market_cap_b":      round(market_cap / 1e9, 1) if market_cap else None,
                "short_ratio":       round(short_ratio, 1) if short_ratio else None,
                "short_pct_float":   round(short_pct * 100, 1) if short_pct else None,
                "analyst_rec":       rec_key or None,
                "analyst_target":    round(target_price, 2) if target_price else None,
                "analyst_upside_pct": target_upside,
                "analyst_count":     int(analyst_count) if analyst_count else None,
                "insider_summary":   insider_summary or None,
                "institutional_top": inst_summary or None,
                "earnings_in_days":  earnings_in_days,
                "earnings_date":     earnings_date_str or None,
                "options_note":      options_note or None,
                "opportunity_score": min(score, 100),
            })

        except Exception as sym_err:
            logger.debug(f"[SwingScout] {sym}: {sym_err}")
            continue

    # Sort by score, keep top 20 for LLM analysis
    symbol_intel.sort(key=lambda x: x["opportunity_score"], reverse=True)
    top_symbols = symbol_intel[:20]

    # Strong sectors (for prompt context)
    strong_sectors = [
        f"{name} ({d['ret_5d']:+.1f}% 5d)"
        for name, d in sorted(sector_data.items(), key=lambda x: x[1].get("ret_5d") or 0, reverse=True)
        if d.get("trend") == "STRONG"
    ][:5]
    weak_sectors = [
        name for name, d in sector_data.items() if d.get("trend") == "WEAK"
    ]

    summary = (
        f"Strong sectors: {', '.join(strong_sectors) or 'none'}.  "
        f"Weak/avoid: {', '.join(weak_sectors) or 'none'}."
    )

    return {
        "symbols":       top_symbols,
        "all_symbols":   symbol_intel,
        "sectors":       sector_data,
        "strong_sectors": strong_sectors,
        "weak_sectors":  weak_sectors,
        "summary":       summary,
        "scanned_count": len(symbol_intel),
    }


# ─── Prompts ──────────────────────────────────────────────────────────────────

_GROK_SWING_PROMPT = """\
You are a swing trading intelligence analyst. You have access to live X/Twitter \
and news feeds. I'm giving you REAL pre-screened market data for today's top \
opportunity candidates — use this as your foundation.

Today: {today} | VIX={vix} | Market bias: {market_bias_hint}

SECTOR ROTATION (5-day momentum):
{sector_summary}

TOP CANDIDATES BY OPPORTUNITY SCORE (pre-screened from {scanned_count} stocks):
{candidates_table}

LEGEND: ret_5d=5-day return%, vol_ratio=vol vs 30d avg, rsi=RSI-14, \
ins=insider activity, earn=earnings in X days, opts=options note, \
analyst=recommendation|upside%

Your job: For the TOP 3-5 symbols from this list, identify the SPECIFIC \
catalyst or news driving the setup right now. Focus on:
- Confirmed institutional accumulation or unusual options = highest priority
- Upcoming earnings 7-28 days out + uptrend = high conviction
- Insider net buying + volume pickup = follow the smart money
- Sector momentum plays where the rotation is just starting
- Short squeeze candidates (high short % + improving price action)

Supplement with any current news/social sentiment you have access to.
Only recommend names from the provided list unless you have very strong \
current intelligence on a name not listed.

Respond in JSON:
{{"ideas": [{{"symbol": "TICKER", "catalyst": "<specific catalyst or data point>", \
"thesis": "<one sentence — why now, why long>", "sector": "<sector>", \
"urgency": "HIGH|MEDIUM|LOW", \
"source": "institutional|insider|earnings|options|sector_rotation|news|sentiment", \
"key_data": "<the most compelling data point from the table>"}}], \
"market_bias": "RISK_ON|RISK_OFF|NEUTRAL", \
"avoid_sectors": ["<sector1>"], \
"intelligence_note": "<any current market intel not captured in the data>"}}"""


_GPT4_SWING_PROMPT = """\
You are a quantitative analyst scoring swing trade ideas. I'm giving you \
data-backed swing ideas and need macro + technical validation.

Today: {today} | VIX={vix} | DXY={dxy} | 10Y={yield_10y}%

IDEAS TO SCORE (with underlying data):
{ideas_with_data_json}

For each symbol, assess:
1. Does macro environment (VIX, rates, DXY) support this LONG swing?
2. Is RSI in a healthy range for entry (30-65 ideal)?
3. Is the analyst target price realistic vs. current price?
4. What's the options market signaling (if options data present)?
5. Rate risk/reward: HIGH (strong data support) / MEDIUM / LOW
6. Estimate entry zone (near current price, key level, or earnings-play entry)
7. Primary invalidation level

Note: if insider_summary shows NET BUY → add conviction. \
If short_pct_float > 15% AND price rising → squeeze risk = upside amplifier.

Respond in JSON:
{{"scored": [{{"symbol": "TICKER", "rr_rating": "HIGH|MEDIUM|LOW", \
"macro_ok": true|false, "rsi_ok": true|false, \
"entry_note": "<brief entry level>", "key_risk": "<invalidation>", \
"conviction": <0.0-1.0>, \
"data_edge": "<the strongest single data point supporting this trade>"}}]}}"""


_CLAUDE_SWING_PROMPT = """\
You are the final decision layer for a data-driven swing trading bot.

Today: {today} | VIX: {vix} | Market bias: {market_bias}

INTELLIGENCE GATHERED (real data — not speculation):
Sector leaders: {strong_sectors}
Sectors to avoid: {weak_sectors}

GROK's top picks (catalyst + news intelligence):
{grok_ideas_json}

GPT-4's quantitative scores:
{gpt4_scored_json}

FULL DATA CONTEXT for top candidates:
{symbol_data_json}

Your job:
1. Combine data evidence + news catalyst + macro score → rank top 3 ideas
2. For each, write a sharp 1-sentence thesis grounded in the ACTUAL DATA
   (cite the specific data point: "Insiders net-bought 200K shares + earnings in 12 days")
3. Reject any idea where the data doesn't support the thesis
4. A valid trade requires: clear catalyst OR unusual institutional signal, \
   price above EMAs, RSI not overbought, macro not hostile
5. Assign final confidence (0.0-1.0). Only include >= 0.60. Be selective.

Respond in JSON:
{{"top_ideas": [{{"symbol": "TICKER", \
"thesis": "<data-grounded one sentence — cite the key evidence>", \
"confidence": <0.0-1.0>, \
"catalyst": "<specific catalyst or data trigger>", \
"entry_note": "<entry context>", \
"key_risk": "<main risk>", \
"conviction_tier": "HIGH|MEDIUM", \
"supporting_data": "<the 2-3 data points that make this compelling>"}}], \
"rejected": [{{"symbol": "TICKER", "reason": "<why rejected>"}}], \
"market_note": "<one sentence on overall swing environment today>"}}"""


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


def _format_candidates_table(symbols: list) -> str:
    """Format top candidates as a compact table string for the prompt."""
    lines = []
    for s in symbols[:15]:  # cap at 15 to stay within token limits
        parts = [
            f"{s['symbol']:<6}",
            f"${s['close']:.2f}",
            f"5d:{s['ret_5d']:+.1f}%" if s.get('ret_5d') is not None else "5d:—",
            f"vol×{s['vol_ratio']:.1f}",
            f"RSI:{s['rsi']:.0f}",
        ]
        if s.get("insider_summary"):
            parts.append(f"INS:{s['insider_summary'][:30]}")
        if s.get("earnings_in_days") and 0 < s["earnings_in_days"] <= 30:
            parts.append(f"EARN:{s['earnings_date']}({s['earnings_in_days']}d)")
        if s.get("options_note"):
            parts.append(f"OPTS:{s['options_note']}")
        if s.get("analyst_upside_pct") and s["analyst_upside_pct"] > 10:
            parts.append(f"TGT:+{s['analyst_upside_pct']:.0f}%({s['analyst_rec']})")
        if s.get("short_pct_float") and s["short_pct_float"] > 10:
            parts.append(f"SHORT:{s['short_pct_float']:.0f}%float")
        lines.append("  " + "  ".join(parts))
    return "\n".join(lines)


async def _query_grok_swing(intel: dict, vix: float) -> dict:
    try:
        from config import settings as s
        if not getattr(s, "GROK_API_KEY", ""):
            return {"ideas": [], "market_bias": "NEUTRAL", "avoid_sectors": []}

        from openai import AsyncOpenAI
        client = AsyncOpenAI(api_key=s.GROK_API_KEY, base_url="https://api.x.ai/v1")

        # Infer market bias from sector momentum
        strong = intel.get("strong_sectors", [])
        bias_hint = "RISK_ON" if len(strong) >= 3 else "RISK_OFF" if vix > 25 else "NEUTRAL"

        prompt = _GROK_SWING_PROMPT.format(
            today=datetime.now(ET).strftime("%A %B %d, %Y"),
            vix=round(vix, 1),
            market_bias_hint=bias_hint,
            sector_summary=intel.get("summary", ""),
            scanned_count=intel.get("scanned_count", len(_SCAN_UNIVERSE)),
            candidates_table=_format_candidates_table(intel.get("symbols", [])),
        )
        resp = await asyncio.wait_for(
            client.chat.completions.create(
                model="grok-3-mini",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=1000,
            ),
            timeout=25.0,
        )
        result = _parse_json(resp.choices[0].message.content or "")
        logger.info(f"[SwingScout/Grok] {len(result.get('ideas', []))} ideas from {intel.get('scanned_count', 0)} scanned")
        return result
    except Exception as e:
        logger.warning(f"[SwingScout] Grok failed: {e}")
        return {"ideas": [], "market_bias": "NEUTRAL", "avoid_sectors": []}


async def _query_gpt4_swing(ideas: list, intel: dict, vix: float, dxy: float, yield_10y: float) -> dict:
    try:
        from config import settings as s
        if not getattr(s, "OPENAI_API_KEY", "") or not ideas:
            return {"scored": []}

        from openai import AsyncOpenAI
        client = AsyncOpenAI(api_key=s.OPENAI_API_KEY)

        # Enrich ideas with their underlying data
        symbol_lookup = {sym["symbol"]: sym for sym in intel.get("all_symbols", [])}
        ideas_enriched = []
        for idea in ideas:
            enriched = dict(idea)
            sym_data = symbol_lookup.get(idea.get("symbol"), {})
            enriched["_data"] = {k: v for k, v in sym_data.items()
                                  if k not in ("symbol",) and v is not None}
            ideas_enriched.append(enriched)

        prompt = _GPT4_SWING_PROMPT.format(
            today=datetime.now(ET).strftime("%B %d, %Y"),
            vix=round(vix, 1),
            dxy=round(dxy, 2) if dxy else "n/a",
            yield_10y=round(yield_10y, 3) if yield_10y else "n/a",
            ideas_with_data_json=json.dumps(ideas_enriched, indent=2),
        )
        resp = await asyncio.wait_for(
            client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.15,
                max_tokens=700,
            ),
            timeout=20.0,
        )
        result = _parse_json(resp.choices[0].message.content or "")
        logger.info(f"[SwingScout/GPT-4] scored {len(result.get('scored', []))} ideas")
        return result
    except Exception as e:
        logger.warning(f"[SwingScout] GPT-4 failed: {e}")
        return {"scored": []}


async def _query_claude_swing(grok_out: dict, gpt4_out: dict, intel: dict, vix: float) -> dict:
    try:
        from config import settings as s
        if not getattr(s, "ANTHROPIC_API_KEY", ""):
            return {"top_ideas": [], "rejected": [], "market_note": ""}

        import anthropic
        client = anthropic.AsyncAnthropic(api_key=s.ANTHROPIC_API_KEY)

        # Include full symbol data for top candidates so Claude has the complete picture
        all_sym = {sym["symbol"]: sym for sym in intel.get("all_symbols", [])}
        top_syms = [i.get("symbol") for i in grok_out.get("ideas", [])] + \
                   [s.get("symbol") for s in gpt4_out.get("scored", [])]
        symbol_data_subset = {sym: all_sym[sym] for sym in set(top_syms) if sym in all_sym}

        prompt = _CLAUDE_SWING_PROMPT.format(
            today=datetime.now(ET).strftime("%B %d, %Y"),
            vix=round(vix, 1),
            market_bias=grok_out.get("market_bias", "NEUTRAL"),
            strong_sectors=", ".join(intel.get("strong_sectors", [])) or "none",
            weak_sectors=", ".join(intel.get("weak_sectors", [])) or "none",
            grok_ideas_json=json.dumps(grok_out.get("ideas", []), indent=2),
            gpt4_scored_json=json.dumps(gpt4_out.get("scored", []), indent=2),
            symbol_data_json=json.dumps(symbol_data_subset, indent=2),
        )
        resp = await asyncio.wait_for(
            client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=900,
                messages=[{"role": "user", "content": prompt}],
            ),
            timeout=25.0,
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
    Full pipeline:
        1. Gather real market intelligence across the universe
        2. Grok adds news/sentiment layer on top of the data
        3. GPT-4 validates macro + quantitative fit
        4. Claude synthesizes final ranked ideas with data citations
    """
    vix       = float(market_data.get("vix")       or 18.0)
    dxy       = float(market_data.get("dxy")       or 104.0)
    yield_10y = float(market_data.get("yield_10y") or 4.3)

    # Step 1: gather real data (blocking but fast — yfinance batch download)
    logger.info(f"[SwingScout] Scanning {len(_SCAN_UNIVERSE)} symbols for market intelligence…")
    intel = _gather_market_intelligence()
    logger.info(
        f"[SwingScout] Intelligence gathered: {intel.get('scanned_count', 0)} symbols. "
        f"Sectors: {intel.get('summary', '')}"
    )

    # Step 2: Grok adds news/sentiment context on top of the real data
    grok_out = await _query_grok_swing(intel, vix)

    # Step 3: GPT-4 validates with macro/quant lens
    gpt4_out = await _query_gpt4_swing(
        grok_out.get("ideas", []), intel, vix, dxy, yield_10y
    )

    # Step 4: Claude synthesizes and ranks, citing actual data
    claude_out = await _query_claude_swing(grok_out, gpt4_out, intel, vix)

    return {
        "top_ideas":      claude_out.get("top_ideas", []),
        "rejected":       claude_out.get("rejected", []),
        "market_note":    claude_out.get("market_note", ""),
        "market_bias":    grok_out.get("market_bias", "NEUTRAL"),
        "avoid_sectors":  grok_out.get("avoid_sectors", []),
        "strong_sectors": intel.get("strong_sectors", []),
        "scanned_count":  intel.get("scanned_count", 0),
        "timestamp":      datetime.now(ET).strftime("%H:%M ET"),
        "vix":            vix,
    }


def run_swing_scout(market_data: dict) -> dict:
    """Synchronous wrapper — call from scheduler or API."""
    try:
        return asyncio.run(_async_scan(market_data))
    except Exception as e:
        logger.error(f"[SwingScout] pipeline failed: {e}")
        return {"top_ideas": [], "market_note": "", "timestamp": "", "error": str(e)}
