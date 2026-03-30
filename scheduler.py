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
import sys
import threading
import time
from datetime import datetime, date

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
from execution.router import router as _router
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
        logging.FileHandler("tradez.log"),
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
        1. SQLite bot_state (dashboard picks it up via WebSocket)
        2. SQLite events feed (dashboard activity log)
        3. Telegram (optional — only on SIGNAL or PRE_MARKET triggers)
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

        # 1. Persist in bot_state for dashboard
        try:
            update_bot_state({"llm_advisory": _json.dumps(advisory)})
        except Exception:
            pass

        # 2. Log to events feed
        flags_str = " | ".join(advisory.get("risk_flags", [])) or "none"
        try:
            log_event(
                f"AI: {advisory.get('headline', '')}",
                "AI",
                f"{advisory.get('brief', '')}  |  Flags: {flags_str}",
            )
        except Exception:
            pass

        # 3. Telegram — only for signals and pre-market (not every quiet hour)
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
        equity = _router.get_broker_for("MES").get_account_equity()
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

def run_signal_check() -> None:
    """
    Core job. Runs every 15 min, Mon–Fri, 9am–4pm ET.

    Sequence:
        1. Authenticate all brokers
        2. Get account equity → init session if new day
        3. Check daily drawdown (raises RiskBlock if hit)
        4. Fetch live fundamentals → determine regime
        5. Call orchestrator.run_all_symbols() — runs every eligible strategy
           across every active symbol, resolves conflicts, places orders
        6. Update dashboard state (SQLite) + send Telegram summary
        7. Run AI advisory in background thread
    """
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
        _router.cancel_all_orders("MES")

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
