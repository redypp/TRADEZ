"""
scheduler.py

Automated multi-strategy trading bot.

How it works:
    - APScheduler fires every 15 min (Mon–Fri, 9am–4pm ET)
    - Each tick: authenticates → checks daily drawdown → fetches fundamentals →
      calls the orchestrator, which queries the strategy registry, fetches data
      per timeframe, runs each eligible strategy, resolves direction conflicts,
      and places bracket orders for all approved signals
    - A second job at 15:30 ET sends the daily summary
    - On startup, records session_start_equity once so drawdown is tracked

Strategies are enabled/disabled in .env:
    STRATEGY_BRT_ENABLED=true
    STRATEGY_VWAP_MR_ENABLED=false
    STRATEGY_DONCHIAN_ENABLED=false
    STRATEGY_ORB_ENABLED=false
    STRATEGY_RSI2_ENABLED=false

Adding a new strategy: subclass AbstractStrategy, decorate with @register,
and set its STRATEGY_<NAME>_ENABLED=true in .env. No changes to this file needed.

Usage:
    python scheduler.py               # demo account (PAPER_TRADING=true)
    PAPER_TRADING=false python scheduler.py  # live — only when you're ready

Stopping:
    Ctrl-C   — graceful shutdown (sends Telegram alert)
"""

import logging
import os
import sys
import threading
import time
from datetime import datetime, date
from pathlib import Path

os.makedirs("logs", exist_ok=True)

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz

from config import settings
from data.fundamentals import get_live_fundamentals, print_fundamentals
from data.trade_log import init_db, log_event, update_bot_state, get_daily_summary
from strategy.break_retest import get_latest_brt_signal, prepare_break_retest
from strategy.vwap_reversion import prepare_vwap_reversion, get_latest_vwap_mr_signal
from strategy.volume_profile import vpoc_trend
from strategy.regime import get_regime_params, get_regime_info
from risk.manager import (
    RiskBlock, check_daily_drawdown,
    load_open_trades_from_db, check_breakeven_moves,
)
from execution.router import router as _router, FUTURES_SYMBOLS
from monitor.alerts import (
    notify_signal_check,
    notify_daily_summary,
    notify_error,
    notify_llm_advisory,
)
from orchestrator import run_all_symbols

# ─── Logging ─────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("logs/tradez.log"),
    ],
)
logger = logging.getLogger("scheduler")

# ─── Session state (reset each trading day) ──────────────────────────────────

ET = pytz.timezone("America/New_York")

_session: dict = {
    "start_equity":   0.0,
    "trades_today":   0,
    "pnl_today":      0.0,
    "last_trade_date": None,
}


# ─── AI Advisory (background thread helper) ──────────────────────────────────

def _run_advisory(market_ctx: dict, strategy_id: str,
                  signal_direction: str, trigger: str) -> None:
    """
    Runs in a daemon thread — never blocks the execution path.
    Fetches LLM advisory then pushes it to:
        1. monitor/llm_gate advisory cache (used as quality gate on next tick)
        2. SQLite bot_state (dashboard picks it up via WebSocket)
        3. SQLite events feed (dashboard activity log)
        4. Telegram (optional — only on SIGNAL or PRE_MARKET triggers)
    """
    try:
        from strategy.llm_advisory import get_advisory
        from data.trade_log import log_event, update_bot_state
        import json as _json

        advisory = get_advisory(
            market_data=market_ctx,
            strategy_id=strategy_id,
            signal_direction=signal_direction,
            trigger=trigger,
        )

        # 1. Store in LLM gate cache so next tick can use it as a quality gate
        try:
            from monitor.llm_gate import update_advisory
            update_advisory(advisory)
        except Exception:
            pass

        # 2. Persist in bot_state for dashboard
        try:
            update_bot_state({"llm_advisory": _json.dumps(advisory)})
        except Exception:
            pass

        # 3. Log to events feed
        flags_str = " | ".join(advisory.get("risk_flags", [])) or "none"
        try:
            log_event(
                f"AI: {advisory.get('headline', '')}",
                "AI",
                f"{advisory.get('brief', '')}  |  Flags: {flags_str}",
            )
        except Exception:
            pass

        # 4. Telegram — only for signals and pre-market (not every quiet hour)
        if trigger in ("SIGNAL", "PRE_MARKET"):
            try:
                notify_llm_advisory(advisory)
            except Exception:
                pass

        logger.info(f"[Advisory] Done — {advisory.get('headline', '')}")

    except Exception as e:
        logger.warning(f"[Advisory] Background thread failed: {e}")


# ─── Tradovate helpers ────────────────────────────────────────────────────────

def _ensure_auth(max_attempts: int = 3) -> None:
    """
    Authenticate all brokers with exponential backoff retry.
    Retries up to max_attempts times before raising.
    Without retry, a single auth failure at :02 past the hour blocks the entire hour.
    """
    last_err = None
    for attempt in range(1, max_attempts + 1):
        try:
            _router.connect_all()
            if attempt > 1:
                logger.info(f"Auth succeeded on attempt {attempt}")
            return
        except Exception as e:
            last_err = e
            wait = 2 ** attempt  # 2s, 4s, 8s
            logger.warning(
                f"Auth attempt {attempt}/{max_attempts} failed: {e}. "
                f"Retrying in {wait}s…"
            )
            time.sleep(wait)
    raise ConnectionError(f"Auth failed after {max_attempts} attempts: {last_err}")


def _safe_get_equity() -> float:
    """
    Return confirmed account equity from Tradovate.

    If the API returns 0 or raises, behaviour depends on EQUITY_FALLBACK in .env:
        EQUITY_FALLBACK=0 (default) — raises EquityUnavailable, halting the tick.
            No trade is placed without confirmed equity. Safe by default.
        EQUITY_FALLBACK=<amount>    — uses that value as emergency fallback.
            Only set this if you know your account balance and accept the risk.

    Raises:
        EquityUnavailable if equity cannot be confirmed and no fallback is set.
    """
    try:
        portfolio = _router.get_portfolio()
        equity = portfolio.total_equity
        if equity > 0:
            return equity
        # API returned 0 — treat same as failure
        raise ValueError("Broker returned equity of 0")
    except Exception as e:
        fallback = settings.EQUITY_FALLBACK
        if fallback > 0:
            logger.warning(
                f"Could not confirm equity ({e}). "
                f"Using configured fallback: ${fallback:,.2f}. "
                f"Risk calculations are based on this figure."
            )
            try:
                notify_error(
                    f"⚠️ Equity fetch failed — trading on fallback ${fallback:,.2f}. "
                    f"Verify account balance immediately."
                )
            except Exception:
                pass
            return fallback
        # No fallback configured — halt this tick entirely
        raise EquityUnavailable(
            f"Cannot confirm account equity ({e}). "
            f"Set EQUITY_FALLBACK in .env to allow trading on estimated balance, "
            f"or this tick will be skipped to protect the risk model."
        ) from e


class EquityUnavailable(Exception):
    """Raised when account equity cannot be confirmed and no fallback is configured."""
    pass


# ─── Daily session initialiser ────────────────────────────────────────────────

def _init_session_if_new_day(equity: float) -> None:
    """Record start-of-day equity once per calendar day."""
    today = date.today()
    if _session["last_trade_date"] != today:
        _session["start_equity"]    = equity
        _session["trades_today"]    = 0
        _session["pnl_today"]       = 0.0
        _session["last_trade_date"] = today
        logger.info(f"New trading day — session equity locked at ${equity:,.2f}")


# ─── Main hourly signal job ───────────────────────────────────────────────────

_HALT_FILE = Path(__file__).parent / "HALT"


def is_halted() -> bool:
    """Check if the kill switch is active (HALT file exists in project root)."""
    return _HALT_FILE.exists()


def run_signal_check() -> None:
    """
    Core job. Runs every 15 min, Mon–Fri, 9am–4pm ET.

    Sequence:
        0. Check kill switch (HALT file) — if present, flatten and skip
        1. Authenticate all brokers
        2. Get account equity → init session if new day
        3. Check daily drawdown (raises RiskBlock if hit)
        4. Fetch live fundamentals → determine regime
        5. Call orchestrator.run_all_symbols() — runs every eligible strategy
           across every active symbol, resolves conflicts, places orders
        6. Update dashboard state (SQLite) + send Telegram summary
        7. Run AI advisory in background thread
    """
    # ── Kill switch ───────────────────────────────────────────────────────
    if is_halted():
        logger.critical("HALT file detected — emergency stop active. Remove HALT file to resume.")
        try:
            _router.connect_all()
            results = _router.close_all_positions()
            if results:
                logger.critical(f"HALT: flattened {len(results)} position(s)")
                notify_error(f"🛑 HALT ACTIVE — flattened {len(results)} position(s). Remove HALT file to resume.")
            else:
                notify_error("🛑 HALT ACTIVE — no positions to close. Remove HALT file to resume.")
        except Exception as e:
            logger.error(f"HALT flatten failed: {e}")
            notify_error(f"🛑 HALT ACTIVE but flatten failed: {e}")
        return

    logger.info("─── Signal check starting ───")
    try:
        log_event("Signal check started", "INFO")
    except Exception:
        pass

    try:
        _ensure_auth()

        # ── Equity & session init ─────────────────────────────────────────
        equity = _safe_get_equity()
        _init_session_if_new_day(equity)

        # ── Daily drawdown gate ───────────────────────────────────────────
        check_daily_drawdown(equity, _session["start_equity"])

        # ── Live fundamentals ─────────────────────────────────────────────
        fundamentals = get_live_fundamentals()
        print_fundamentals(fundamentals)

        # ── Regime detection ──────────────────────────────────────────────
        regime_info   = get_regime_info(fundamentals.get("vix"))
        regime_params = get_regime_params(fundamentals.get("vix"))

        logger.info(
            f"Regime: {regime_info['regime']}  "
            f"(ADX_min={regime_info.get('adx_min')}  "
            f"SL={regime_info.get('sl_buffer')}×ATR  "
            f"TP={regime_info.get('tp_rr')}R)"
        )
        try:
            log_event(
                f"Regime: {regime_info['regime']}",
                "INFO",
                f"VIX {fundamentals.get('vix', 0):.1f} — {regime_info['description']}",
            )
        except Exception:
            pass

        # ── LLM strategy selector (pre-execution, cached for orchestrator) ─
        # Runs Grok + GPT-4 in parallel, then Claude synthesizes the result.
        # Total latency ~12-20s — completes before orchestrator executes signals.
        # Result is stored in monitor/llm_gate.py for zero-latency reads later.
        # Only runs if LLM_SELECTOR_ENABLED=true in .env.
        if settings.LLM_SELECTOR_ENABLED and regime_info.get("can_trade", True):
            try:
                from strategy.llm_selector import get_llm_strategy_selection
                from monitor.llm_gate import update_llm_selection

                # Build market context for the selector
                _llm_ctx = {
                    "close":          None,   # filled after BRT signal computed below
                    "ema20":          None,
                    "vwap":           None,
                    "adx":            None,
                    "rsi":            None,
                    "atr":            None,
                    "vix":            fundamentals.get("vix"),
                    "yield_10y":      fundamentals.get("yield_10y"),
                    "dxy":            fundamentals.get("dxy"),
                    "spy_vol_ratio":  fundamentals.get("spy_vol_ratio"),
                    "regime":         regime_info["regime"],
                    "vpoc_migration": None,
                    "headwinds":      fundamentals.get("headwinds", []),
                    "tailwinds":      fundamentals.get("tailwinds", []),
                    "brt_signal":     0,
                    "orb_signal":     0,
                    "session_hour":   datetime.now(ET).hour,
                }

                logger.info("[LLMSelector] Running ensemble selection (Grok + GPT-4 + Claude)…")
                llm_result = get_llm_strategy_selection(_llm_ctx)
                update_llm_selection(llm_result)

                logger.info(
                    f"[LLMSelector] strategy={llm_result.get('strategy')} "
                    f"bias={llm_result.get('bias')} "
                    f"conf={llm_result.get('confidence', 0):.2f} "
                    f"source={llm_result.get('source', '?')}"
                )
                try:
                    log_event(
                        f"LLM: {llm_result.get('strategy')} / {llm_result.get('bias')}",
                        "AI",
                        f"conf={llm_result.get('confidence', 0):.2f} — {llm_result.get('reasoning', '')[:80]}",
                    )
                except Exception:
                    pass

            except Exception as llm_err:
                logger.warning(f"[LLMSelector] Failed (non-fatal, proceeding without gate): {llm_err}")

        # ── Breakeven stop management (checked before new entries) ────────
        try:
            mes_pos = _router.get_position("MES")
            if mes_pos != 0:
                # Quick 15-min fetch for live price
                from data.fetcher import fetch_historical as _fh
                _df = _fh("MES", period="5d", timeframe_minutes=15)
                live_prices = {"MES": float(_df["close"].iloc[-1])}
                check_breakeven_moves(live_prices, _router)
        except Exception as be_err:
            logger.debug(f"Breakeven check skipped: {be_err}")

        # ── Orchestrator — runs all eligible strategies across all symbols ─
        executed = run_all_symbols(
            fundamentals  = fundamentals,
            regime_info   = regime_info,
            regime_params = regime_params,
            equity        = equity,
            session       = _session,
        )
        if executed:
            tags = [t["symbol"] + "/" + t["strategy"] for t in executed]
            logger.info(f"Tick executed {len(executed)} trade(s): {tags}")

        # ── Dashboard state snapshot (BRT signal for the Live tab) ────────
        try:
            from data.fetcher import fetch_historical as _fh
            from data.validator import validate_ohlcv, DataQualityError
            _df15 = _fh("MES", period="60d", timeframe_minutes=15)
            validate_ohlcv(_df15, timeframe_minutes=15)
            _df15 = prepare_break_retest(_df15, long_only=True, regime_params=regime_params)
            brt_signal     = get_latest_brt_signal(_df15)
            vpoc_migration = vpoc_trend(_df15)
        except Exception:
            brt_signal     = {}
            vpoc_migration = "NEUTRAL"

        try:
            daily   = get_daily_summary()
            et_hour = datetime.now(ET).hour
            update_bot_state({
                "brt_state":     "NEUTRAL",
                "close":         brt_signal.get("close"),
                "ema20":         brt_signal.get("ema20"),
                "atr":           brt_signal.get("atr"),
                "adx":           brt_signal.get("adx"),
                "rsi":           brt_signal.get("rsi"),
                "vwap":          brt_signal.get("vwap"),
                "pdh":           brt_signal.get("pdh"),
                "pdl":           brt_signal.get("pdl"),
                "swing_hi":      brt_signal.get("swing_hi"),
                "swing_lo":      brt_signal.get("swing_lo"),
                "prior_poc":     brt_signal.get("prior_poc"),
                "prior_vah":     brt_signal.get("prior_vah"),
                "prior_val":     brt_signal.get("prior_val"),
                "eqh":           brt_signal.get("eqh"),
                "eql":           brt_signal.get("eql"),
                "fvg_bull_low":  brt_signal.get("fvg_bull_low"),
                "fvg_bull_high": brt_signal.get("fvg_bull_high"),
                "fvg_bear_low":  brt_signal.get("fvg_bear_low"),
                "fvg_bear_high": brt_signal.get("fvg_bear_high"),
                "vpoc_migration": vpoc_migration,
                "regime":        regime_info["regime"],
                "vix":           fundamentals.get("vix"),
                "yield_10y":     fundamentals.get("yield_10y"),
                "dxy":           fundamentals.get("dxy"),
                "spy_vol_ratio": fundamentals.get("spy_vol_ratio"),
                "session_open":  1 if 9 <= et_hour < 16 else 0,
                "daily_pnl":     daily.get("total_pnl", 0.0),
                "trades_today":  daily.get("total", 0),
                "adx_min":       regime_info.get("adx_min"),
                "sl_buffer":     regime_info.get("sl_buffer"),
                "tp_rr":         regime_info.get("tp_rr"),
                "max_retest_bars": regime_info.get("max_retest_bars"),
                "headwinds":     fundamentals.get("headwinds", []),
                "tailwinds":     fundamentals.get("tailwinds", []),
                "paper_trading": 1 if settings.PAPER_TRADING else 0,
            })
        except Exception as db_err:
            logger.warning(f"State DB write failed (non-fatal): {db_err}")

        # ── Telegram summary (smart — only fires if noteworthy) ───────────
        notify_signal_check(brt_signal, fundamentals)

        # ── Update LLM selector context with real signal data for next tick ─
        # After we have brt_signal, we can store richer context in the gate cache
        # so the NEXT tick's LLM selector gets better technical data.
        if settings.LLM_SELECTOR_ENABLED and brt_signal:
            try:
                from monitor.llm_gate import get_llm_selection, update_llm_selection
                _cached = get_llm_selection()
                if _cached:
                    # Annotate the cached selection with the actual signal observed
                    _cached["_brt_signal_close"] = brt_signal.get("close")
                    _cached["_brt_signal_adx"]   = brt_signal.get("adx")
                    _cached["_brt_signal_rsi"]   = brt_signal.get("rsi")
                    update_llm_selection(_cached)
            except Exception:
                pass

        # ── AI Advisory (background — never delays execution) ─────────────
        if settings.LLM_ADVISORY_ENABLED:
            _market_ctx = {
                "close":          brt_signal.get("close"),
                "ema20":          brt_signal.get("ema20"),
                "vwap":           brt_signal.get("vwap"),
                "adx":            brt_signal.get("adx"),
                "rsi":            brt_signal.get("rsi"),
                "atr":            brt_signal.get("atr"),
                "vix":            fundamentals.get("vix"),
                "yield_10y":      fundamentals.get("yield_10y"),
                "dxy":            fundamentals.get("dxy"),
                "spy_vol_ratio":  fundamentals.get("spy_vol_ratio"),
                "regime":         regime_info["regime"],
                "vpoc_migration": vpoc_migration,
                "headwinds":      fundamentals.get("headwinds", []),
                "tailwinds":      fundamentals.get("tailwinds", []),
                "session_hour":   datetime.now(ET).hour,
            }
            _sig_val   = brt_signal.get("signal", 0)
            _sig_dir   = {1: "LONG", -1: "SHORT", 0: "FLAT"}.get(_sig_val, "FLAT")
            _strat_id  = "BRT" if _sig_val != 0 else "FLAT"
            _trigger   = "SIGNAL" if _sig_val != 0 else "HOURLY"
            threading.Thread(
                target=_run_advisory,
                args=(_market_ctx, _strat_id, _sig_dir, _trigger),
                daemon=True,
            ).start()

    except EquityUnavailable as eu:
        logger.warning(f"Tick skipped — equity unavailable: {eu}")
        try:
            log_event("Tick skipped — equity unavailable", "WARN", str(eu))
        except Exception:
            pass

    except RiskBlock as rb:
        logger.warning(f"Session-level risk block: {rb}")
        from monitor.alerts import notify_risk_block
        notify_risk_block(str(rb))

    except Exception as e:
        logger.exception(f"Unhandled error in signal check: {e}")
        notify_error(str(e))

    finally:
        logger.info("─── Signal check complete ───")


# ─── EOD flatten intraday positions ──────────────────────────────────────────

def run_eod_flatten() -> None:
    """
    Fires at 15:55 ET — 5 min before futures close.
    Flattens ALL intraday positions (futures) so nothing carries overnight.
    Swing/daily positions on Alpaca are left open intentionally.
    """
    logger.info("─── EOD flatten — closing intraday positions ───")
    try:
        _ensure_auth()
        from risk.manager import OPEN_TRADES, close_trade

        closed = []
        for symbol in list(FUTURES_SYMBOLS):
            try:
                pos = _router.get_position(symbol)
                if pos != 0:
                    _router.close_position(symbol)
                    if symbol in OPEN_TRADES:
                        close_trade(symbol)
                    closed.append(f"{symbol} ({pos:+d})")
                    logger.warning(f"EOD flatten: closed {symbol} ({pos:+d})")
            except Exception as e:
                logger.error(f"EOD flatten failed for {symbol}: {e}")

        if closed:
            msg = f"EOD flatten: closed {', '.join(closed)}"
            try:
                log_event(msg, "TRADE")
                notify_error(msg)
            except Exception:
                pass
        else:
            logger.info("EOD flatten: no intraday positions to close")

    except Exception as e:
        logger.exception(f"EOD flatten error: {e}")
        notify_error(f"EOD flatten failed: {e}")


# ─── End-of-day summary job ───────────────────────────────────────────────────

def run_eod_summary() -> None:
    """
    Fires at 15:30 ET.  Sends daily summary, cancels any dangling orders,
    and logs the day's P&L.
    """
    logger.info("─── End-of-day summary ───")
    try:
        _ensure_auth()

        # Cancel any unfilled orders left open (shouldn't happen with brackets,
        # but safety net in case of partial fills or manual interference).
        for sym in list(FUTURES_SYMBOLS):
            try:
                _router.cancel_all_orders(sym)
            except Exception:
                pass

        equity = _safe_get_equity()
        if equity <= 0:
            equity = _session["start_equity"]   # best guess

        # Compute today's final P&L from equity change
        pnl_today = equity - _session["start_equity"] if _session["start_equity"] > 0 else 0.0

        notify_daily_summary(
            trades_today = _session["trades_today"],
            pnl_today    = pnl_today,
            equity       = equity,
        )

        logger.info(
            f"EOD | trades={_session['trades_today']}  "
            f"P&L=${pnl_today:+.2f}  equity=${equity:,.2f}"
        )

    except Exception as e:
        logger.exception(f"Error in EOD summary: {e}")
        notify_error(f"EOD summary failed: {e}")


# ─── Pre-market AI briefing ───────────────────────────────────────────────────

def run_premarket_briefing() -> None:
    """
    Fires at 9:55 ET — 5 minutes before market open.
    Fetches live fundamentals + runs AI advisory with PRE_MARKET trigger.
    Sends a Telegram briefing so the trader knows what to expect today.
    """
    logger.info("─── Pre-market AI briefing ───")
    try:
        fundamentals = get_live_fundamentals()
        regime_info  = get_regime_info(fundamentals.get("vix"))

        market_ctx = {
            "close":         None,
            "ema20":         None,
            "vwap":          None,
            "adx":           None,
            "rsi":           None,
            "atr":           None,
            "vix":           fundamentals.get("vix"),
            "yield_10y":     fundamentals.get("yield_10y"),
            "dxy":           fundamentals.get("dxy"),
            "spy_vol_ratio": fundamentals.get("spy_vol_ratio"),
            "regime":        regime_info["regime"],
            "vpoc_migration": None,
            "headwinds":     fundamentals.get("headwinds", []),
            "tailwinds":     fundamentals.get("tailwinds", []),
            "session_hour":  9,
        }
        threading.Thread(
            target=_run_advisory,
            args=(market_ctx, "PRE_MARKET", "N/A", "PRE_MARKET"),
            daemon=True,
        ).start()

    except Exception as e:
        logger.warning(f"Pre-market briefing failed: {e}")


# ─── EOD Swing scan ──────────────────────────────────────────────────────────

def run_eod_swing_scan() -> None:
    """
    Fires at 16:05 ET Mon–Fri (after US market close, daily candles settled).

    Scans the full Momentum Swing universe, runs prepare() + get_signal()
    for each symbol, and places bracket orders via Alpaca for any valid setups.
    Also runs the proactive LLM swing scout (Grok → GPT-4 → Claude) to find
    catalyst-driven ideas and stores them in bot_state for the dashboard.
    Only runs if STRATEGY_SWING_ENABLED=true.
    """
    if not settings.STRATEGY_ENABLED.get("SWING", False):
        logger.info("EOD swing scan skipped — STRATEGY_SWING_ENABLED not set")
        return

    logger.info("─── EOD Swing scan starting ───")

    # ── One-shot override (relaxed filters / shrunk risk / expanded universe) ──
    # If data/.swing_override.json exists, apply it for THIS run only, then
    # restore settings and delete the file in the finally block.
    from strategy import swing_override
    override = swing_override.load_override()
    if override:
        swing_override.apply(override)

    try:
        _ensure_auth()
        equity = _safe_get_equity()
        if equity <= 0:
            logger.warning("EOD swing: could not read equity — skipping")
            return

        fundamentals  = get_live_fundamentals()
        regime_info   = get_regime_info(fundamentals.get("vix"))
        regime_params = get_regime_params(fundamentals.get("vix"))

        _session["start_equity"] = _session.get("start_equity") or equity

        executed = run_all_symbols(
            fundamentals  = fundamentals,
            regime_info   = regime_info,
            regime_params = regime_params,
            equity        = equity,
            session       = _session,
        )

        swing_executed = [t for t in executed if t.get("strategy") == "SWING"]
        if swing_executed:
            tags = [f"{t['symbol']} {t.get('direction_str','?')}" for t in swing_executed]
            logger.info(f"EOD swing placed {len(swing_executed)} order(s): {tags}")
            try:
                from monitor.alerts import send_telegram
                lines = [f"📈 *Swing EOD Scan* — {len(swing_executed)} setup(s) entered"]
                for t in swing_executed:
                    lines.append(
                        f"  • {t['symbol']} {t.get('direction_str','LONG')} | "
                        f"entry≈{t.get('entry',0):.2f} SL={t.get('sl',0):.2f} TP={t.get('tp',0):.2f}"
                    )
                send_telegram("\n".join(lines))
            except Exception:
                pass
        else:
            logger.info("EOD swing: no setups met criteria today")

        # ── LLM Swing Scout (proactive catalyst ideas) ────────────────────
        # Runs Grok → GPT-4 → Claude in sequence to identify catalyst-driven
        # long swing ideas. Results stored in bot_state for dashboard display.
        try:
            import json as _json
            from strategy.llm_swing_scout import run_swing_scout
            logger.info("[SwingScout] Running proactive LLM opportunity scan…")
            scout_result = run_swing_scout({
                "vix":       fundamentals.get("vix", 18.0),
                "dxy":       fundamentals.get("dxy", 104.0),
                "yield_10y": fundamentals.get("yield_10y", 4.3),
            })
            update_bot_state({"swing_scout": _json.dumps(scout_result)})
            top_count = len(scout_result.get("top_ideas", []))
            logger.info(f"[SwingScout] {top_count} top idea(s) stored in bot_state")
            if top_count > 0:
                try:
                    from monitor.alerts import send_telegram
                    lines = [f"🤖 *LLM Swing Scout* — {top_count} opportunity(ies) identified"]
                    lines.append(scout_result.get("market_note", ""))
                    for idea in scout_result.get("top_ideas", []):
                        lines.append(
                            f"  • *{idea['symbol']}* [{idea.get('conviction_tier','?')}] "
                            f"{idea.get('thesis','')}"
                        )
                    send_telegram("\n".join(lines))
                except Exception:
                    pass
        except Exception as scout_err:
            logger.warning(f"[SwingScout] non-fatal failure: {scout_err}")

    except Exception as e:
        logger.error(f"EOD swing scan failed: {e}", exc_info=True)
    finally:
        # Always restore settings and consume the override file, even on error
        if override:
            try:
                swing_override.consume()
            finally:
                swing_override.restore()


# ─── Scheduler setup ──────────────────────────────────────────────────────────

def main() -> None:
    init_db()  # ensure SQLite tables exist before scheduler fires

    # Restore open trade registry from SQLite (crash recovery).
    # If the process restarted mid-trade, OPEN_TRADES would otherwise be empty
    # and risk/sizing checks would behave as if we're flat when we're not.
    try:
        load_open_trades_from_db()
    except Exception as e:
        logger.warning(f"Could not restore open trades on startup: {e}")

    # Reconcile with broker — clear any trades the broker already closed
    # while we were offline (SL/TP filled, manual close, etc.)
    try:
        from risk.manager import clear_stale_open_trades, OPEN_TRADES
        if OPEN_TRADES:
            _router.connect_all()
            live_positions: dict[str, int] = {}
            for sym in list(OPEN_TRADES.keys()):
                try:
                    live_positions[sym] = _router.get_position(sym)
                except Exception:
                    pass  # can't check — leave it in registry (safe side)
            if live_positions:
                clear_stale_open_trades(live_positions)
    except Exception as e:
        logger.warning(f"Startup position reconciliation failed (non-fatal): {e}")

    from strategy.registry import get_all as _get_all_strats
    enabled = [s.name for s in _get_all_strats() if settings.STRATEGY_ENABLED.get(s.name)]
    logger.info("=" * 55)
    logger.info("  TRADEZ — Multi-Strategy Automated Trading Bot")
    logger.info(f"  Mode       : {'PAPER' if settings.PAPER_TRADING else '*** LIVE ***'}")
    logger.info(f"  Broker     : Tradovate ({'DEMO' if settings.PAPER_TRADING else 'LIVE'})")
    logger.info(f"  Strategies : {', '.join(enabled) if enabled else 'none enabled'}")
    logger.info(f"  Symbols    : {', '.join(settings.ACTIVE_SYMBOLS)}")
    logger.info(f"  Conflict   : {settings.STRATEGY_CONFLICT_RESOLUTION}")
    logger.info(f"  Session    :  9:02 – 15:47 ET  (Mon–Fri, every 15min)")
    logger.info("=" * 55)

    scheduler = BlockingScheduler(timezone=ET)

    # 15-min signal check: every 15 minutes, 10am–3pm ET, Mon–Fri
    scheduler.add_job(
        func    = run_signal_check,
        trigger = CronTrigger(
            day_of_week = "mon-fri",
            hour        = "9-15",
            minute      = "2,17,32,47",
            timezone    = ET,
        ),
        id        = "signal_check",
        name      = "MES B&R Signal Check",
        misfire_grace_time = 120,   # tolerate up to 2 min late start
    )

    # End-of-day summary at 15:30 ET
    scheduler.add_job(
        func    = run_eod_summary,
        trigger = CronTrigger(
            day_of_week = "mon-fri",
            hour        = "15",
            minute      = "30",
            timezone    = ET,
        ),
        id   = "eod_summary",
        name = "End-of-Day Summary",
    )

    # EOD flatten intraday positions at 15:55 ET (5 min before futures close)
    scheduler.add_job(
        func    = run_eod_flatten,
        trigger = CronTrigger(
            day_of_week = "mon-fri",
            hour        = "15",
            minute      = "55",
            timezone    = ET,
        ),
        id   = "eod_flatten",
        name = "EOD Flatten Intraday Positions",
    )

    # EOD Momentum Swing scan at 16:05 ET (after daily candles settle)
    if settings.STRATEGY_ENABLED.get("SWING", False):
        scheduler.add_job(
            func    = run_eod_swing_scan,
            trigger = CronTrigger(
                day_of_week = "mon-fri",
                hour        = "16",
                minute      = "5",
                timezone    = ET,
            ),
            id   = "eod_swing_scan",
            name = "EOD Momentum Swing Scan",
        )
        logger.info("EOD Swing scan job registered (16:05 ET Mon-Fri)")

    # Pre-market AI briefing at 9:55 ET (before first signal check)
    if settings.LLM_ADVISORY_ENABLED:
        scheduler.add_job(
            func    = run_premarket_briefing,
            trigger = CronTrigger(
                day_of_week = "mon-fri",
                hour        = "9",
                minute      = "55",
                timezone    = ET,
            ),
            id   = "premarket_briefing",
            name = "Pre-Market AI Briefing",
        )

    logger.info("Scheduler started. Press Ctrl-C to stop.")
    logger.info("Next signal check jobs:")
    for job in scheduler.get_jobs():
        next_run = getattr(job, 'next_run_time', None) or getattr(job, '_get_run_times', None)
        logger.info(f"  [{job.id}]  {job.name}")

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Shutdown requested — stopping scheduler.")
        notify_error("Bot stopped manually (KeyboardInterrupt).")
        scheduler.shutdown(wait=False)


if __name__ == "__main__":
    main()
