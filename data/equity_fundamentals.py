"""
data/equity_fundamentals.py
────────────────────────────
Per-symbol fundamental intelligence layer.

This module is the foundation of what separates TRADEZ from a pure algo:
every swing trade decision is informed by real company fundamentals, not
just price action.

Data pulled per symbol:
  Earnings quality     — Beat/miss streak (last 4Q), EPS growth, surprise %
  Earnings history     — Last 4Q actual vs estimate with surprise magnitude
  Revenue health       — YoY & QoQ revenue growth trend
  Analyst consensus    — Net upgrade/downgrade trend last 90 days + target upside
  Insider activity     — Net buying/selling last 90 days (SEC-reported)
  Financial health     — Gross margin, operating margin, debt/equity, FCF yield
  Short interest       — % float short, days to cover (squeeze potential)
  Geopolitical exposure— Sector classification + active geo risks per sector
  Earnings catalyst    — Days to next earnings (catalyst window: 7-28 days)
  Company news         — Top 3 recent headlines via Grok (ticker-specific)

Geopolitical risk context (updated manually for major macro regimes):
  Tech      → AI regulation, China/Taiwan chip risk, tariff exposure
  Energy    → OPEC decisions, Middle East tensions, Russia/Ukraine pipeline
  Financials→ Fed rate policy, regional banking stress, credit spreads
  Healthcare→ Drug pricing legislation, FDA approval risk, GLP-1 competition
  Industrials→ Defense spending (NATO), infrastructure bill, China decoupling
  Consumer  → Tariff pass-through, consumer confidence, discretionary risk

Used by:
  strategy/momentum_swing.py   — fundamental gate before execution
  strategy/llm_swing_scout.py  — enriches LLM prompts with real data
  web/api.py                   — /api/swing/screener (per-row fundamentals)
  strategy/llm_selector.py     — geo/fundamental context in MES decision
  orchestrator.py              — fundamental gate for equity strategies
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

# ─── Geopolitical sector exposure map ─────────────────────────────────────────
# Curated by sector. Updated to reflect current macro environment.
# Risk level: HIGH / MEDIUM / LOW
# Geo risks are real, named events — not vague speculation.

GEO_SECTOR_MAP = {
    # Ticker → (sector_label, geo_risks, geo_risk_level)
    # Tech / AI / Semis
    "AAPL":  ("Tech",       ["China revenue exposure (20%+ of sales)", "US-China tariff escalation"], "HIGH"),
    "MSFT":  ("Tech",       ["AI regulation (EU AI Act)", "Azure gov contracts"], "LOW"),
    "NVDA":  ("Semis",      ["Export controls China/Russia", "Taiwan TSMC concentration"], "HIGH"),
    "AMD":   ("Semis",      ["China export controls", "AI compute demand"], "MEDIUM"),
    "AVGO":  ("Semis",      ["China revenue ~25%", "VMware integration risk"], "HIGH"),
    "TSM":   ("Semis",      ["Taiwan strait geopolitical risk", "US subsidy dependency"], "HIGH"),
    "AMAT":  ("Semis",      ["China equipment export ban", "WFE cycle"], "HIGH"),
    "KLAC":  ("Semis",      ["China export controls"], "HIGH"),
    "LRCX":  ("Semis",      ["China restriction compliance"], "HIGH"),
    "ASML":  ("Semis",      ["Dutch export controls EUV to China", "TSMC dependency"], "HIGH"),
    "QCOM":  ("Semis",      ["China handset market", "Huawei settlement"], "HIGH"),
    "MRVL":  ("Semis",      ["AI custom chips — concentration in hyperscalers"], "MEDIUM"),
    "META":  ("Tech",       ["EU content regulation", "AI Llama open-source risk"], "MEDIUM"),
    "GOOGL": ("Tech",       ["DOJ antitrust breakup risk", "AI competition OpenAI"], "MEDIUM"),
    "AMZN":  ("Tech",       ["AWS gov cloud expansion", "FTC regulatory scrutiny"], "MEDIUM"),
    "CRM":   ("Software",   ["Enterprise spending slowdown", "AI agent competition"], "LOW"),
    "ORCL":  ("Software",   ["US gov cloud (JEDI successor)", "AI data center"], "LOW"),
    "SNOW":  ("Software",   ["Enterprise AI data spend", "AWS/Azure competition"], "LOW"),
    "MDB":   ("Software",   ["Atlas cloud consumption model"], "LOW"),
    "DDOG":  ("Software",   ["Observability spend — IT budget sensitivity"], "LOW"),
    "ZS":    ("Software",   ["Cybersecurity — government mandates (CISA)"], "LOW"),
    "PANW":  ("Software",   ["Cybersecurity consolidation"], "LOW"),
    "CRWD":  ("Software",   ["July 2024 outage reputational risk", "Govt contracts"], "MEDIUM"),
    "SHOP":  ("Software",   ["Tariff impact on SMB merchants", "US/Canada trade"], "MEDIUM"),
    # Financials
    "GS":    ("Financials", ["Investment banking cycle", "Credit risk"], "LOW"),
    "MS":    ("Financials", ["Wealth management", "M&A pipeline"], "LOW"),
    "JPM":   ("Financials", ["Commercial real estate exposure", "Basel III endgame"], "MEDIUM"),
    "V":     ("Financials", ["Cross-border volume", "CBDCs regulatory risk"], "LOW"),
    "MA":    ("Financials", ["Cross-border volume", "Emerging markets"], "LOW"),
    "COF":   ("Financials", ["Consumer credit quality", "CFPB late fee rule"], "HIGH"),
    # Healthcare
    "LLY":   ("Healthcare", ["GLP-1 pricing pressure (Medicare negotiation)", "Capacity risk"], "MEDIUM"),
    "NVO":   ("Healthcare", ["GLP-1 competitor (LLY)", "Danish krone FX"], "MEDIUM"),
    "ABBV":  ("Healthcare", ["Humira biosimilar erosion", "Pipeline dependency"], "MEDIUM"),
    "ISRG":  ("Healthcare", ["Surgical robotics adoption", "Hospital capex"], "LOW"),
    "DXCM":  ("Healthcare", ["CGM competition (Abbott FreeStyle)", "Medicare coverage"], "MEDIUM"),
    # Energy
    "XOM":   ("Energy",     ["OPEC+ production decisions", "Energy transition capex"], "MEDIUM"),
    "CVX":   ("Energy",     ["Hess deal (Guyana arbitration)", "OPEC+ discipline"], "MEDIUM"),
    # Industrials / Defense
    "CAT":   ("Industrials",["China construction slowdown", "Infrastructure spending"], "MEDIUM"),
    "DE":    ("Industrials", ["Ag commodity prices", "Tariff on steel/aluminum"], "MEDIUM"),
    "GE":    ("Industrials", ["Aerospace engine orders", "Defense segment"], "LOW"),
    # Consumer
    "COST":  ("Consumer",   ["Tariff pass-through on imports", "Membership value"], "LOW"),
    "NKE":   ("Consumer",   ["China market recovery", "Vietnam manufacturing tariff"], "HIGH"),
    "LULU":  ("Consumer",   ["Premium consumer spending slowdown"], "MEDIUM"),
    "DECK":  ("Consumer",   ["Footwear tariffs", "HOKA momentum"], "MEDIUM"),
    # High-beta / momentum
    "TSLA":  ("Tech",       ["China EV competition BYD", "Tariff impact Model 3", "Musk politics"], "HIGH"),
    "PLTR":  ("Tech",       ["US gov contract concentration", "AIP commercial ramp"], "LOW"),
    "APP":   ("Tech",       ["Mobile advertising cycle", "Privacy regulation"], "MEDIUM"),
    "AXON":  ("Industrials",["Law enforcement budget", "TASER competition"], "LOW"),
    "RDDT":  ("Tech",       ["Monetization still early", "Content moderation risk"], "MEDIUM"),
    "ARM":   ("Semis",      ["SoftBank overhang", "NVDA/Apple concentration"], "MEDIUM"),
    "SMCI":  ("Tech",       ["Audit/accounting concerns", "NVDA GPU supply chain"], "HIGH"),
    "COIN":  ("Financials", ["Crypto regulatory risk (SEC)", "BTC price correlation"], "HIGH"),
    "HOOD":  ("Financials", ["PFOF regulatory risk", "Retail trading volume"], "HIGH"),
    "SQ":    ("Fintech",    ["Cash App monetization", "Buy now pay later regulation"], "MEDIUM"),
    "PYPL":  ("Fintech",    ["Competition from ApplePay/GooglePay", "Braintree margin"], "MEDIUM"),
    "MSTR":  ("Crypto",     ["BTC proxy — maximum crypto volatility"], "HIGH"),
    "RBLX":  ("Tech",       ["Metaverse demand", "Youth gaming demographics"], "LOW"),
    "U":     ("Tech",       ["Game engine market share Unity/Unreal", "Runtime fee reversal"], "MEDIUM"),
    "IONQ":  ("Tech",       ["Quantum computing pre-revenue", "Gov grants"], "LOW"),
    "UBER":  ("Tech",       ["Autonomous vehicle displacement risk", "Driver legislation"], "MEDIUM"),
    "ABNB":  ("Consumer",   ["Travel demand sustainability", "Short-term rental regulation"], "MEDIUM"),
    # Additional coverage for full swing universe
    "NFLX":  ("Tech",       ["Streaming ad tier growth", "Password sharing crackdown"], "LOW"),
    "INTC":  ("Semis",      ["Foundry turnaround risk", "US CHIPS Act subsidy dependency"], "HIGH"),
    "MU":    ("Semis",      ["DRAM/NAND pricing cycle", "China memory ban"], "HIGH"),
    "ON":    ("Semis",      ["EV chip demand", "Industrial cycle sensitivity"], "MEDIUM"),
    "SNPS":  ("Semis",      ["EDA spending tied to chip capex", "China export compliance"], "MEDIUM"),
    "CDNS":  ("Semis",      ["EDA/IP licensing", "China restrictions"], "MEDIUM"),
    "NOW":   ("Software",   ["Enterprise IT spending", "AI workflow automation"], "LOW"),
    "WDAY":  ("Software",   ["HR/finance SaaS spending cycle"], "LOW"),
    "TEAM":  ("Software",   ["Enterprise collaboration spending"], "LOW"),
    "NET":   ("Software",   ["Cybersecurity/CDN spending", "Enterprise adoption"], "LOW"),
    "HUBS":  ("Software",   ["SMB marketing spend cycle"], "LOW"),
    "WMT":   ("Consumer",   ["Tariff pass-through risk", "E-commerce growth"], "MEDIUM"),
    "TGT":   ("Consumer",   ["Discretionary spending weakness", "Tariff exposure"], "MEDIUM"),
    "HD":    ("Consumer",   ["Housing market sensitivity", "Rate cycle impact"], "MEDIUM"),
    "LOW":   ("Consumer",   ["Housing turnover rates", "DIY spending"], "MEDIUM"),
    "PEP":   ("Consumer",   ["Pricing power limits", "GLP-1 impact on snacking"], "LOW"),
    "KO":    ("Consumer",   ["Emerging market FX", "Sugar tax regulation"], "LOW"),
    "DIS":   ("Consumer",   ["Theme park + streaming dual model", "Content costs"], "MEDIUM"),
    "BA":    ("Industrials",["737 MAX production ramp", "FAA scrutiny", "Defense backlog"], "HIGH"),
    "RTX":   ("Industrials",["Defense spending growth (NATO)", "Engine recall costs"], "MEDIUM"),
    "LMT":   ("Industrials",["Defense budget dependency", "F-35 program"], "LOW"),
    "UNH":   ("Healthcare", ["Medicare Advantage scrutiny", "PBM reform risk"], "MEDIUM"),
    "JNJ":   ("Healthcare", ["Talc litigation", "MedTech growth"], "MEDIUM"),
    "PFE":   ("Healthcare", ["Post-COVID revenue cliff", "Oncology pipeline"], "MEDIUM"),
    "MRNA":  ("Healthcare", ["mRNA pipeline beyond COVID", "RSV/flu vaccine adoption"], "MEDIUM"),
    "BRK-B": ("Financials", ["Berkshire cash deployment", "Insurance float"], "LOW"),
    "C":     ("Financials", ["Consumer credit quality", "International exposure"], "MEDIUM"),
    "BAC":   ("Financials", ["Rate sensitivity", "Consumer banking trends"], "MEDIUM"),
    "AXP":   ("Financials", ["Premium consumer spending", "Travel recovery"], "LOW"),
    "SLB":   ("Energy",     ["Oilfield services spending cycle", "International upstream"], "MEDIUM"),
    "COP":   ("Energy",     ["Permian Basin production", "LNG export growth"], "MEDIUM"),
}

# Default for unlisted symbols
_DEFAULT_GEO = ("Unknown", ["Limited geopolitical data available"], "MEDIUM")


def _safe(val, default=None):
    try:
        f = float(val)
        return None if (f != f) else f  # NaN check
    except Exception:
        return default


def get_equity_fundamentals(symbol: str) -> dict:
    """
    Pull full fundamental context for a single symbol.

    Returns a structured dict with fundamental scores and qualitative signals.
    All fields have safe defaults — never raises.
    """
    result = {
        "symbol":            symbol,
        # Earnings
        "eps_beat_streak":   0,      # consecutive quarters beating EPS estimate
        "eps_growth_yoy":    None,   # YoY EPS growth %
        "eps_surprise_avg":  None,   # avg EPS surprise % last 4Q
        "rev_growth_yoy":    None,   # Revenue YoY growth %
        "earnings_history":  [],     # last 4Q: [{quarter, actual, estimate, surprise_pct, beat}]
        # Analyst
        "analyst_rec":       None,   # "strong_buy"|"buy"|"hold"|"sell"
        "analyst_count":     None,
        "analyst_target":    None,
        "analyst_upside":    None,   # % upside to mean target
        "analyst_trend":     "NEUTRAL",  # "UPGRADING"|"DOWNGRADING"|"NEUTRAL"
        "analyst_trend_detail": "",
        # Insider
        "insider_net_shares":  None,
        "insider_signal":      "NEUTRAL",  # "BUYING"|"SELLING"|"NEUTRAL"
        "insider_detail":      "",
        # Financial health
        "gross_margin":      None,
        "operating_margin":  None,
        "profit_margin":     None,
        "debt_to_equity":    None,
        "fcf_yield":         None,   # FCF / market cap %
        "revenue_growth":    None,   # most recent QoQ revenue growth
        # Catalysts
        "earnings_in_days":  None,
        "earnings_date":     "",
        # Short interest
        "short_pct_float":   None,
        "short_ratio":       None,
        "squeeze_potential": False,
        # Geopolitical
        "sector":            "Unknown",
        "geo_risks":         [],
        "geo_risk_level":    "MEDIUM",
        # Company-specific news (populated by get_symbol_news)
        "recent_headlines":  [],     # top 3 company-specific headlines from Grok
        "news_sentiment":    "NEUTRAL",  # BULLISH|BEARISH|NEUTRAL based on recent headlines
        # Composite scores
        "fundamental_score": 50,     # 0-100
        "fundamental_grade": "C",    # A/B/C/D
        "bull_case":         "",     # one-line bull case summary
        "bear_case":         "",     # one-line bear case summary
        "error":             None,
    }

    try:
        import yfinance as yf
        import pandas as pd

        t = yf.Ticker(symbol)

        # ── Geopolitical context ──────────────────────────────────────────────
        geo = GEO_SECTOR_MAP.get(symbol, _DEFAULT_GEO)
        result["sector"]        = geo[0]
        result["geo_risks"]     = geo[1]
        result["geo_risk_level"]= geo[2]

        # ── Analyst data ──────────────────────────────────────────────────────
        info = {}
        try:
            info = t.info or {}
        except Exception:
            pass

        rec_key       = info.get("recommendationKey", "")
        target_price  = _safe(info.get("targetMeanPrice"))
        target_hi     = _safe(info.get("targetHighPrice"))
        target_lo     = _safe(info.get("targetLowPrice"))
        analyst_count = _safe(info.get("numberOfAnalystOpinions"), 0)
        current_price = _safe(info.get("currentPrice") or info.get("regularMarketPrice"))

        result["analyst_rec"]    = rec_key or None
        result["analyst_count"]  = int(analyst_count) if analyst_count else None
        result["analyst_target"] = round(target_price, 2) if target_price else None

        if target_price and current_price and current_price > 0:
            upside = (target_price / current_price - 1) * 100
            result["analyst_upside"] = round(upside, 1)

        # Analyst recommendation trend (last 90 days)
        try:
            recs = t.recommendations
            if recs is not None and not recs.empty:
                # Normalize column names
                recs.columns = [c.lower().replace(" ", "_") for c in recs.columns]
                if "period" in recs.columns:
                    # Old format: period, strongBuy, buy, hold, sell, strongSell
                    recent = recs.tail(3)
                    if len(recent) >= 2:
                        buy_now  = int(recent.get("strongbuy", pd.Series([0])).iloc[-1] or 0) + \
                                   int(recent.get("buy",       pd.Series([0])).iloc[-1] or 0)
                        buy_prev = int(recent.get("strongbuy", pd.Series([0])).iloc[-2] or 0) + \
                                   int(recent.get("buy",       pd.Series([0])).iloc[-2] or 0)
                        sell_now  = int(recent.get("sell",      pd.Series([0])).iloc[-1] or 0) + \
                                    int(recent.get("strongsell",pd.Series([0])).iloc[-1] or 0)
                        sell_prev = int(recent.get("sell",      pd.Series([0])).iloc[-2] or 0) + \
                                    int(recent.get("strongsell",pd.Series([0])).iloc[-2] or 0)
                        buy_delta  = buy_now  - buy_prev
                        sell_delta = sell_now - sell_prev
                        if buy_delta > 0 and buy_delta > sell_delta:
                            result["analyst_trend"] = "UPGRADING"
                            result["analyst_trend_detail"] = f"+{buy_delta} buys added"
                        elif sell_delta > 0 and sell_delta > buy_delta:
                            result["analyst_trend"] = "DOWNGRADING"
                            result["analyst_trend_detail"] = f"+{sell_delta} sells added"
                else:
                    # New format: action-based rows
                    cutoff = datetime.now() - timedelta(days=90)
                    if hasattr(recs.index, "tz_localize"):
                        pass
                    try:
                        recs_recent = recs[recs.index >= pd.Timestamp(cutoff, tz="UTC")]
                    except Exception:
                        recs_recent = recs.tail(20)
                    if "togrades" in recs_recent.columns and "action" in recs_recent.columns:
                        upgrades   = recs_recent[recs_recent["action"].isin(["up","init","reit"])
                                                  & recs_recent["togrades"].str.lower().isin(
                                                      ["buy","strong buy","outperform","overweight"])]
                        downgrades = recs_recent[recs_recent["action"].isin(["down"])
                                                  & recs_recent["togrades"].str.lower().isin(
                                                      ["sell","underperform","underweight","reduce"])]
                        n_up = len(upgrades); n_dn = len(downgrades)
                        if n_up > n_dn and n_up >= 2:
                            result["analyst_trend"] = "UPGRADING"
                            result["analyst_trend_detail"] = f"{n_up} upgrades vs {n_dn} downgrades (90d)"
                        elif n_dn > n_up and n_dn >= 2:
                            result["analyst_trend"] = "DOWNGRADING"
                            result["analyst_trend_detail"] = f"{n_dn} downgrades vs {n_up} upgrades (90d)"
                        else:
                            result["analyst_trend_detail"] = f"{n_up} up / {n_dn} dn (90d)"
        except Exception:
            pass

        # ── Earnings quality + history ────────────────────────────────────────
        try:
            earnings = t.quarterly_earnings
            if earnings is not None and not earnings.empty:
                # Columns: Earnings, Estimate (actual EPS, estimated EPS)
                recent4 = earnings.head(4)  # most recent 4 quarters
                beat_streak = 0
                surprises   = []
                history     = []
                for idx, row in recent4.iterrows():
                    actual   = _safe(row.get("Earnings"))
                    estimate = _safe(row.get("Estimate"))
                    quarter_label = str(idx) if idx else ""
                    if actual is not None and estimate is not None and estimate != 0:
                        surprise_pct = round((actual - estimate) / abs(estimate) * 100, 1)
                        surprises.append(surprise_pct)
                        beat = actual > estimate
                        history.append({
                            "quarter": quarter_label,
                            "actual": round(actual, 2),
                            "estimate": round(estimate, 2),
                            "surprise_pct": surprise_pct,
                            "beat": beat,
                        })
                        if beat:
                            beat_streak += 1
                        else:
                            if not history[:-1]:  # first quarter checked
                                pass
                            beat_streak = 0  # reset — only count consecutive from most recent
                    elif actual is not None:
                        history.append({
                            "quarter": quarter_label,
                            "actual": round(actual, 2),
                            "estimate": None,
                            "surprise_pct": None,
                            "beat": None,
                        })
                # Recalculate streak from most recent quarter forward
                beat_streak = 0
                for h in history:
                    if h.get("beat") is True:
                        beat_streak += 1
                    else:
                        break
                result["eps_beat_streak"] = beat_streak
                result["earnings_history"] = history[:4]
                if surprises:
                    result["eps_surprise_avg"] = round(sum(surprises) / len(surprises), 1)
        except Exception:
            pass

        # ── Financial health ──────────────────────────────────────────────────
        result["gross_margin"]     = _safe(info.get("grossMargins"))
        result["operating_margin"] = _safe(info.get("operatingMargins"))
        result["profit_margin"]    = _safe(info.get("profitMargins"))
        result["debt_to_equity"]   = _safe(info.get("debtToEquity"))

        # Revenue growth
        rev_growth = _safe(info.get("revenueGrowth"))
        if rev_growth is not None:
            result["rev_growth_yoy"] = round(rev_growth * 100, 1)

        earnings_growth = _safe(info.get("earningsGrowth"))
        if earnings_growth is not None:
            result["eps_growth_yoy"] = round(earnings_growth * 100, 1)

        # FCF yield
        try:
            fcf       = _safe(info.get("freeCashflow"))
            mkt_cap   = _safe(info.get("marketCap"))
            if fcf and mkt_cap and mkt_cap > 0:
                result["fcf_yield"] = round(fcf / mkt_cap * 100, 2)
        except Exception:
            pass

        # ── Short interest ────────────────────────────────────────────────────
        short_pct  = _safe(info.get("shortPercentOfFloat"))
        short_ratio= _safe(info.get("shortRatio"))
        if short_pct is not None:
            result["short_pct_float"] = round(short_pct * 100, 1)
        if short_ratio is not None:
            result["short_ratio"]     = round(short_ratio, 1)
        # Squeeze potential: high short + price rising + volume surge
        result["squeeze_potential"] = (
            (result["short_pct_float"] or 0) > 15 and
            (result["short_ratio"]     or 0) > 3
        )

        # ── Insider activity ──────────────────────────────────────────────────
        try:
            ins = t.insider_transactions
            if ins is not None and not ins.empty:
                cutoff = datetime.now() - timedelta(days=90)
                ins_cols = [c.lower().replace(" ", "_") for c in ins.columns]
                ins.columns = ins_cols
                date_col = next((c for c in ins_cols
                                 if "date" in c or "start" in c), None)
                if date_col:
                    ins = ins[
                        pd.to_datetime(ins[date_col], errors="coerce") > cutoff
                    ]
                shares_col = next((c for c in ins_cols if "share" in c), None)
                txn_col    = next((c for c in ins_cols if "transact" in c), None)
                if shares_col and txn_col:
                    buys  = ins[ins[txn_col].str.contains(
                        "Purchase|Buy|Acquisition", na=False, case=False
                    )][shares_col].sum()
                    sells = ins[ins[txn_col].str.contains(
                        "Sale|Sell|Disposition", na=False, case=False
                    )][shares_col].sum()
                    net = int(buys - sells)
                    result["insider_net_shares"] = net
                    if net > 50_000:
                        result["insider_signal"] = "BUYING"
                        result["insider_detail"] = f"Net BUY {net:,} shares (90d)"
                    elif net < -50_000:
                        result["insider_signal"] = "SELLING"
                        result["insider_detail"] = f"Net SELL {abs(net):,} shares (90d)"
                    else:
                        result["insider_detail"] = f"Neutral (net {net:+,} shares, 90d)"
        except Exception:
            pass

        # ── Earnings date ─────────────────────────────────────────────────────
        try:
            cal = t.calendar
            if cal is not None:
                if isinstance(cal, dict):
                    ed = cal.get("Earnings Date")
                    if ed and len(ed) > 0:
                        ed_dt = pd.to_datetime(ed[0])
                        days  = (ed_dt.date() - datetime.now().date()).days
                        if 0 <= days <= 90:
                            result["earnings_in_days"] = days
                            result["earnings_date"] = ed_dt.strftime("%b %d")
        except Exception:
            pass

        # ── Earnings estimate revisions ───────────────────────────────────────
        # Track if analysts are raising or lowering estimates — strong predictive signal
        try:
            est = t.earnings_estimate
            if est is not None and not est.empty:
                # Compare current quarter estimate vs 30/60 days ago
                # yfinance returns: avg, low, high, yearAgoEps, growth
                avg_est = _safe(est.loc["avg", est.columns[0]])  # current Q estimate
                year_ago = _safe(est.loc["yearAgoEps", est.columns[0]])
                growth_est = _safe(est.loc["growth", est.columns[0]])
                if growth_est is not None:
                    result["est_growth"] = round(growth_est * 100, 1)
                if avg_est and year_ago and year_ago != 0:
                    result["est_revision_pct"] = round(((avg_est - year_ago) / abs(year_ago)) * 100, 1)
        except Exception:
            pass

        try:
            rev_est = t.revenue_estimate
            if rev_est is not None and not rev_est.empty:
                rev_growth = _safe(rev_est.loc["growth", rev_est.columns[0]])
                if rev_growth is not None:
                    result["rev_est_growth"] = round(rev_growth * 100, 1)
        except Exception:
            pass

        # ── SEC EDGAR filings (8-K, Form 4 clusters, 13D activists) ──────────
        sec_score_delta = 0
        sec_detail = ""
        try:
            from data.sec_edgar import get_sec_score
            sec_score_delta, sec_detail = get_sec_score(symbol)
            result["sec_score_delta"] = sec_score_delta
            result["sec_detail"] = sec_detail
        except Exception as sec_err:
            logger.debug(f"[Fundamentals] SEC EDGAR skipped for {symbol}: {sec_err}")

        # ── Congressional trading tracker ────────────────────────────────────
        political_score_delta = 0
        political_detail = ""
        try:
            from data.political_trades import get_political_score
            political_score_delta, political_detail = get_political_score(symbol)
            result["political_score_delta"] = political_score_delta
            result["political_detail"] = political_detail
        except Exception as pol_err:
            logger.debug(f"[Fundamentals] Political trades skipped for {symbol}: {pol_err}")

        # ── Composite fundamental score (0-100) ───────────────────────────────
        score = 50  # neutral base

        # Earnings quality
        streak = result["eps_beat_streak"]
        if streak >= 4:    score += 15
        elif streak >= 3:  score += 10
        elif streak >= 2:  score += 5
        elif streak == 0:  score -= 8

        surprise = result["eps_surprise_avg"]
        if surprise and surprise > 5:   score += 8
        elif surprise and surprise < -3: score -= 8

        # Revenue growth
        rev = result["rev_growth_yoy"]
        if rev and rev > 20:   score += 10
        elif rev and rev > 10: score += 5
        elif rev and rev < 0:  score -= 10

        # Analyst consensus
        rec = result["analyst_rec"] or ""
        if "strong_buy" in rec: score += 12
        elif "buy" in rec:      score += 8
        elif "sell" in rec:     score -= 10
        if result["analyst_trend"] == "UPGRADING":   score += 8
        elif result["analyst_trend"] == "DOWNGRADING": score -= 8
        upside = result["analyst_upside"]
        if upside and upside > 20:   score += 6
        elif upside and upside < 0:  score -= 8

        # Insider signal
        if result["insider_signal"] == "BUYING":   score += 10
        elif result["insider_signal"] == "SELLING": score -= 6

        # Financial health
        op_margin = result["operating_margin"]
        if op_margin and op_margin > 0.20: score += 5
        elif op_margin and op_margin < 0:  score -= 8
        fcf = result["fcf_yield"]
        if fcf and fcf > 3:  score += 5
        elif fcf and fcf < 0: score -= 5

        # Earnings catalyst (positive if upcoming)
        edays = result["earnings_in_days"]
        if edays and 7 <= edays <= 28:   score += 6   # in catalyst window
        elif edays and edays <= 6:        score -= 4   # too close — binary event risk

        # Squeeze potential
        if result["squeeze_potential"]: score += 5

        # Earnings estimate revisions
        est_growth = result.get("est_growth")
        if est_growth is not None:
            if est_growth > 10:    score += 10  # estimates rising strongly
            elif est_growth > 5:   score += 6
            elif est_growth < -10: score -= 10  # estimates falling hard
            elif est_growth < -5:  score -= 6

        # SEC EDGAR filing signal
        score += sec_score_delta

        # Congressional trading signal
        score += political_score_delta

        # Geopolitical risk penalty
        geo_lvl = result["geo_risk_level"]
        if geo_lvl == "HIGH":    score -= 8
        elif geo_lvl == "MEDIUM": score -= 3

        result["fundamental_score"] = max(0, min(100, score))

        # Grade
        fs = result["fundamental_score"]
        if fs >= 75:   result["fundamental_grade"] = "A"
        elif fs >= 60: result["fundamental_grade"] = "B"
        elif fs >= 45: result["fundamental_grade"] = "C"
        else:          result["fundamental_grade"] = "D"

        # ── One-line bull / bear case ─────────────────────────────────────────
        bull_parts = []
        bear_parts = []

        if streak >= 3:
            bull_parts.append(f"{streak}Q earnings beat streak")
        if result["analyst_trend"] == "UPGRADING":
            bull_parts.append(result["analyst_trend_detail"] or "analyst upgrades")
        if result["insider_signal"] == "BUYING":
            bull_parts.append(result["insider_detail"])
        if upside and upside > 15:
            bull_parts.append(f"+{upside:.0f}% to analyst target")
        if result["squeeze_potential"]:
            bull_parts.append(f"{result['short_pct_float']:.0f}% float short — squeeze risk")
        if edays and 7 <= edays <= 28:
            bull_parts.append(f"earnings in {edays}d ({result['earnings_date']})")
        if sec_score_delta > 0:
            bull_parts.append(sec_detail.split(":")[1].strip() if ":" in sec_detail else sec_detail)
        if political_score_delta > 0:
            bull_parts.append(political_detail.split(":")[1].strip() if ":" in political_detail else political_detail)
        if est_growth is not None and est_growth > 5:
            bull_parts.append(f"estimates rising +{est_growth:.0f}%")

        if result["analyst_trend"] == "DOWNGRADING":
            bear_parts.append(result["analyst_trend_detail"] or "analyst downgrades")
        if result["insider_signal"] == "SELLING":
            bear_parts.append(result["insider_detail"])
        if geo_lvl == "HIGH":
            bear_parts.append(f"HIGH geo risk: {result['geo_risks'][0] if result['geo_risks'] else ''}")
        if rev and rev < 0:
            bear_parts.append(f"revenue declining ({rev:.1f}% YoY)")
        if streak == 0:
            bear_parts.append("missed last earnings estimate")
        if sec_score_delta < 0:
            bear_parts.append(sec_detail.split(":")[1].strip() if ":" in sec_detail else sec_detail)
        if political_score_delta < 0:
            bear_parts.append("Congress members selling")
        if est_growth is not None and est_growth < -5:
            bear_parts.append(f"estimates falling {est_growth:.0f}%")

        result["bull_case"] = " · ".join(bull_parts[:4]) or "No standout catalysts"
        result["bear_case"] = " · ".join(bear_parts[:3]) or "No major red flags"

    except Exception as e:
        result["error"] = str(e)
        logger.debug(f"[FundamentalContext] {symbol}: {e}")

    return result


def get_fundamental_gate(fund: dict) -> tuple[bool, str]:
    """
    Binary gate: should this symbol's fundamental picture allow a swing trade?

    Returns (allow, reason).

    Blocks if:
      - Analysts actively DOWNGRADING with <40 fundamental score
      - Insider selling heavily + score < 45
      - Earnings within 5 days (binary event — not a swing, it's a gamble)
      - Fundamental grade is D (score < 45)
    """
    score = fund.get("fundamental_score", 50)
    grade = fund.get("fundamental_grade", "C")

    # Hard blocks
    edays = fund.get("earnings_in_days")
    if edays is not None and edays <= 5:
        return False, f"Earnings in {edays} days — binary event risk, skip"

    if grade == "D":
        return False, f"Fundamental grade D (score {score}) — skip"

    if fund.get("analyst_trend") == "DOWNGRADING" and score < 45:
        return False, f"Analysts downgrading + weak score ({score})"

    if fund.get("insider_signal") == "SELLING" and score < 45:
        return False, f"Insiders selling + weak fundamentals ({score})"

    return True, f"Fundamentals OK (grade {grade}, score {score})"


# Simple in-process cache (TTL 4 hours — fundamentals don't change intraday)
_FUND_CACHE: dict[str, tuple[dict, float]] = {}
_FUND_CACHE_TTL = 4 * 3600  # 4 hours


def get_fundamentals_cached(symbol: str) -> dict:
    """Return cached fundamental data, fetching if stale."""
    cached = _FUND_CACHE.get(symbol)
    if cached and (time.time() - cached[1]) < _FUND_CACHE_TTL:
        return cached[0]
    data = get_equity_fundamentals(symbol)
    _FUND_CACHE[symbol] = (data, time.time())
    return data


# ─── Company-specific news via Grok ──────────────────────────────────────────
# Queries Grok for ticker-specific breaking news and sentiment.
# Cached per-symbol for 30 minutes — news moves faster than fundamentals.

_NEWS_CACHE: dict[str, tuple[dict, float]] = {}
_NEWS_CACHE_TTL = 30 * 60  # 30 minutes


_GROK_SYMBOL_NEWS_PROMPT = """\
You are a financial news analyst. For the stock ticker {symbol} ({company_name}, \
sector: {sector}), scan X/Twitter and news sources for the most relevant \
developments RIGHT NOW.

Focus on:
- Earnings results, guidance revisions, revenue surprises
- Analyst upgrades/downgrades, price target changes
- Insider buying/selling activity
- Product launches, partnerships, contract wins
- Regulatory actions, lawsuits, FDA decisions
- Geopolitical events directly impacting this company
- Unusual options activity or institutional moves

Geopolitical risks to watch for this stock: {geo_risks}

Return the top 3 most relevant headlines from the last 48 hours, \
plus an overall sentiment assessment.

Respond ONLY in valid JSON:
{{"headlines": ["<headline 1>", "<headline 2>", "<headline 3>"], \
"sentiment": "BULLISH|BEARISH|NEUTRAL", \
"catalyst_summary": "<one sentence: the single most important thing happening with this stock right now>"}}

If nothing notable is happening, return:
{{"headlines": [], "sentiment": "NEUTRAL", "catalyst_summary": "No significant catalysts detected"}}"""


def get_symbol_news(symbol: str, force: bool = False) -> dict:
    """
    Get company-specific news headlines and sentiment via Grok.

    Returns:
        {
            "headlines": ["headline1", "headline2", "headline3"],
            "sentiment": "BULLISH|BEARISH|NEUTRAL",
            "catalyst_summary": "one sentence summary",
        }

    Cached for 30 minutes per symbol. Returns empty result on any failure.
    """
    default = {"headlines": [], "sentiment": "NEUTRAL", "catalyst_summary": ""}

    if not force:
        cached = _NEWS_CACHE.get(symbol)
        if cached and (time.time() - cached[1]) < _NEWS_CACHE_TTL:
            return cached[0]

    try:
        from config import settings
        if not getattr(settings, "FUNDAMENTAL_NEWS_ENABLED", True):
            return default
        api_key = getattr(settings, "XAI_API_KEY", "") or ""
        if not api_key:
            return default

        import openai
        import json
        import re

        geo = GEO_SECTOR_MAP.get(symbol, _DEFAULT_GEO)
        sector = geo[0]
        geo_risks = ", ".join(geo[1]) if geo[1] else "none identified"

        # Try to get company name from yfinance (cached in info)
        company_name = symbol
        try:
            import yfinance as yf
            t = yf.Ticker(symbol)
            info = t.info or {}
            company_name = info.get("shortName", info.get("longName", symbol))
        except Exception:
            pass

        client = openai.OpenAI(api_key=api_key, base_url="https://api.x.ai/v1")
        resp = client.chat.completions.create(
            model="grok-4.20-0309-reasoning",
            messages=[{"role": "user", "content": _GROK_SYMBOL_NEWS_PROMPT.format(
                symbol=symbol,
                company_name=company_name,
                sector=sector,
                geo_risks=geo_risks,
            )}],
            temperature=0.15,
            max_tokens=300,
            timeout=12,
        )
        text = resp.choices[0].message.content or ""
        text = re.sub(r"```(?:json)?", "", text).strip()
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            data = json.loads(match.group())
            result = {
                "headlines": data.get("headlines", [])[:3],
                "sentiment": data.get("sentiment", "NEUTRAL"),
                "catalyst_summary": data.get("catalyst_summary", ""),
            }
            _NEWS_CACHE[symbol] = (result, time.time())
            logger.debug(f"[SymbolNews] {symbol}: {result['sentiment']} — {result['catalyst_summary'][:60]}")
            return result

    except Exception as e:
        logger.debug(f"[SymbolNews] {symbol}: failed — {e}")

    _NEWS_CACHE[symbol] = (default, time.time())
    return default


def get_fundamentals_with_news(symbol: str) -> dict:
    """
    Get full fundamental data enriched with company-specific news.
    This is the primary function other modules should call.
    """
    fund = get_fundamentals_cached(symbol)
    news = get_symbol_news(symbol)
    fund["recent_headlines"] = news.get("headlines", [])
    fund["news_sentiment"] = news.get("sentiment", "NEUTRAL")
    fund["catalyst_summary"] = news.get("catalyst_summary", "")
    return fund


def format_fundamental_brief(fund: dict) -> str:
    """
    Format fundamental data as a compact string for LLM prompts.
    Includes only non-null, decision-relevant fields.
    """
    parts = []
    sym = fund.get("symbol", "?")

    # Grade + score
    parts.append(f"Grade:{fund.get('fundamental_grade','?')}({fund.get('fundamental_score',50)})")

    # Earnings
    streak = fund.get("eps_beat_streak", 0)
    if streak > 0:
        parts.append(f"EPS:{streak}Q_beats")
    hist = fund.get("earnings_history", [])
    if hist:
        recent = hist[0]
        if recent.get("surprise_pct") is not None:
            parts.append(f"LastQ:{recent['surprise_pct']:+.1f}%surprise")

    # Analyst
    rec = fund.get("analyst_rec")
    if rec:
        parts.append(f"Analyst:{rec}")
    trend = fund.get("analyst_trend", "NEUTRAL")
    if trend != "NEUTRAL":
        parts.append(f"Trend:{trend}")
    upside = fund.get("analyst_upside")
    if upside is not None:
        parts.append(f"Upside:{upside:+.0f}%")

    # Insider
    ins = fund.get("insider_signal", "NEUTRAL")
    if ins != "NEUTRAL":
        detail = fund.get("insider_detail", "")
        parts.append(f"Insider:{ins}" + (f"({detail[:25]})" if detail else ""))

    # Earnings catalyst
    edays = fund.get("earnings_in_days")
    if edays is not None and edays <= 30:
        parts.append(f"EarningsIn:{edays}d({fund.get('earnings_date','')})")

    # Short interest
    short_pct = fund.get("short_pct_float")
    if short_pct and short_pct > 10:
        parts.append(f"Short:{short_pct:.0f}%float")
    if fund.get("squeeze_potential"):
        parts.append("SQUEEZE_RISK")

    # Geo risk
    geo = fund.get("geo_risk_level", "MEDIUM")
    if geo == "HIGH":
        risks = fund.get("geo_risks", [])
        parts.append(f"GeoRisk:HIGH({risks[0][:30] if risks else ''})")

    # News sentiment
    news_sent = fund.get("news_sentiment", "NEUTRAL")
    if news_sent != "NEUTRAL":
        parts.append(f"News:{news_sent}")
    catalyst = fund.get("catalyst_summary", "")
    if catalyst:
        parts.append(f"Catalyst:{catalyst[:50]}")

    # Bull/bear
    bull = fund.get("bull_case", "")
    bear = fund.get("bear_case", "")
    if bull and bull != "No standout catalysts":
        parts.append(f"Bull:{bull[:40]}")
    if bear and bear != "No major red flags":
        parts.append(f"Bear:{bear[:40]}")

    return f"[{sym}] " + " | ".join(parts)
