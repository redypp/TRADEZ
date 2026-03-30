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
from risk.manager import RiskBlock, check_all
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
    """
    from strategy.cot_filter import get_cot_bias, COT_BIAS_SHORT

    direction   = int(sig["signal"])
    entry_price = float(sig["close"])
    sl_price    = float(sig.get("stop_loss") or 0)
    tp_price    = float(sig.get("take_profit") or 0)
    level_type  = sig.get("level_type", strategy.name)
    sweep_flag  = int(sig.get("liquidity_sweep", 0))

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

    try:
        open_pos  = _router.get_position(symbol)
        contracts = check_all(
            symbol,
            fundamentals,
            equity,
            open_pos,
            sig,
            trades_today=session.get("trades_today", 0),
        )

        direction_str = "LONG" if direction == 1 else "SHORT"
        logger.info(
            f"[{symbol}] {strategy.name} → placing {direction_str} "
            f"x{contracts} | entry≈{entry_price:.2f} "
            f"SL={sl_price:.2f} TP={tp_price:.2f} COT={cot_bias}"
            f"{'  [SWEEP ✓]' if sweep_flag else ''}"
        )

        _router.place_bracket_order(
            symbol    = symbol,
            qty       = contracts,
            sl_price  = sl_price,
            tp_price  = tp_price,
            direction = direction,
        )

        # ── Logging ───────────────────────────────────────────────────────────
        try:
            log_event(
                f"{direction_str} entry — {level_type} @ {entry_price:.2f}",
                "TRADE",
                (
                    f"Strategy={strategy.name}  "
                    f"SL={sl_price:.2f}  TP={tp_price:.2f}  "
                    f"{contracts} contract(s)  COT={cot_bias}"
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
