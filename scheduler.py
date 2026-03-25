"""
scheduler.py

Automated paper-trading bot for MES Break & Retest.

How it works:
    - APScheduler fires every hour at :02 (Mon–Fri, 10am–3pm ET)
    - Each tick: authenticates to Tradovate → checks daily drawdown → fetches
      live fundamentals → reads current MES position → runs B&R signal engine →
      runs risk checks → places bracket order if approved → sends Telegram alert
    - A second job at 15:30 ET sends the daily summary
    - On startup, records session_start_equity once so drawdown is tracked

Usage:
    python scheduler.py               # demo account (PAPER_TRADING=true)
    PAPER_TRADING=false python scheduler.py  # live — only when you're ready

Prerequisites:
    - .env contains TRADOVATE_USERNAME, TRADOVATE_PASSWORD, TRADOVATE_CID,
      TRADOVATE_SEC, TRADOVATE_APP_ID, TELEGRAM_TOKEN, TELEGRAM_CHAT_ID
    - pip install -r requirements.txt

Stopping:
    Ctrl-C   — graceful shutdown (sends Telegram alert)
"""

import logging
import sys
import time
from datetime import datetime, date

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz

from config import settings
from data.fetcher import fetch_historical
from data.fundamentals import get_live_fundamentals, print_fundamentals
from data.trade_log import init_db, log_trade, log_event, update_bot_state, get_daily_summary
from strategy.break_retest import prepare_break_retest, get_latest_brt_signal
from strategy.regime import get_regime_params, get_regime_info
from strategy.orb import get_orb_signal_15min
from risk.manager import RiskBlock, check_all, check_daily_drawdown
from execution.tradovate import (
    authenticate,
    get_account_equity,
    get_open_mes_position,
    place_bracket_order,
    cancel_all_mes_orders,
)
from monitor.alerts import (
    notify_signal_check,
    notify_entry,
    notify_exit,
    notify_risk_block,
    notify_daily_summary,
    notify_error,
)

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


# ─── Tradovate helpers ────────────────────────────────────────────────────────

def _ensure_auth() -> None:
    """Authenticate to Tradovate (token auto-renews if near expiry)."""
    from execution.tradovate import _session, _get_token
    _get_token()   # handles first-time auth + renewal


def _safe_get_equity() -> float:
    """Return account equity, defaulting to $3,000 if API returns 0."""
    try:
        equity = get_account_equity()
        if equity <= 0:
            logger.warning("Account equity returned 0 — defaulting to $3,000")
            return 3000.0
        return equity
    except Exception as e:
        logger.warning(f"Could not fetch equity: {e} — defaulting to $3,000")
        return 3000.0


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
    Core hourly job.  Runs every :02 past the hour, Mon–Fri, 10am–3pm ET.

    Sequence:
        1. Connect IBKR
        2. Get account equity → init session if new day
        3. Check daily drawdown (raises RiskBlock if hit)
        4. Fetch live fundamentals
        5. Get current MES position
        6. Fetch 1h price data, run B&R signal engine
        7. If signal != 0, run risk checks → place bracket order
        8. Send Telegram summary
        9. Disconnect
    """
    logger.info("─── Hourly signal check starting ───")
    try: log_event("Signal check started", "INFO")
    except Exception: pass

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

        # ── Regime detection — drives adaptive BRT parameters ─────────────
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
                f"VIX {fundamentals.get('vix', '?'):.1f} — {regime_info['description']}"
            )
        except Exception: pass

        # ── Current MES position ──────────────────────────────────────────
        open_position = get_open_mes_position()
        logger.info(f"Open MES position: {open_position:+d} contracts")

        # ── Price data (regime params injected into strategy) ─────────────
        df = fetch_historical("MES", period="60d", timeframe_minutes=15)
        df = prepare_break_retest(df, long_only=True, regime_params=regime_params)

        # ── Strategy signals (B&R priority; ORB fallback) ─────────────
        brt_signal = get_latest_brt_signal(df)
        orb_signal = get_orb_signal_15min(df)

        if brt_signal.get("signal", 0) != 0:
            signal      = brt_signal
            strategy_id = "BRT"
        elif orb_signal.get("signal", 0) != 0:
            signal      = orb_signal
            strategy_id = "ORB"
        else:
            signal      = brt_signal   # flat — used for Telegram summary
            strategy_id = "FLAT"

        logger.info(
            f"[{strategy_id}] Signal={signal.get('signal', 0):+d}  "
            f"ADX={signal.get('adx', 0):.1f}  "
            f"RSI={signal.get('rsi', 0):.1f}  "
            f"Close={signal.get('close', 0):.2f}"
        )

        # ── Push live state snapshot to SQLite for dashboard ──────────────
        try:
            daily = get_daily_summary()
            et_hour = datetime.now(ET).hour
            update_bot_state({
                "brt_state":    "NEUTRAL",  # refined below if in a watch state
                "close":        signal.get("close"),
                "ema20":        signal.get("ema20"),
                "atr":          signal.get("atr"),
                "adx":          signal.get("adx"),
                "rsi":          signal.get("rsi"),
                "vwap":         signal.get("vwap"),
                "pdh":          signal.get("pdh"),
                "pdl":          signal.get("pdl"),
                "swing_hi":     signal.get("swing_hi"),
                "swing_lo":     signal.get("swing_lo"),
                "regime":       regime_info["regime"],
                "vix":          fundamentals.get("vix"),
                "yield_10y":    fundamentals.get("yield_10y"),
                "dxy":          fundamentals.get("dxy"),
                "spy_vol_ratio": fundamentals.get("spy_vol_ratio"),
                "session_open": 1 if 10 <= et_hour < 15 else 0,
                "daily_pnl":    daily.get("total_pnl", 0.0),
                "trades_today": daily.get("total", 0),
                "adx_min":      regime_info.get("adx_min"),
                "sl_buffer":    regime_info.get("sl_buffer"),
                "tp_rr":        regime_info.get("tp_rr"),
                "max_retest_bars": regime_info.get("max_retest_bars"),
                "headwinds":    fundamentals.get("headwinds", []),
                "tailwinds":    fundamentals.get("tailwinds", []),
                "paper_trading": 1 if settings.PAPER_TRADING else 0,
            })
        except Exception as db_err:
            logger.warning(f"State DB write failed (non-fatal): {db_err}")

        # ── Telegram hourly summary (smart — only fires if noteworthy) ────
        notify_signal_check(signal, fundamentals)

        # ── Entry logic ───────────────────────────────────────────────────
        if signal.get("signal", 0) != 0:
            try:
                contracts = check_all(fundamentals, equity, open_position, signal)

                direction  = int(signal["signal"])   # 1 = long, -1 = short
                entry_price = float(signal["close"])
                sl_price    = float(signal["stop_loss"])
                tp_price    = float(signal["take_profit"])
                level_type  = signal.get("level_type", "")
                retest_lvl  = float(signal.get("retest_level", entry_price))

                logger.info(
                    f"Placing {'LONG' if direction == 1 else 'SHORT'} bracket "
                    f"x{contracts} | entry≈{entry_price:.2f} "
                    f"SL={sl_price:.2f} TP={tp_price:.2f}"
                )

                place_bracket_order(
                    contracts = contracts,
                    sl_price  = sl_price,
                    tp_price  = tp_price,
                    direction = direction,
                )

                # Log activity event
                try:
                    log_event(
                        f"{'LONG' if direction == 1 else 'SHORT'} entry — {level_type} @ {entry_price:.2f}",
                        "TRADE",
                        f"SL {sl_price:.2f} | TP {tp_price:.2f} | {contracts} contract(s)"
                    )
                except Exception: pass

                # Log trade to SQLite
                try:
                    log_trade(
                        direction   = "LONG" if direction == 1 else "SHORT",
                        level_type  = level_type,
                        entry_price = entry_price,
                        stop_loss   = sl_price,
                        take_profit = tp_price,
                        contracts   = contracts,
                        regime      = regime_info.get("regime"),
                        vix         = fundamentals.get("vix"),
                    )
                except Exception as db_err:
                    logger.warning(f"Trade log write failed (non-fatal): {db_err}")

                # Update session counters (P&L filled in by exit logic, see below)
                _session["trades_today"] += 1

                notify_entry(
                    contracts    = contracts,
                    entry_price  = entry_price,
                    sl_price     = sl_price,
                    tp_price     = tp_price,
                    level_type   = level_type,
                    retest_level = retest_lvl,
                )

            except RiskBlock as rb:
                logger.warning(f"Risk block: {rb}")
                notify_risk_block(str(rb))
                try: log_event(f"Risk block: {rb}", "WARN")
                except Exception: pass

    except RiskBlock as rb:
        # Daily drawdown limit hit — block for the rest of the session
        logger.warning(f"Session-level risk block: {rb}")
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
        cancel_all_mes_orders()

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


# ─── Scheduler setup ──────────────────────────────────────────────────────────

def main() -> None:
    init_db()  # ensure SQLite tables exist before scheduler fires

    logger.info("=" * 50)
    logger.info("  TRADEZ — Automated Paper Trading Bot")
    logger.info(f"  Mode   : {'PAPER' if settings.PAPER_TRADING else '*** LIVE ***'}")
    logger.info(f"  Broker : Tradovate ({'DEMO' if settings.PAPER_TRADING else 'LIVE'})")
    logger.info(f"  Symbol : MES  (Break & Retest, 15min)")
    logger.info(f"  Session: 10:02 – 15:02 ET  (Mon–Fri)")
    logger.info("=" * 50)

    scheduler = BlockingScheduler(timezone=ET)

    # Hourly signal check: every :02 past the hour, 10am–3pm ET, Mon–Fri
    scheduler.add_job(
        func    = run_signal_check,
        trigger = CronTrigger(
            day_of_week = "mon-fri",
            hour        = "10-15",
            minute      = "2",
            timezone    = ET,
        ),
        id        = "signal_check",
        name      = "MES B&R Signal Check",
        misfire_grace_time = 300,   # tolerate up to 5 min late start
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

    logger.info("Scheduler started. Press Ctrl-C to stop.")
    logger.info("Next signal check jobs:")
    for job in scheduler.get_jobs():
        logger.info(f"  [{job.id}]  next run: {job.next_run_time}")

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Shutdown requested — stopping scheduler.")
        notify_error("Bot stopped manually (KeyboardInterrupt).")
        scheduler.shutdown(wait=False)


if __name__ == "__main__":
    main()
