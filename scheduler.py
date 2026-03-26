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
import threading
import time
from datetime import datetime, date

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz

from config import settings
from data.fetcher import fetch_historical
from data.fundamentals import get_live_fundamentals, print_fundamentals
from data.trade_log import init_db, log_trade, log_event, update_bot_state, get_daily_summary
from data.validator import validate_ohlcv, DataQualityError, data_quality_summary
from strategy.break_retest import prepare_break_retest, get_latest_brt_signal
from strategy.volume_profile import vpoc_trend
from strategy.regime import get_regime_params, get_regime_info
from risk.manager import (
    RiskBlock, check_all, check_daily_drawdown,
    load_open_trades_from_db, clear_stale_open_trades, check_breakeven_moves,
    record_trade_outcome,
)
from strategy.cot_filter import get_cot_bias, COT_BIAS_SHORT
from monitor.performance import brt_monitor
from execution.router import router as _router
from monitor.alerts import (
    notify_signal_check,
    notify_entry,
    notify_exit,
    notify_risk_block,
    notify_daily_summary,
    notify_error,
    notify_llm_advisory,
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
        open_position = _router.get_position("MES")
        logger.info(f"Open MES position: {open_position:+d} contracts")

        # ── Price data (with data quality validation) ─────────────────────
        df = fetch_historical("MES", period="60d", timeframe_minutes=15)

        # Validate data before running signal engine.
        # Bad ticks or stale data can generate false signals on corrupted bars.
        try:
            validate_ohlcv(df, timeframe_minutes=15)
        except DataQualityError as dqe:
            logger.warning(f"Data quality check failed — skipping tick: {dqe}")
            try:
                log_event("Data quality check failed — tick skipped", "WARN", str(dqe))
            except Exception:
                pass
            return  # skip this tick entirely — don't trade on bad data

        df = prepare_break_retest(df, long_only=True, regime_params=regime_params)

        # ── Strategy signals (pure BRT) ───────────────────────────────
        brt_signal     = get_latest_brt_signal(df)
        vpoc_migration = vpoc_trend(df)  # "RISING" / "FALLING" / "NEUTRAL"

        signal      = brt_signal
        strategy_id = "BRT" if brt_signal.get("signal", 0) != 0 else "FLAT"

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
                "prior_poc":    signal.get("prior_poc"),
                "prior_vah":    signal.get("prior_vah"),
                "prior_val":    signal.get("prior_val"),
                "eqh":          signal.get("eqh"),
                "eql":          signal.get("eql"),
                "fvg_bull_low":  signal.get("fvg_bull_low"),
                "fvg_bull_high": signal.get("fvg_bull_high"),
                "fvg_bear_low":  signal.get("fvg_bear_low"),
                "fvg_bear_high": signal.get("fvg_bear_high"),
                "vpoc_migration": vpoc_migration,
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

        # ── AI Advisory (background thread — never delays execution) ────────
        # Uses LLM_ADVISORY_ENABLED (separate from LLM_SELECTOR_ENABLED).
        # Advisory runs for market intelligence + logging regardless of whether
        # the strategy selector is active. Decoupled intentionally.
        if settings.LLM_ADVISORY_ENABLED:
            _market_ctx = {
                "close":         brt_signal.get("close"),
                "ema20":         brt_signal.get("ema20"),
                "vwap":          brt_signal.get("vwap"),
                "adx":           brt_signal.get("adx"),
                "rsi":           brt_signal.get("rsi"),
                "atr":           brt_signal.get("atr"),
                "vix":           fundamentals.get("vix"),
                "yield_10y":     fundamentals.get("yield_10y"),
                "dxy":           fundamentals.get("dxy"),
                "spy_vol_ratio": fundamentals.get("spy_vol_ratio"),
                "regime":        regime_info["regime"],
                "vpoc_migration": vpoc_migration,
                "headwinds":     fundamentals.get("headwinds", []),
                "tailwinds":     fundamentals.get("tailwinds", []),
                "session_hour":  datetime.now(ET).hour,
            }
            _sig_dir = {1: "LONG", -1: "SHORT", 0: "FLAT"}.get(
                signal.get("signal", 0), "FLAT"
            )
            _trigger = "SIGNAL" if strategy_id != "FLAT" else "HOURLY"
            threading.Thread(
                target=_run_advisory,
                args=(_market_ctx, strategy_id, _sig_dir, _trigger),
                daemon=True,
            ).start()

        # ── Breakeven stop management (checked each tick before new entries) ─
        try:
            live_prices = {"MES": float(signal.get("close", 0))}
            check_breakeven_moves(live_prices, _router)
        except Exception as be_err:
            logger.debug(f"Breakeven check skipped: {be_err}")

        # ── COT directional bias filter ────────────────────────────────────
        cot_bias = "NEUTRAL"
        if settings.COT_FILTER_ENABLED:
            try:
                cot_bias = get_cot_bias("MES")
                if cot_bias != "NEUTRAL":
                    logger.info(f"COT bias: {cot_bias}")
            except Exception as cot_err:
                logger.debug(f"COT fetch failed (non-fatal, defaulting NEUTRAL): {cot_err}")
                cot_bias = "NEUTRAL"

        # ── Entry logic ───────────────────────────────────────────────────
        if signal.get("signal", 0) != 0:
            # COT filter: block long entries when Leveraged Funds at extreme net long
            # (contrarian SHORT signal — they are the last buyer, not the first).
            if signal.get("signal", 0) == 1 and cot_bias == COT_BIAS_SHORT:
                logger.info(
                    "COT filter: LONG entry blocked — Leveraged Funds at extreme net long "
                    "(contrarian short signal). Waiting for COT to normalize."
                )
                try:
                    log_event(
                        "COT filter blocked LONG entry", "WARN",
                        "Leveraged Funds at extreme net long — contrarian short bias"
                    )
                except Exception:
                    pass
            else:
                try:
                    # Pre-entry performance gate — pause if rolling metrics in PAUSE state
                    perf_status = brt_monitor.get_status()
                    if perf_status == "PAUSE":
                        raise RiskBlock(
                            f"Performance monitor: new entries paused. "
                            f"Rolling win rate has been below threshold for sustained period. "
                            f"Review rolling metrics before resuming."
                        )

                    # FIX: check_all signature is (symbol, fundamentals, equity, position, signal)
                    contracts = check_all(
                        "MES", fundamentals, equity, open_position, signal,
                        trades_today=_session["trades_today"],
                    )

                    direction   = int(signal["signal"])
                    entry_price = float(signal["close"])
                    sl_price    = float(signal["stop_loss"])
                    tp_price    = float(signal["take_profit"])
                    level_type  = signal.get("level_type", "")
                    retest_lvl  = float(signal.get("retest_level", entry_price))
                    sweep_flag  = signal.get("liquidity_sweep", 0)

                    logger.info(
                        f"Placing {'LONG' if direction == 1 else 'SHORT'} bracket "
                        f"x{contracts} | entry≈{entry_price:.2f} "
                        f"SL={sl_price:.2f} TP={tp_price:.2f}"
                        f"  COT={cot_bias}"
                        f"{'  [SWEEP ✓]' if sweep_flag else ''}"
                    )

                    _router.place_bracket_order(
                        symbol    = "MES",
                        qty       = contracts,
                        sl_price  = sl_price,
                        tp_price  = tp_price,
                        direction = direction,
                    )

                    # Log activity event
                    try:
                        log_event(
                            f"{'LONG' if direction == 1 else 'SHORT'} entry — "
                            f"{level_type} @ {entry_price:.2f}",
                            "TRADE",
                            f"SL {sl_price:.2f} | TP {tp_price:.2f} | "
                            f"{contracts} contract(s) | COT={cot_bias}",
                        )
                    except Exception:
                        pass

                    # Log trade to SQLite (includes cot_bias for attribution analysis)
                    try:
                        log_trade(
                            direction       = "LONG" if direction == 1 else "SHORT",
                            level_type      = level_type,
                            entry_price     = entry_price,
                            stop_loss       = sl_price,
                            take_profit     = tp_price,
                            contracts       = contracts,
                            regime          = regime_info.get("regime"),
                            vix             = fundamentals.get("vix"),
                            liquidity_sweep = int(sweep_flag),
                            cot_bias        = cot_bias,
                        )
                    except Exception as db_err:
                        logger.warning(f"Trade log write failed (non-fatal): {db_err}")

                    # Update session counters
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
                    try:
                        log_event(f"Risk block: {rb}", "WARN")
                    except Exception:
                        pass

    except EquityUnavailable as eu:
        # Equity could not be confirmed — skip this tick, do not trade.
        # This is intentional behaviour, not an error. Next tick will retry.
        logger.warning(f"Tick skipped — equity unavailable: {eu}")
        try:
            log_event("Tick skipped — equity unavailable", "WARN", str(eu))
        except Exception:
            pass

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

    logger.info("=" * 50)
    logger.info("  TRADEZ — Automated Paper Trading Bot")
    logger.info(f"  Mode   : {'PAPER' if settings.PAPER_TRADING else '*** LIVE ***'}")
    logger.info(f"  Broker : Tradovate ({'DEMO' if settings.PAPER_TRADING else 'LIVE'})")
    logger.info(f"  Symbol : MES  (BRT — Break & Retest, 15min)")
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
