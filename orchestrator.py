"""
orchestrator.py

Multi-strategy orchestrator — the brain that decides what runs, when, and where.

Each tick the scheduler calls run_all_symbols(), which:

    1. Derives the candidate symbol list from all registered, enabled strategies
    2. For each symbol, queries the registry for eligible strategies
    3. Fetches OHLCV data (one fetch per symbol+timeframe, shared across strategies)
    4. Runs each strategy's prepare() + get_signal()
    5. Resolves conflicts when 2+ strategies disagree on direction for the same symbol
    6. For each approved signal: runs risk checks → places bracket order → logs

Conflict resolution (STRATEGY_CONFLICT_RESOLUTION in .env):
    PRIORITY — highest-priority strategy (lowest .priority value) wins
    SKIP     — no trade is taken on that symbol this tick

Adding a new strategy
─────────────────────
1. Subclass AbstractStrategy in strategy/<name>.py
2. Decorate with @register
3. Set name, symbols, timeframe_minutes, priority
4. Implement is_eligible(), prepare(), get_signal()
5. Add strategy.name to STRATEGY_ENABLED in .env (default false)
6. The orchestrator picks it up automatically — no changes needed here.
"""

import logging
import threading
from datetime import datetime
from typing import Optional

import pytz

from config import settings
from data.fetcher import fetch_historical
from data.validator import validate_ohlcv, DataQualityError
from data.trade_log import log_trade, log_event
from risk.manager import RiskBlock, check_all, register_trade
from execution.router import router as _router
from monitor.alerts import (
    notify_entry,
    notify_risk_block,
)

# Trigger strategy auto-registration by importing their modules.
# Each module-level @register decorator fires on import.
import strategy.break_retest    # noqa: F401
import strategy.vwap_reversion  # noqa: F401
import strategy.donchian        # noqa: F401
import strategy.orb             # noqa: F401
import strategy.rsi2_daily      # noqa: F401

from strategy.registry import get_eligible, get_all

logger = logging.getLogger("orchestrator")
ET = pytz.timezone("America/New_York")

# ─── Strategy-specific pre-execution Telegram alerts ─────────────────────────
# Add entries here when a strategy gets its own notify function in monitor/alerts.py
_SIGNAL_NOTIFIERS: dict = {}

try:
    from monitor.alerts import notify_brt_signal
    _SIGNAL_NOTIFIERS["BRT"] = notify_brt_signal
except ImportError:
    pass

try:
    from monitor.alerts import notify_vwap_signal
    _SIGNAL_NOTIFIERS["VWAP_MR"] = notify_vwap_signal
except ImportError:
    pass


# ─── Active symbol list ───────────────────────────────────────────────────────

def _active_symbols() -> list[str]:
    """
    Return the deduplicated list of symbols that have at least one enabled strategy.
    Intersected with ACTIVE_SYMBOLS so the operator can pin the universe in .env.
    """
    universe = set(settings.ACTIVE_SYMBOLS)
    covered: set[str] = set()
    for strategy in get_all():
        if settings.STRATEGY_ENABLED.get(strategy.name, False):
            covered.update(s for s in strategy.symbols if s in universe)
    return sorted(covered)


# ─── Data fetch cache (per tick) ─────────────────────────────────────────────

def _fetch_cached(
    cache: dict,
    symbol: str,
    timeframe_minutes: int,
) -> Optional[object]:
    """
    Return OHLCV data for (symbol, timeframe), fetching once and caching the result.
    Returns None on any data or quality failure.
    """
    key = (symbol, timeframe_minutes)
    if key in cache:
        return cache[key]

    # yfinance period caps: 5m/15m → 60d max; 60m → 730d; daily → 5y
    period = "60d" if timeframe_minutes <= 60 else "2y"
    try:
        df = fetch_historical(symbol, period=period, timeframe_minutes=timeframe_minutes)
        validate_ohlcv(df, timeframe_minutes=timeframe_minutes)
        cache[key] = df
        return df
    except DataQualityError as dqe:
        logger.warning(f"Data quality [{symbol} {timeframe_minutes}m]: {dqe}")
        try:
            log_event(
                f"Data quality fail — {symbol} {timeframe_minutes}m",
                "WARN",
                str(dqe),
            )
        except Exception:
            pass
        return None
    except Exception as exc:
        logger.warning(f"Data fetch failed [{symbol} {timeframe_minutes}m]: {exc}")
        return None


# ─── Conflict resolution ──────────────────────────────────────────────────────

def _resolve_conflicts(
    pairs: list[tuple],
    symbol: str,
) -> list[tuple]:
    """
    Given [(strategy, signal_dict), ...] for one symbol, filter direction conflicts.

    Rules:
      - Drop pairs where signal == 0 (no trade).
      - If all remaining agree on direction → keep all.
      - If directions conflict → apply STRATEGY_CONFLICT_RESOLUTION:
            PRIORITY : keep only the highest-priority strategy (lowest .priority)
            SKIP     : return [] (no trade this tick for this symbol)
    """
    active = [(s, sig) for s, sig in pairs if sig.get("signal", 0) != 0]
    if not active:
        return []

    directions = {sig["signal"] for _, sig in active}
    if len(directions) == 1:
        return active  # unanimous — all eligible strategies agree

    # Conflict detected
    names = [s.name for s, _ in active]
    logger.info(
        f"[{symbol}] Strategy conflict: {names} → directions={directions}"
    )
    try:
        log_event(
            f"Strategy conflict on {symbol}",
            "WARN",
            f"Strategies: {names}  Directions: {directions}",
        )
    except Exception:
        pass

    if settings.STRATEGY_CONFLICT_RESOLUTION == "SKIP":
        logger.info(f"[{symbol}] Conflict resolution: SKIP — no trade this tick")
        return []

    # PRIORITY: lowest .priority number wins
    winner = min(active, key=lambda x: x[0].priority)
    logger.info(
        f"[{symbol}] Conflict resolution: PRIORITY — {winner[0].name} wins"
    )
    return [winner]


# ─── Single-symbol strategy runner ───────────────────────────────────────────

def run_strategies(
    symbol: str,
    fundamentals: dict,
    regime_info: dict,
    regime_params: dict,
    equity: float,
    session: dict,
) -> list[dict]:
    """
    Run all eligible strategies for *symbol* and execute approved signals.

    Args:
        symbol        : Trading symbol (e.g. "MES")
        fundamentals  : Live fundamentals dict (vix, yield_10y, dxy, spy_vol_ratio)
        regime_info   : Regime info dict (regime, adx_min, sl_buffer, tp_rr, ...)
        regime_params : Regime parameter dict forwarded to strategy.prepare()
        equity        : Current account equity
        session       : Mutable session state dict (trades_today, start_equity, ...)

    Returns:
        List of executed-trade dicts (one per placed order).
    """
    regime      = regime_info.get("regime", "NORMAL")
    session_hour = datetime.now(ET).hour

    # 1. Query registry
    eligible = get_eligible(symbol, regime, session_hour, fundamentals)
    if not eligible:
        logger.debug(f"[{symbol}] No eligible strategies this tick")
        return []

    logger.info(
        f"[{symbol}] Eligible: {[s.name for s in eligible]}"
    )

    # 2. Fetch data (one fetch per (symbol, timeframe))
    data_cache: dict = {}
    pairs: list[tuple] = []

    for strategy in eligible:
        df_raw = _fetch_cached(data_cache, symbol, strategy.timeframe_minutes)
        if df_raw is None:
            logger.warning(f"[{symbol}] {strategy.name}: data unavailable — skipping")
            continue

        try:
            long_only = symbol in settings.LONG_ONLY_SYMBOLS
            df = strategy.prepare(
                df_raw.copy(),
                long_only=long_only,
                regime_params=regime_params,
            )
            sig = strategy.get_signal(df, regime_params=regime_params)
            sig["strategy"] = strategy.name
            sig["symbol"]   = symbol
            pairs.append((strategy, sig))

            logger.info(
                f"[{symbol}] {strategy.name}: "
                f"signal={sig.get('signal', 0):+d}  "
                f"close={sig.get('close', 0):.2f}"
            )

            # Pre-execution Telegram alert (fires before risk/execution)
            if sig.get("signal", 0) != 0:
                notifier = _SIGNAL_NOTIFIERS.get(strategy.name)
                if notifier:
                    try:
                        notifier(sig)
                    except Exception:
                        pass

        except Exception as exc:
            logger.warning(
                f"[{symbol}] {strategy.name} signal generation failed: {exc}",
                exc_info=True,
            )

    if not pairs:
        return []

    # 3. Resolve conflicts
    approved = _resolve_conflicts(pairs, symbol)
    if not approved:
        return []

    # 4. Execute each approved signal
    results: list[dict] = []
    for strategy, sig in approved:
        if sig.get("signal", 0) == 0:
            continue
        result = _execute_signal(
            symbol       = symbol,
            strategy     = strategy,
            sig          = sig,
            fundamentals = fundamentals,
            regime_info  = regime_info,
            equity       = equity,
            session      = session,
        )
        if result:
            results.append(result)

    return results


# ─── All-symbols runner ───────────────────────────────────────────────────────

def run_all_symbols(
    fundamentals: dict,
    regime_info: dict,
    regime_params: dict,
    equity: float,
    session: dict,
) -> list[dict]:
    """
    Run strategies for every active symbol.

    Called once per scheduler tick. Returns all executed-trade dicts.
    """
    symbols = _active_symbols()
    if not symbols:
        logger.warning("Orchestrator: no active symbols — check STRATEGY_ENABLED in .env")
        return []

    all_results: list[dict] = []
    for symbol in symbols:
        try:
            results = run_strategies(
                symbol       = symbol,
                fundamentals = fundamentals,
                regime_info  = regime_info,
                regime_params = regime_params,
                equity       = equity,
                session      = session,
            )
            all_results.extend(results)
        except Exception as exc:
            logger.error(f"[{symbol}] Unhandled error in run_strategies: {exc}", exc_info=True)

    return all_results


# ─── Signal execution ─────────────────────────────────────────────────────────

def _execute_signal(
    symbol: str,
    strategy,
    sig: dict,
    fundamentals: dict,
    regime_info: dict,
    equity: float,
    session: dict,
) -> Optional[dict]:
    """
    Run risk checks and place a bracket order for one approved signal.
    Returns a result dict on success, None if blocked or failed.

    Gate order (each can veto independently):
        1. COT filter              — CFTC positioning extremes
        1b. Fundamental gate       — equity fundamental intelligence (stocks only)
        2. Performance monitor     — rolling win rate (BRT only)
        3. News halt               — HIGH-impact breaking news pause window
        4. News signal gate        — Grok directional assessment vs algo direction
        5. LLM selector gate       — ensemble (Grok+GPT-4+Claude) strategy/bias gate
        6. Advisory quality gate   — prior-tick signal_quality + macro_supports
        7. Risk checks             — equity, drawdown, heat, position sizing
    """
    from strategy.cot_filter import get_cot_bias, COT_BIAS_SHORT

    direction   = int(sig["signal"])
    entry_price = float(sig["close"])
    sl_price    = float(sig.get("stop_loss") or 0)
    tp_price    = float(sig.get("take_profit") or 0)
    level_type  = sig.get("level_type", strategy.name)
    sweep_flag  = int(sig.get("liquidity_sweep", 0))
    direction_str = "LONG" if direction == 1 else "SHORT"

    # Stamp strategy_type into the signal for risk manager
    strategy_type = getattr(strategy, "strategy_type", "intraday")
    sig["strategy_type"] = strategy_type

    # ── COT filter (MES longs) ────────────────────────────────────────────────
    cot_bias = "NEUTRAL"
    if settings.COT_FILTER_ENABLED:
        try:
            cot_bias = get_cot_bias(symbol)
        except Exception:
            pass

    if direction == 1 and cot_bias == COT_BIAS_SHORT:
        logger.info(
            f"[{symbol}] {strategy.name}: COT filter blocked LONG "
            "(Leveraged Funds at extreme net long)"
        )
        try:
            log_event(
                f"COT filter blocked LONG on {symbol}",
                "WARN",
                f"Strategy={strategy.name}",
            )
        except Exception:
            pass
        return None

    # ── Fundamental gate (equity strategies — stocks only) ────────────────────
    # Blocks swing/equity trades when company fundamentals are weak.
    # Skipped for futures symbols (MES, MNQ, MGC, SIL) — they use macro regime.
    _futures_symbols = {"MES", "MNQ", "MGC", "SIL", "ES", "NQ", "GC", "SI"}
    if settings.FUNDAMENTAL_GATE_ENABLED and symbol not in _futures_symbols:
        try:
            from data.equity_fundamentals import get_fundamentals_cached, get_fundamental_gate
            fund = get_fundamentals_cached(symbol)
            allowed, reason = get_fundamental_gate(fund)
            if not allowed:
                logger.info(
                    f"[{symbol}] {strategy.name}: FUNDAMENTAL GATE BLOCKED — {reason}"
                )
                try:
                    log_event(
                        f"Fundamental gate blocked {symbol} {strategy.name}",
                        "WARN",
                        reason,
                    )
                    notify_risk_block(
                        symbol=symbol,
                        strategy_name=strategy.name,
                        reason=f"Fundamental gate: {reason}",
                    )
                except Exception:
                    pass
                return None
            else:
                logger.debug(f"[{symbol}] Fundamental gate: {reason}")
        except ImportError:
            pass  # equity_fundamentals not available — proceed

    # ── Performance monitor gate (BRT only) ───────────────────────────────────
    if strategy.name == "BRT":
        try:
            from monitor.performance import brt_monitor
            if brt_monitor.get_status() == "PAUSE":
                raise RiskBlock(
                    "Performance monitor: BRT entries paused — "
                    "rolling win rate below threshold."
                )
        except RiskBlock:
            raise
        except Exception:
            pass

    # ── News halt gate ────────────────────────────────────────────────────────
    # If a HIGH-impact news event was detected recently and NEWS_HALT_ENABLED=true,
    # all new entries are paused for NEWS_HALT_MINUTES.
    try:
        from monitor.news_monitor import is_news_halt_active
        if is_news_halt_active():
            logger.info(
                f"[{symbol}] {strategy.name}: news halt active — "
                f"skipping entry (HIGH-impact event window)"
            )
            try:
                log_event(
                    f"News halt — {symbol} {strategy.name} entry skipped",
                    "WARN",
                    "HIGH-impact news event active",
                )
            except Exception:
                pass
            return None
    except Exception:
        pass  # news monitor not available — proceed

    # ── News signal gate + size boost ─────────────────────────────────────────
    # Gate 1: if Grok assessed a directional signal from breaking news and it
    #   OPPOSES the algo direction → block entry.
    # Gate 2: if news CONFIRMS algo direction with high confidence → apply
    #   a size boost (NEWS_SIZE_BOOST_FACTOR) as a reward for confluence.
    news_boost = 1.0
    news_sig   = None

    if settings.NEWS_TRADE_ENABLED:
        try:
            from monitor.news_monitor import get_active_news_signal
            news_sig = get_active_news_signal()
        except Exception:
            pass

    if news_sig:
        news_dir = news_sig.get("direction", "NEUTRAL")
        news_conf = float(news_sig.get("confidence", 0))
        news_algo_dir = "BULLISH" if direction == 1 else "BEARISH"

        if news_dir not in ("NEUTRAL", "") and news_dir != news_algo_dir:
            # News opposes signal — block
            logger.warning(
                f"[{symbol}] {strategy.name}: NEWS BLOCK — "
                f"{news_dir} (conf={news_conf:.0%}) opposes {direction_str} | "
                f"{news_sig.get('headline', '')[:60]}"
            )
            try:
                from monitor.alerts import notify_news_trade_block
                notify_news_trade_block(
                    brt_direction  = news_algo_dir,
                    news_direction = news_dir,
                    confidence     = news_conf,
                    headline       = news_sig.get("headline", ""),
                    reason         = news_sig.get("reason", ""),
                )
            except Exception:
                pass
            try:
                log_event(
                    f"News block — {symbol} {direction_str}",
                    "WARN",
                    f"{news_dir} ({news_conf:.0%} conf): {news_sig.get('headline','')[:80]}",
                )
            except Exception:
                pass
            return None

        elif news_dir == news_algo_dir:
            logger.info(
                f"[{symbol}] NEWS CONFIRMS {direction_str} "
                f"(conf={news_conf:.0%}) | {news_sig.get('headline','')[:60]}"
            )
            # Apply size boost if confidence is high enough
            if news_conf >= settings.NEWS_BOOST_CONFIDENCE_MIN:
                news_boost = settings.NEWS_SIZE_BOOST_FACTOR
                logger.info(
                    f"[{symbol}] News size boost: {news_boost:.2f}x "
                    f"(conf={news_conf:.0%} >= threshold {settings.NEWS_BOOST_CONFIDENCE_MIN:.0%})"
                )

    # ── LLM selector gate ─────────────────────────────────────────────────────
    # The LLM selector (Grok + GPT-4 + Claude ensemble) was pre-run at the start
    # of this tick and cached in monitor/llm_gate.py. Reading the cache is instant.
    #
    # Blocking rules (LLM_GATE_ENABLED=true + confidence >= LLM_GATE_CONFIDENCE_MIN):
    #   - LLM says FLAT → skip entry
    #   - LLM bias opposes algo direction → skip entry
    # Boost rule:
    #   - LLM bias confirms direction with confidence >= 0.75 → small size boost
    llm_boost = 1.0

    if settings.LLM_GATE_ENABLED:
        try:
            from monitor.llm_gate import get_llm_selection
            llm = get_llm_selection()
        except Exception:
            llm = {}

        llm_strategy = llm.get("strategy", "")
        llm_bias     = llm.get("bias", "NEUTRAL")
        llm_conf     = float(llm.get("confidence", 0.0))
        llm_reason   = llm.get("reasoning", "")

        if llm_strategy and llm_conf >= settings.LLM_GATE_CONFIDENCE_MIN:

            if llm_strategy == "FLAT":
                logger.info(
                    f"[{symbol}] {strategy.name}: LLM gate — FLAT "
                    f"(conf={llm_conf:.0%}) | {llm_reason[:80]}"
                )
                try:
                    from monitor.alerts import notify_llm_gate_block
                    notify_llm_gate_block(
                        strategy_name = strategy.name,
                        direction     = direction_str,
                        llm_strategy  = llm_strategy,
                        llm_bias      = llm_bias,
                        confidence    = llm_conf,
                        reasoning     = llm_reason,
                    )
                except Exception:
                    pass
                try:
                    log_event(
                        f"LLM gate blocked {symbol} {direction_str}",
                        "WARN",
                        f"LLM=FLAT ({llm_conf:.0%}): {llm_reason[:80]}",
                    )
                except Exception:
                    pass
                return None

            elif llm_bias not in ("NEUTRAL", "") and llm_bias != direction_str:
                logger.info(
                    f"[{symbol}] {strategy.name}: LLM gate — bias {llm_bias} "
                    f"opposes {direction_str} (conf={llm_conf:.0%})"
                )
                try:
                    from monitor.alerts import notify_llm_gate_block
                    notify_llm_gate_block(
                        strategy_name = strategy.name,
                        direction     = direction_str,
                        llm_strategy  = llm_strategy,
                        llm_bias      = llm_bias,
                        confidence    = llm_conf,
                        reasoning     = llm_reason,
                    )
                except Exception:
                    pass
                try:
                    log_event(
                        f"LLM gate blocked {symbol} {direction_str}",
                        "WARN",
                        f"LLM bias={llm_bias} ({llm_conf:.0%}): {llm_reason[:80]}",
                    )
                except Exception:
                    pass
                return None

            elif llm_bias == direction_str and llm_conf >= 0.75:
                # LLM confirms — small reward boost (scaled linearly from 0.75 to 1.0 conf)
                llm_boost = round(1.0 + (llm_conf - 0.75) * 0.6, 2)  # max +15% at conf=1.0
                logger.info(
                    f"[{symbol}] LLM confirms {direction_str} (conf={llm_conf:.0%}) "
                    f"— size boost {llm_boost:.2f}x"
                )

    # ── Advisory quality gate ─────────────────────────────────────────────────
    # Uses the advisory result from the PREVIOUS tick (stored in llm_gate cache).
    # If signal_quality=LOW AND macro_supports=False → skip.
    # This uses recent AI assessment without any execution-path latency.
    if settings.LLM_QUALITY_GATE_ENABLED:
        try:
            from monitor.llm_gate import get_advisory_result
            adv = get_advisory_result()
        except Exception:
            adv = {}

        # Fallback: if scheduler advisory is empty, try screener advisory written
        # by the dashboard's background LLM worker (cross-process via bot_state).
        if not adv:
            try:
                import json as _json
                from data.trade_log import get_bot_state
                raw = (get_bot_state() or {}).get("screener_advisory")
                if raw:
                    adv = _json.loads(raw)
            except Exception:
                pass

        if adv:
            quality        = adv.get("signal_quality", "N/A")
            macro_supports = adv.get("macro_supports")
            risk_flags     = adv.get("risk_flags", [])
            trade_idea     = adv.get("trade_idea") or {}
            idea_dir       = trade_idea.get("direction", "FLAT")
            idea_conf      = float(trade_idea.get("confidence") or 0.0)

            # ── Trade idea: oppose → block ─────────────────────────────────
            if (idea_dir in ("LONG", "SHORT")
                    and idea_conf >= settings.LLM_GATE_CONFIDENCE_MIN
                    and idea_dir != direction_str):
                logger.info(
                    f"[{symbol}] {strategy.name}: LLM trade idea opposes signal "
                    f"({idea_dir} vs {direction_str}, conf={idea_conf:.2f}) — blocked"
                )
                try:
                    log_event(
                        f"LLM idea blocked {symbol} {direction_str}",
                        "WARN",
                        f"LLM wants {idea_dir} (conf={idea_conf:.2f}) — thesis: {trade_idea.get('thesis','')}",
                    )
                except Exception:
                    pass
                return None

            # ── Trade idea: align → size boost ─────────────────────────────
            if (idea_dir == direction_str
                    and idea_conf >= settings.LLM_GATE_CONFIDENCE_MIN):
                idea_boost = 1.0 + (idea_conf - settings.LLM_GATE_CONFIDENCE_MIN)
                llm_boost  = min(1.5, llm_boost * idea_boost)
                logger.info(
                    f"[{symbol}] {strategy.name}: LLM idea aligns ({idea_dir}, "
                    f"conf={idea_conf:.2f}) — size boost {llm_boost:.2f}x"
                )

            # ── Standard quality gate ──────────────────────────────────────
            if quality == "LOW" and macro_supports is False:
                logger.info(
                    f"[{symbol}] {strategy.name}: advisory quality gate blocked — "
                    f"quality={quality} macro_supports={macro_supports} "
                    f"flags={risk_flags}"
                )
                try:
                    from monitor.alerts import notify_llm_quality_gate_block
                    notify_llm_quality_gate_block(
                        strategy_name  = strategy.name,
                        direction      = direction_str,
                        signal_quality = quality,
                        macro_supports = bool(macro_supports),
                        risk_flags     = risk_flags,
                    )
                except Exception:
                    pass
                try:
                    log_event(
                        f"Advisory quality gate blocked {symbol} {direction_str}",
                        "WARN",
                        f"quality={quality} macro_supports={macro_supports} flags={risk_flags}",
                    )
                except Exception:
                    pass
                return None

    # ── Combined size boost (news × LLM, capped at 2.0x) ─────────────────────
    combined_boost = min(2.0, news_boost * llm_boost)
    if combined_boost != 1.0:
        logger.info(
            f"[{symbol}] Combined size boost: {combined_boost:.2f}x "
            f"(news={news_boost:.2f}x LLM={llm_boost:.2f}x)"
        )

    try:
        open_pos  = _router.get_position(symbol)
        contracts = check_all(
            symbol,
            fundamentals,
            equity,
            open_pos,
            sig,
            trades_today=session.get("trades_today", 0),
            size_boost=combined_boost,
        )

        boost_tag = f"  [BOOST {combined_boost:.2f}x]" if combined_boost > 1.0 else ""
        logger.info(
            f"[{symbol}] {strategy.name} → placing {direction_str} "
            f"x{contracts} | entry≈{entry_price:.2f} "
            f"SL={sl_price:.2f} TP={tp_price:.2f} COT={cot_bias}"
            f"{'  [SWEEP ✓]' if sweep_flag else ''}{boost_tag}"
        )

        # Send news size boost Telegram alert (when applicable)
        if news_boost > 1.0 and news_sig:
            try:
                from monitor.alerts import notify_news_size_boost
                notify_news_size_boost(
                    direction  = direction_str,
                    confidence = float(news_sig.get("confidence", 0)),
                    boost      = combined_boost,
                    contracts  = contracts,
                    headline   = news_sig.get("headline", ""),
                )
            except Exception:
                pass

        _router.place_bracket_order(
            symbol    = symbol,
            qty       = contracts,
            sl_price  = sl_price,
            tp_price  = tp_price,
            direction = direction,
        )

        # ── Register open trade for portfolio heat + breakeven tracking ───────
        try:
            register_trade(
                symbol        = symbol,
                direction     = direction,
                qty           = contracts,
                entry         = entry_price,
                stop          = sl_price,
                tp            = tp_price,
                strategy_type = strategy_type,
            )
        except Exception as reg_err:
            logger.warning(f"[{symbol}] register_trade failed (non-fatal): {reg_err}")

        # ── Logging ───────────────────────────────────────────────────────────
        boost_note = f"  boost={combined_boost:.2f}x" if combined_boost > 1.0 else ""
        try:
            log_event(
                f"{direction_str} entry — {level_type} @ {entry_price:.2f}",
                "TRADE",
                (
                    f"Strategy={strategy.name}  "
                    f"SL={sl_price:.2f}  TP={tp_price:.2f}  "
                    f"{contracts} contract(s)  COT={cot_bias}{boost_note}"
                ),
            )
        except Exception:
            pass

        try:
            log_trade(
                direction       = direction_str,
                level_type      = level_type,
                entry_price     = entry_price,
                stop_loss       = sl_price,
                take_profit     = tp_price,
                contracts       = contracts,
                regime          = regime_info.get("regime"),
                vix             = fundamentals.get("vix"),
                liquidity_sweep = sweep_flag,
                cot_bias        = cot_bias,
            )
        except Exception as db_err:
            logger.warning(f"Trade log write failed: {db_err}")

        session["trades_today"] = session.get("trades_today", 0) + 1

        notify_entry(
            contracts    = contracts,
            entry_price  = entry_price,
            sl_price     = sl_price,
            tp_price     = tp_price,
            level_type   = level_type,
            retest_level = float(sig.get("retest_level", entry_price)),
            direction    = direction_str,
        )

        return {
            "strategy":    strategy.name,
            "symbol":      symbol,
            "direction":   direction,
            "contracts":   contracts,
            "entry_price": entry_price,
            "sl_price":    sl_price,
            "tp_price":    tp_price,
        }

    except RiskBlock as rb:
        logger.warning(f"[{symbol}] {strategy.name} risk block: {rb}")
        notify_risk_block(str(rb))
        try:
            log_event(
                f"Risk block: {rb}",
                "WARN",
                f"{strategy.name} on {symbol}",
            )
        except Exception:
            pass
        return None
